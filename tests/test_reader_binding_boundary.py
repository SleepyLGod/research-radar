"""Fresh Reader output must bind paragraphs before downstream paid stages."""

import json

import pytest
from test_paper_reading import SequenceProvider, _artifact, _claim_units_fixture

from research_radar.analysis.deep_reading import run_artifact_deep_reading
from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import (
    model_paper_reading_with_attempts,
    parse_paper_reading,
    validate_paper_reading,
)
from research_radar.exceptions import AnalysisError


def response(paragraph: object) -> str:
    """Retain the real answer's failure shape, not its private run metadata."""
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    body = payload["deep_readings"]
    body["claim_units"][0]["claim_id"] = "c1"
    body["reader_explanation"] = {"solution_walkthrough": [paragraph]}
    return json.dumps(payload)


@pytest.mark.parametrize("paragraph", [
    "The mechanism is explained here (c1).",
    {"text": "The mechanism is explained here (c1)."},
    {"text": "The mechanism is explained here (c1).", "supporting_claim_ids": []},
    {"text": "An explanation.", "supporting_claim_ids": ["unknown"]},
    {"text": "An explanation.", "supporting_claim_ids": ["c1", "c1"]},
    {"text": "An explanation.", "supporting_claim_ids": [1]},
])
def test_fresh_unbound_explanation_stops_after_one_reader_call(paragraph: object) -> None:
    reader = SequenceProvider([response(paragraph)])
    repair = SequenceProvider([])

    with pytest.raises(AnalysisError, match="explanation") as failure:
        run_artifact_deep_reading(
            _artifact(), reader, model="fake-reader",
            anchor_repair_provider=repair, anchor_repair_model="fake-repair",
        )

    assert len(reader.messages) == 1
    assert repair.messages == []
    assert [attempt["status"] for attempt in failure.value.reader_attempts] == ["failed"]


def test_explicit_binding_is_kept_but_does_not_approve_the_paragraph() -> None:
    raw = response({"text": "An unrelated interpretation.", "supporting_claim_ids": ["c1"]})
    reader = SequenceProvider([raw])

    result = model_paper_reading_with_attempts(_artifact(), reader, model="fake-reader")
    claims, _ = validate_paper_reading(result.reading, _artifact())
    public, _ = public_explanation(result.reading.reader_explanation, claims)

    assert result.reading.reader_explanation.solution_walkthrough[0].supporting_claim_ids == ["c1"]
    assert result.reading.reader_explanation.solution_walkthrough[0].review is None
    assert "An unrelated interpretation." not in repr(public)
    assert len(reader.messages) == 1


def test_legacy_string_paragraph_remains_readable_without_guessing_ids() -> None:
    raw = response("A saved old explanation (c1).")

    reading = parse_paper_reading(raw, _artifact())
    paragraph = reading.reader_explanation.solution_walkthrough[0]

    assert paragraph.text == "A saved old explanation (c1)."
    assert paragraph.supporting_claim_ids == []
    assert paragraph.review is None


def test_new_paragraph_cannot_bind_a_positional_id_invented_for_legacy_loading() -> None:
    payload = json.loads(response({"text": "A candidate.", "supporting_claim_ids": ["legacy-c1"]}))
    payload["deep_readings"]["claim_units"][0].pop("claim_id")
    raw = json.dumps(payload)
    reader = SequenceProvider([raw])

    assert parse_paper_reading(raw, _artifact()).claim_units[0].claim_id == "legacy-c1"
    with pytest.raises(AnalysisError, match="unknown support IDs"):
        model_paper_reading_with_attempts(_artifact(), reader, model="fake-reader")
    assert len(reader.messages) == 1


@pytest.mark.parametrize("missing", ["text", "section"])
def test_explicit_id_on_a_dropped_claim_unit_cannot_bind_new_prose(missing: str) -> None:
    payload = json.loads(response({"text": "A candidate.", "supporting_claim_ids": ["c1"]}))
    payload["deep_readings"]["claim_units"][0][missing] = ""
    reader = SequenceProvider([json.dumps(payload)])

    with pytest.raises(AnalysisError, match="unknown support IDs"):
        model_paper_reading_with_attempts(_artifact(), reader, model="fake-reader")
    assert len(reader.messages) == 1
