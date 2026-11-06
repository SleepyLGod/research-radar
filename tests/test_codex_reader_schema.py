"""Reader-only Codex schema constraints do not leak into other model tasks."""

import json
import shlex
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS, source_response
from test_paper_reading import _artifact, _claim_units_fixture

from research_radar.analysis import cli_providers
from research_radar.analysis.cli_providers import CodexCliProvider
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import (
    _reading_response_example,
    model_paper_reading_with_attempts,
    parse_paper_reading,
)
from research_radar.analysis.providers import Message
from research_radar.analysis.reader_input import check_reader_input
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.analysis.review import review_publication_facts
from research_radar.analysis.source_references import build_source_index
from research_radar.exceptions import AnalysisError


def provider() -> CodexCliProvider:
    """Use an existing local executable only to resolve a path; execution is replaced."""
    instance = CodexCliProvider(name="codex", command="/usr/bin/true", reasoning_effort="xhigh")
    instance.reader_contexts = OFFLINE_READER_CONTEXTS
    return instance


def fixture() -> str:
    return _claim_units_fixture(["Memory benchmark fixture."])


def fake_execution(monkeypatch: pytest.MonkeyPatch, answer: str) -> list[dict[str, object]]:
    """Capture schema bytes before the existing temporary process directory is cleaned up."""
    calls = []
    def run(command: list[str], name: str, **kwargs: object) -> None:
        schema = None
        if "--output-schema" in command:
            schema_path = Path(command[command.index("--output-schema") + 1])
            assert schema_path.stat().st_mode & 0o777 == 0o600
            schema = json.loads(schema_path.read_text())
        calls.append({"command": command, "schema": schema, **kwargs})
        Path(command[command.index("--output-last-message") + 1]).write_text(
            source_response(answer, [Message("user", kwargs["prompt"])]))
    monkeypatch.setattr(cli_providers, "_run_command", run)
    return calls


def test_reader_uses_complete_schema_and_does_not_mutate_shared_provider(monkeypatch) -> None:
    instance = provider()
    calls = fake_execution(monkeypatch, fixture())
    result = model_paper_reading_with_attempts(_artifact(), instance, model="fake-reader",
                                             facts_only=True)
    assert result.reading.claim_units
    assert len(calls) == 1
    assert calls[0]["schema"] == paper_reading_response_schema(
        facts_only=True, source_ids=build_source_index(_artifact()).source_ids)
    assert calls[0]["schema"]["properties"]["deep_readings"]["items"]["properties"][
        "reader_explanation"]["properties"] == {}
    assert calls[0]["command"][-1] == "-"
    assert calls[0]["stdin_text"] == calls[0]["prompt"]
    assert 'model_reasoning_effort="xhigh"' in calls[0]["command"]
    instance.complete([Message("user", "Other task, no Reader schema.")], model="fake-reader")
    assert calls[1]["schema"] is None


def test_schema_counts_toward_full_input_plan() -> None:
    instance = provider()
    messages = [Message("user", "Read full paper.")]
    plain = check_reader_input(messages, instance, model="fake-reader")
    constrained = check_reader_input(messages, instance, model="fake-reader",
                                    response_schema=paper_reading_response_schema(facts_only=True))
    assert constrained["input_utf8_bytes"] > plain["input_utf8_bytes"]


def test_fact_verifier_reuses_codex_with_its_own_schema_not_the_reader_schema(monkeypatch) -> None:
    from test_publication_composition import candidates

    from research_radar.analysis.review_targets import build_review_targets

    instance = provider()
    reading, claim = candidates()
    artifact = replace(_artifact(), source=replace(_artifact().source, url=reading.source_url),
                       text=claim.evidence[0].quote)
    contract = build_review_targets([claim], "")
    calls = fake_execution(monkeypatch, json.dumps({"decisions": {key: {
        "status": "supported", "reason": "Offline source fixture.",
        "evidence_refs": list(target["direct_evidence"])}
        for key, target in contract.targets.items()}}))
    reviewed = review_publication_facts([claim], instance, model="fake-reviewer",
        readings=[reading], artifacts=[artifact])
    assert reviewed.claims[0].is_publishable()
    assert calls[0]["schema"] == contract.schema
    assert "deep_readings" not in calls[0]["schema"]["properties"]


