"""Reader envelope regressions minimized from a saved malformed model response."""

import json
from pathlib import Path

import pytest
from test_paper_reading import SequenceProvider, _artifact, _claim_units_fixture
from test_pipeline_fake import DEEP_READING_FIXTURE_TEXT, FakeConnector

from research_radar.analysis.openai_stream import parse_chat_stream
from research_radar.analysis.paper_reading import (
    paper_reading_prompt,
    parse_paper_reading,
    validate_paper_reading,
)
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact
from research_radar.pipeline import daily
from research_radar.storage.files import read_json, read_jsonl


@pytest.mark.parametrize("language", ["en", "zh"])
def test_actual_prompt_example_is_a_complete_parseable_reader_response(language: str) -> None:
    prompt = paper_reading_prompt(_artifact(), language=language)
    marker = "Complete JSON response example (replace all placeholders):\n"
    example, _ = json.JSONDecoder().raw_decode(prompt, prompt.index(marker) + len(marker))

    assert set(example) == {"deep_readings", "unsupported_or_rejected_claims"}
    assert isinstance(example["deep_readings"], list)
    assert len(example["deep_readings"]) == 1
    # The example uses an offered ID; another source's ID still cannot pass.
    invalid = json.loads(json.dumps(example))
    invalid['deep_readings'][0]['experimental_results'][0]['evidence'] = [
        {'source_id':'b0000000000000000:1'}]
    with pytest.raises(AnalysisError, match="source reference"):
        parse_paper_reading(json.dumps(invalid), _artifact())
    reading = parse_paper_reading(json.dumps(example), _artifact())
    assert [unit.claim_id for unit in reading.claim_units] == ["c1", "c2", "c3"]
    assert reading.evaluation_context.claim_references == {
        "data_construction": [], "available_inputs": [], "outcome_measurement": ["c3"],
    }
    assert reading.claim_units[0].claim_id == "c1"
    assert reading.reader_explanation.solution_walkthrough[0].supporting_claim_ids == ["c1"]
    claims, _ = validate_paper_reading(reading, _artifact())
    assert all("model_review" not in claim.metadata for claim in claims)
    assert reading.method_flow.review is None  # Valid structure is not semantic approval.


def test_missing_item_object_close_is_rejected_without_repair_or_partial_extraction() -> None:
    # The live response closed reader_explanation, then the array before its item object.
    # Keep that failure shape but replace paper text with existing offline fixture text.
    path = Path(__file__).parent / "fixtures/reader_missing_object_close.txt"
    raw = path.read_text(encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as syntax:
        json.loads(raw)
    assert raw[syntax.value.pos] == "]"
    with pytest.raises(AnalysisError, match="not valid JSON"):
        parse_paper_reading(raw, _artifact())
    assert path.read_text(encoding="utf-8") == raw


def test_fragmented_explanation_objects_are_rejected_without_reassembly() -> None:
    # Preserve the latest answer's field-object fragments, not its paper text.
    path = Path(__file__).parent / "fixtures/reader_fragmented_explanation.txt"
    raw = path.read_text(encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as syntax:
        json.loads(raw)
    assert raw[syntax.value.pos:].startswith('{"core_thesis":')
    with pytest.raises(AnalysisError, match="not valid JSON"):
        parse_paper_reading(raw, _artifact())
    assert path.read_text(encoding="utf-8") == raw


def test_same_explanation_fields_in_one_object_are_readable() -> None:
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    payload["deep_readings"]["reader_explanation"] = {
        "opening_context": [{"text": "Offline background note.", "supporting_claim_ids": ["c1"]}],
        "core_thesis": [{"text": "Offline thesis note.", "supporting_claim_ids": ["c1"]}],
    }

    reading = parse_paper_reading(json.dumps(payload), _artifact())

    assert reading.reader_explanation.opening_context[0].text == "Offline background note."
    assert reading.reader_explanation.core_thesis[0].text == "Offline thesis note."


@pytest.mark.parametrize(
    "fixture_name", ["reader_missing_object_close.txt", "reader_fragmented_explanation.txt"],
)
@pytest.mark.parametrize("chunk_size", [1, 17, 4096])
def test_shared_streaming_preserves_invalid_answer_for_reader_rejection(
    fixture_name: str, chunk_size: int,
) -> None:
    raw = (Path(__file__).parent / "fixtures" / fixture_name).read_text(encoding="utf-8")
    events = [
        {"choices": [{"index": 0, "delta": {"content": raw[i:i + 90]}}]}
        for i in range(0, len(raw), 90)
    ]
    events.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    wire = ("".join(f"data: {json.dumps(event)}\n\n" for event in events)
            + "data: [DONE]\n\n").encode("utf-8")

    response = parse_chat_stream(wire[i:i + chunk_size] for i in range(0, len(wire), chunk_size))

    assert response["choices"][0]["message"]["content"] == raw
    with pytest.raises(AnalysisError, match="not valid JSON"):
        parse_paper_reading(response["choices"][0]["message"]["content"], _artifact())


def test_canonical_single_item_array_preserves_outer_rejected_audit() -> None:
    body = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))["deep_readings"]
    payload = {"deep_readings": [body], "unsupported_or_rejected_claims": ["Not established."]}

    reading = parse_paper_reading(json.dumps(payload), _artifact())
    claims, _ = validate_paper_reading(reading, _artifact())

    assert reading.unsupported_or_rejected_claims == ["Not established."]
    assert [claim.text for claim in claims if claim.is_publishable()] == [
        "Experiment: Memory benchmark fixture."
    ]


