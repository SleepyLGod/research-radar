"""Experimental observations retain conditions and explicit source uncertainty."""

import hashlib
import json
from pathlib import Path

import pytest
from test_paper_reading import _claim_units_fixture

from research_radar.analysis.paper_reading import (
    paper_reading_prompt,
    parse_paper_reading,
    reading_to_dict,
)
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, SourceCandidate, SourceType

URL = "https://example.com/paper"
QUOTE = "The final task success rate after clarification is 0.99."


def fixture() -> tuple[Artifact, dict]:
    artifact = Artifact(SourceCandidate("Paper", URL, SourceType.PAPER, "fixture"), QUOTE)
    payload = json.loads(_claim_units_fixture([QUOTE]))
    for key in ("area_context", "problem_solution", "related_work", "limitations",
                "critical_assessment"):
        payload["deep_readings"][key]["evidence"] = [{"quote": QUOTE}]
    payload["deep_readings"]["claim_units"][0]["evidence"] = [{"quote": QUOTE}]
    payload["deep_readings"]["claim_units"][0]["claim_id"] = "c1"
    payload["deep_readings"]["experimental_results"] = [{
        "result_id": "r1", "question": "Does clarification finish the task?",
        "conditions": ["Synthetic multi-session tasks", "After clarification"],
        "metric": "Task Rate (Post)",
        "observations": [{"subject": "GPT4o-mini", "value": "0.99"}],
        "comparison_scope": ["GPT4o-mini after clarification"],
        "uncertainty": [], "supporting_claim_ids": ["c1"],
        "evidence": [{"quote": QUOTE, "location": "Table 10"}],
        "source_kind": "table", "source_label": "Table 10", "physical_page": 12,
        "binding_status": "text_bound",
    }]
    return artifact, payload


def test_result_round_trip_keeps_outcome_stage_and_source_context() -> None:
    artifact, payload = fixture()
    reading = parse_paper_reading(json.dumps(payload), artifact)
    result = reading.experimental_results[0]
    assert result.metric == "Task Rate (Post)"
    assert result.conditions[-1] == "After clarification"
    saved = reading_to_dict(reading)["experimental_results"][0]
    assert saved["physical_page"] == 12
    context, _ = build_reading_review_context([reading], [], [artifact])
    assert json.loads(context)["experimental_result_proposals"][0]["results"] == [saved]


@pytest.mark.parametrize("change", ["id", "duplicate", "page", "quote", "observation",
                                  "condition", "status"])
def test_result_contract_cannot_guess_missing_bindings(change: str) -> None:
    artifact, payload = fixture()
    results = payload["deep_readings"]["experimental_results"]
    result = results[0]
    if change == "id":
        result["supporting_claim_ids"] = ["invented"]
    elif change == "duplicate":
        results.append(dict(result))
    elif change == "page":
        result["physical_page"] = True
    elif change == "quote":
        result["evidence"][0]["quote"] = "The final rate is 100%."
    elif change == "observation":
        result["observations"][0]["value"] = {"made_up": 100}
    elif change == "condition":
        result["conditions"] = "After clarification"
    else:
        result["binding_status"] = "approved"
    with pytest.raises(AnalysisError):
        parse_paper_reading(json.dumps(payload), artifact)


def test_figure_proposal_is_not_passed_off_as_verified_visual_evidence() -> None:
    artifact, payload = fixture()
    result = payload["deep_readings"]["experimental_results"][0]
    result.update(source_kind="figure", source_label="Figure 4", binding_status="unresolved")
    reading = parse_paper_reading(json.dumps(payload), artifact)
    context, _ = build_reading_review_context([reading], [], [artifact])
    parsed = json.loads(context)
    assert parsed["experimental_result_proposals"][0]["visual_input"] == "not_supplied"
    assert (parsed["experimental_result_proposals"][0]["results"][0]["binding_status"]
            == "unresolved")


def test_reader_prompt_and_strict_schema_share_result_fields() -> None:
    artifact, payload = fixture()
    prompt = paper_reading_prompt(artifact, facts_only=True)
    assert "experimental_results" in prompt
    assert "Do not infer a ranking" in prompt
    schema = paper_reading_response_schema()
    properties = schema["properties"]["deep_readings"]["items"]["properties"]
    fields = properties["experimental_results"]["items"]["properties"]
    assert set(fields) == set(payload["deep_readings"]["experimental_results"][0])


def test_legacy_reading_without_experiments_is_not_invented() -> None:
    artifact, payload = fixture()
    payload["deep_readings"].pop("experimental_results")
    assert parse_paper_reading(json.dumps(payload), artifact).experimental_results == []


def test_result_quote_is_matched_inside_full_text_not_only_equal_fixture() -> None:
    from dataclasses import replace

    artifact, payload = fixture()
    artifact = replace(artifact, text="Earlier methods and setup.\n" + QUOTE + "\nLimitations.")
    assert len(parse_paper_reading(json.dumps(payload), artifact).experimental_results) == 1


def test_original_document_fingerprint_is_not_a_claim_of_visual_access(tmp_path: Path) -> None:
    artifact, payload = fixture()
    path = tmp_path / "original.pdf"
    path.write_bytes(b"%PDF-offline-original-fixture")
    from dataclasses import replace

    artifact = replace(artifact, artifact_path=str(path), content_type="application/pdf")
    reading = parse_paper_reading(json.dumps(payload), artifact)
    context, _ = build_reading_review_context([reading], [], [artifact])
    record = json.loads(context)["full_sources"][0]["original_document"]
    assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record["visual_input"] == "not_supplied"
    assert str(path) not in context