def test_real_subprocess_fixture_receives_schema_file_and_full_stdin(tmp_path: Path) -> None:
    directory = tmp_path / "Research Tools"
    directory.mkdir()
    executable = directory / "offline reader.py"
    record = tmp_path / "received.json"
    executable.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "schema = json.loads(Path(args[args.index('--output-schema') + 1]).read_text())\n"
        f"Path({str(record)!r}).write_text(json.dumps({{'args': args, 'schema': schema, "
        "'stdin': (prompt := sys.stdin.read())}))\n"
        f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
        "from reader_fixtures import source_response\n"
        "from research_radar.analysis.providers import Message\n"
        f"Path(args[args.index('--output-last-message') + 1]).write_text(\n"
        f"source_response({fixture()!r}, [Message('user', prompt)]))\n"
    )
    instance = CodexCliProvider(name="codex", command=(
        f"{shlex.quote(sys.executable)} {shlex.quote(str(executable))}"))
    instance.reader_contexts = OFFLINE_READER_CONTEXTS
    original = replace(_artifact(), text=_artifact().text * 5000 + "\nFULL INPUT END 标记")
    result = model_paper_reading_with_attempts(original, instance,
        model="fake-reader", facts_only=True)
    captured = json.loads(record.read_text())
    assert result.reading.claim_units
    import re

    assert original.text in re.sub(r"\nsource_id=b[0-9a-f]{16}:\d+\n", "", captured["stdin"])
    assert captured["args"][-1] == "-"
    assert captured["schema"] == paper_reading_response_schema(
        facts_only=True, source_ids=build_source_index(original).source_ids)


def test_cached_reader_separates_schema_and_plain_calls_and_keeps_counters(
    monkeypatch, tmp_path: Path,
) -> None:
    calls = fake_execution(monkeypatch, fixture())
    cached = CachedLLMProvider(provider(), cache_dir=tmp_path, task_name="deep_reading")
    for _ in range(2):
        model_paper_reading_with_attempts(_artifact(), cached, model="fake-reader", facts_only=True)
    assert len(calls) == 1 and cached.hit_count == cached.miss_count == 1
    # The same message/model must miss without the schema identity.
    messages = [Message("user", "same input")]
    cached.complete_with_schema(messages, model="fake-reader",
                                response_schema=paper_reading_response_schema(facts_only=True))
    cached.complete(messages, model="fake-reader")
    assert len(calls) == 3
    assert cached.hit_count == 1 and cached.miss_count == 3


def test_facts_only_and_full_reader_schemas_do_not_share_cache(monkeypatch, tmp_path: Path) -> None:
    calls = fake_execution(monkeypatch, fixture())
    cached = CachedLLMProvider(provider(), cache_dir=tmp_path, task_name="deep_reading")
    messages = [Message("user", "same source")]
    for facts_only in (True, False, False):
        cached.complete_with_schema(messages, model="fake-reader",
            response_schema=paper_reading_response_schema(facts_only=facts_only))
    assert len(calls) == 2 and cached.hit_count == 1
    assert calls[0]["schema"] != calls[1]["schema"]


def test_backend_schema_error_never_falls_back_to_plain_output(monkeypatch) -> None:
    calls = []
    def fail(command, *args, **kwargs):
        calls.append(command)
        raise AnalysisError("Offline schema rejection.")
    monkeypatch.setattr(cli_providers, "_run_command", fail)
    with pytest.raises(AnalysisError, match="schema rejection"):
        model_paper_reading_with_attempts(_artifact(), provider(), model="fake-reader",
                                         facts_only=True)
    assert len(calls) == 1 and "--output-schema" in calls[0]


def test_real_extra_closing_pattern_is_rejected_before_cache(monkeypatch, tmp_path: Path) -> None:
    calls = fake_execution(monkeypatch, fixture() + "]}")
    cached = CachedLLMProvider(provider(), cache_dir=tmp_path, task_name="deep_reading")
    with pytest.raises(AnalysisError, match="JSON"):
        model_paper_reading_with_attempts(_artifact(), cached, model="fake-reader", facts_only=True)
    assert len(calls) == 1
    assert not list(tmp_path.rglob("*.json"))


def test_real_observation_string_pattern_stops_without_repair(monkeypatch) -> None:
    from test_experimental_results_contract import fixture as experiment_fixture

    artifact, body = experiment_fixture()
    body["deep_readings"]["experimental_results"][0]["observations"] = ["Method: 0.99"]
    calls = fake_execution(monkeypatch, json.dumps(body))
    with pytest.raises(AnalysisError, match="subject/value"):
        model_paper_reading_with_attempts(artifact, provider(), model="fake-reader",
                                         facts_only=True)
    assert len(calls) == 1
    with pytest.raises(AnalysisError, match="subject/value"):
        parse_paper_reading(json.dumps(body), artifact)


@pytest.mark.parametrize("facts_only", [False, True])
def test_full_root_example_shows_typed_observations_and_matches_explanation_mode(
    facts_only: bool,
) -> None:
    example = json.loads(_reading_response_example(facts_only=facts_only))
    reading = example["deep_readings"][0]
    observations = reading["experimental_results"][0]["observations"]
    assert observations and set(observations[0]) == {"subject", "value"}
    assert all(isinstance(value, str) for value in observations[0].values())
    assert bool(reading["reader_explanation"]) != facts_only