@pytest.mark.parametrize("size", [0, 2])
def test_single_paper_request_rejects_empty_or_multiple_readings(size: int) -> None:
    body = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))["deep_readings"]

    with pytest.raises(AnalysisError):
        parse_paper_reading(json.dumps({"deep_readings": [body] * size}), _artifact())


@pytest.mark.parametrize("wrapper", ["plain", "fenced", "prose"])
def test_array_root_cannot_be_salvaged_as_its_first_object(wrapper: str) -> None:
    body = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    raw = json.dumps([body])
    if wrapper == "fenced":
        raw = f"```json\n{raw}\n```"
    elif wrapper == "prose":
        raw = f"Here is the response:\n{raw}"

    with pytest.raises(AnalysisError, match="must be an object"):
        parse_paper_reading(raw, _artifact())


@pytest.mark.parametrize("shape", ["object", "unwrapped", "array"])
def test_valid_existing_reader_envelopes_remain_readable(shape: str) -> None:
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    body = payload["deep_readings"]
    if shape == "unwrapped":
        payload = body
    elif shape == "array":
        payload["deep_readings"] = [body]

    reading = parse_paper_reading(json.dumps(payload), _artifact())

    assert reading.claim_units[0].text == "Memory benchmark fixture."


@pytest.mark.parametrize(
    "fixture_name", ["reader_missing_object_close.txt", "reader_fragmented_explanation.txt"],
)
def test_malformed_root_never_becomes_public_daily_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
) -> None:
    raw = (Path(__file__).parent / "fixtures" / fixture_name).read_text(encoding="utf-8")
    reader = SequenceProvider([raw, raw])
    verifier = SequenceProvider([])
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    monkeypatch.setattr(
        daily, "ingest_source", lambda source, _: Artifact(source=source,
                                                           text=DEEP_READING_FIXTURE_TEXT),
    )

    run = daily.run_daily(
        tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
        deep_limit=1, verifier=verifier, figure_extractor=lambda *_a, **_k: [],
    )

    draft = read_json(run / "article_draft.json")
    assert draft["claims"] == []
    assert draft["metadata"]["deep_read_count"] == 0
    assert draft["metadata"]["research_outcome"]["status"] == "incomplete"
    assert len(reader.messages) == 2  # The pre-existing schema retry is unchanged.
    assert verifier.messages == []
    assert any("not valid JSON" in str(finding) for finding in read_jsonl(
        run / "review_findings.jsonl",
    ))
