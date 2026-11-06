"""Complete extracted text is delivered intact, or rejected before a model call."""

import json
import re
import shlex
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from research_radar.analysis.cli_providers import CodexCliProvider, messages_to_prompt
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import (
    model_paper_reading_with_attempts,
    paper_reading_prompt,
)
from research_radar.analysis.paper_sections import build_reading_packet
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import (
    ReaderContextBudget,
    ReaderInputError,
    check_reader_input,
)
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError, ConfigError
from research_radar.models import Artifact, SourceCandidate, SourceType


def artifact(text: str) -> Artifact:
    return Artifact(
        source=SourceCandidate(
            title="A complete study",
            url="https://example.test/a",
            source_type=SourceType.PAPER,
            source_name="offline",
        ),
        text=text,
    )


def test_full_input_includes_references_appendix_and_all_whitespace() -> None:
    text = (
        "preface\n[page 1]\nAbstract\n"
        + "A measured observation. " * 2000
        + "\n[page 2]\nReferences\nA cited work.\n\nAppendix A\nFinal condition.  \n"
    )
    packet = build_reading_packet(artifact(text))
    prompt = paper_reading_prompt(artifact(text), packet=packet)
    assert text in re.sub(r"\nsource_id=b[0-9a-f]{16}:\d+\n", "", prompt)
    assert "bounded excerpts" not in prompt
    assert all(row["status"] == "complete" for row in packet.coverage)


def test_reader_projects_literal_tables_without_changing_full_text_or_local_geometry() -> None:
    text = "[page 1]\nTable 3: Results.\nMemOS 0.5539\nAppendix: unchanged.\n"
    table = {"table_id": "table-3", "physical_page": 1, "complete_grid": True,
             "caption": "Table 3: Results.", "box": [0, 1, 2, 3],
             "cells": [{"cell_id": "cell-1", "row_headers": ["MemOS"],
                        "column_headers": ["Average", "AA"], "value": "0.5539",
                        "box": [0, 1, 2, 3],
                        "row_header_boxes": [{"text": "MemOS", "box": [0, 1, 2, 3]}],
                        "column_header_boxes": [{"text": "AA", "box": [0, 1, 2, 3]}]}]}
    source = replace(artifact(text), metadata={"table_evidence": [table]})
    original = deepcopy(source.metadata)
    prompt = paper_reading_prompt(source)
    raw = prompt.split("POSITIONED TABLE SOURCES (literal cells, not approved findings):\n")[1]
    projected, _ = json.JSONDecoder().raw_decode(raw)
    assert projected == [{"table_id": "table-3", "physical_page": 1, "complete_grid": True,
                          "caption": "Table 3: Results.",
                          "cells": [{"cell_id": "cell-1", "row_headers": ["MemOS"],
                                     "column_headers": ["Average", "AA"], "value": "0.5539"}]}]
    assert text in re.sub(r"\nsource_id=b[0-9a-f]{16}:\d+\n", "", prompt)
    assert source.metadata == original


def test_codex_large_unicode_input_uses_stdin_not_command_arguments(tmp_path: Path) -> None:
    script = tmp_path / "offline codex.py"
    script.write_text(
        "import sys,json\nfrom pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "assert args[-1]=='-'\n"
        "output=Path(args[args.index('--output-last-message')+1])\n"
        "output.write_text(json.dumps({'input':sys.stdin.read(),'args':args}))\n",
        encoding="utf-8",
    )
    provider = CodexCliProvider(
        name="offline",
        command=f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}",
    )
    messages = [Message(role="user", content="完整正文 Ω\n" * 100_000)]
    result = json.loads(provider.complete(messages, model="offline").content)
    assert result["input"] == messages_to_prompt(messages)
    assert max(map(len, result["args"])) < 1024


class RecordingReader:
    name = "offline-reader"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(content="not JSON", model=model)


def test_unknown_model_capacity_stops_before_any_request() -> None:
    provider = RecordingReader()
    with pytest.raises(AnalysisError, match="reader_context_unknown"):
        model_paper_reading_with_attempts(artifact("A complete source."), provider, model="unknown")
    assert provider.calls == []


@pytest.mark.parametrize("bad", [True, 0, -1, "1000"])
def test_context_capacity_configuration_requires_positive_integers(bad: object) -> None:
    with pytest.raises(ConfigError):
        parse_config(
            {
                "topics": [{"id": "memory", "queries": ["memory"]}],
                "model_providers": {
                    "offline": {
                        "kind": "codex_cli",
                        "command": "offline",
                        "reader_contexts": {
                            "reader": {
                                "context_window_tokens": bad,
                                "output_reserve_tokens": 1000,
                                "overhead_reserve_tokens": 1000,
                            }
                        },
                    }
                },
            }
        )


def configure(provider: RecordingReader, window: int = 1_000_000) -> RecordingReader:
    provider.reader_contexts = {"reader": ReaderContextBudget(window, 1000, 1000)}
    return provider


def test_capacity_includes_instructions_unicode_output_and_overhead() -> None:
    messages = [Message("system", "Instruction" * 50), Message("user", "论文 Ω" * 30)]
    provider = configure(RecordingReader(), window=2100)
    with pytest.raises(ReaderInputError, match="reader_context_exceeded") as failure:
        check_reader_input(messages, provider, model="reader")
    audit = failure.value.audit
    assert audit["input_utf8_bytes"] > sum(len(m.content) for m in messages)
    assert audit["planned_total_tokens"] == audit["input_utf8_bytes"] + 2000
    assert provider.calls == []


def test_changing_model_does_not_reuse_another_models_capacity() -> None:
    provider = configure(RecordingReader())
    with pytest.raises(ReaderInputError, match="reader_context_unknown"):
        check_reader_input([Message("user", "source")], provider, model="other")


def test_repair_request_is_rechecked_instead_of_getting_fresh_capacity() -> None:
    source = artifact("Complete source.")
    provider = configure(RecordingReader())
    # One failed parse reveals the exact first request without making real calls.
    with pytest.raises(AnalysisError, match="after 2 attempts"):
        model_paper_reading_with_attempts(source, provider, model="reader")
    audit = check_reader_input(provider.calls[0], provider, model="reader")
    first_size = audit["planned_total_tokens"]
    provider.calls.clear()
    configure(provider, window=first_size)
    with pytest.raises(ReaderInputError, match="reader_context_exceeded") as failure:
        model_paper_reading_with_attempts(source, provider, model="reader")
    assert len(provider.calls) == 1
    assert len(failure.value.reader_attempts) == 1
    assert failure.value.reader_attempts[0]["status"] == "failed"
    assert failure.value.audit["attempt_index"] == 2


def test_guard_runs_before_cache_and_rejected_content_is_not_reused(tmp_path: Path) -> None:
    provider = configure(RecordingReader())
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="deep_reading")
    source = artifact("Full source." * 3000)
    # Each explicit run retains its existing two-format-attempt cap, without caching failures.
    for _ in range(2):
        with pytest.raises(AnalysisError, match="after 2 attempts"):
            model_paper_reading_with_attempts(source, cached, model="reader")
    assert len(provider.calls) == 4
    assert cached.hit_count == 0
    assert not list(cached.cache_dir.glob("*.json"))
    cached.reader_contexts = {}
    with pytest.raises(ReaderInputError, match="reader_context_unknown"):
        model_paper_reading_with_attempts(source, cached, model="reader")
    assert cached.hit_count == 0
    assert len(provider.calls) == 4
    assert source.text in re.sub(r"\nsource_id=b[0-9a-f]{16}:\d+\n", "",
                                 provider.calls[0][1].content)


def test_mismatched_packet_stops_without_model_or_repair() -> None:
    provider = configure(RecordingReader())
    with pytest.raises(ReaderInputError, match="reader_input_incomplete"):
        model_paper_reading_with_attempts(
            artifact("Actual text"),
            provider,
            model="reader",
            packet=build_reading_packet(artifact("Other text")),
        )
    assert not provider.calls


def test_explicit_output_limit_must_fit_reserve() -> None:
    provider = configure(RecordingReader())
    provider.max_tokens = 2000
    with pytest.raises(ReaderInputError, match="reader_output_reserve_insufficient"):
        check_reader_input([Message("user", "source")], provider, model="reader")


def test_capacity_configuration_reaches_cache_without_guessing_other_models(tmp_path: Path) -> None:
    from research_radar.analysis.routing import build_provider
    from research_radar.security.secrets import InMemorySecretBackend, SecretManager

    config = parse_config({
        "topics": [{"id": "memory", "queries": ["memory"]}],
        "model_providers": {"offline": {"kind": "local", "reader_contexts": {
            "reader": {"context_window_tokens": 100_000, "output_reserve_tokens": 4096,
                       "overhead_reserve_tokens": 2048},
        }}},
    })
    provider = build_provider(config, SecretManager(InMemorySecretBackend()), "offline")
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="deep_reading")
    assert check_reader_input([Message("user", "source")], cached, model="reader")[
        "status"
    ] == "fits_estimate"
    with pytest.raises(ReaderInputError, match="unknown"):
        check_reader_input([Message("user", "source")], cached, model="another-model")


@pytest.mark.parametrize("mode", ["daily", "paper"])
@pytest.mark.parametrize("block_repair", [False, True])
def test_budget_failure_is_persisted_and_does_not_finish_an_empty_report(
    mode: str, block_repair: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_pipeline_fake import DEEP_READING_FIXTURE_TEXT, FakeConnector

    from research_radar.pipeline import daily, paper

    class StopRepairReader(RecordingReader):
        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            audit = check_reader_input(messages, self, model=model)
            # Pin the fixture to exactly the first request's size, rejecting added repair text.
            self.reader_contexts[model] = ReaderContextBudget(
                audit["planned_total_tokens"], 1000, 1000,
            )
            return super().complete(messages, model=model)

    provider = configure(StopRepairReader()) if block_repair else RecordingReader()
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    module = daily if mode == "daily" else paper
    monkeypatch.setattr(module, "ingest_source", lambda source, _: Artifact(
        source=source, text=DEEP_READING_FIXTURE_TEXT,
    ))
    expected_code = "reader_context_exceeded" if block_repair else "reader_context_unknown"
    with pytest.raises(ReaderInputError, match=expected_code):
        if mode == "daily":
            daily.run_daily(tmp_path, config, "memory", [FakeConnector()], deep_reader=provider,
                            deep_model="reader", deep_limit=2, verifier=provider)
        else:
            paper.run_paper(tmp_path, config, "memory", "https://example.test/paper",
                            provider, model="reader", verifier=provider)
    expected_calls = 1 if block_repair else 0
    assert len(provider.calls) == expected_calls
    inputs = next(tmp_path.rglob("paper_reading_inputs.jsonl"))
    record = json.loads(inputs.read_text().splitlines()[-1])
    assert record["source_text"] == DEEP_READING_FIXTURE_TEXT
    assert record["input_budget"]["code"] == expected_code
    attempts = next(tmp_path.rglob("reader_attempts.jsonl"))
    saved_attempts = [json.loads(line) for line in attempts.read_text().splitlines()]
    assert len(saved_attempts) == expected_calls
    if block_repair:
        assert saved_attempts[0]["attempt_index"] == 1
        assert saved_attempts[0]["status"] == "failed"
    assert not list(tmp_path.rglob("article_draft.json"))
    assert next(tmp_path.rglob("run_error.json")).is_file()


def test_over_budget_never_calls_provider_or_populates_cache(tmp_path: Path) -> None:
    provider = configure(RecordingReader(), window=3000)
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="deep_reading")
    with pytest.raises(ReaderInputError, match="exceeded"):
        model_paper_reading_with_attempts(artifact("Source " * 1000), cached, model="reader")
    assert not provider.calls
    assert cached.hit_count == cached.miss_count == 0
    assert not list(tmp_path.rglob("*.json"))


def test_anthropic_effective_output_limit_cannot_exceed_reserve(tmp_path: Path) -> None:
    from research_radar.analysis.anthropic import AnthropicMessagesProvider
    from research_radar.security.secrets import InMemorySecretBackend, SecretManager

    provider = AnthropicMessagesProvider(name="offline", api_key_secret="offline.key",
                                         secrets=SecretManager(InMemorySecretBackend()))
    provider.reader_contexts = {"reader": ReaderContextBudget(100_000, 1, 1024)}
    for instance in (provider, CachedLLMProvider(provider, cache_dir=tmp_path, task_name="reader")):
        with pytest.raises(ReaderInputError, match="reader_output_reserve_insufficient"):
            check_reader_input([Message("user", "source")], instance, model="reader")
