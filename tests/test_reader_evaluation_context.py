"""Evaluation conditions stay source-bound proposals, never public claims by themselves."""

import json

import pytest
from test_paper_reading import _artifact, _claim_units_fixture

from research_radar.analysis.paper_reading import (
    EvaluationContext,
    ReaderContextError,
    parse_paper_reading,
    validate_paper_reading,
)
from research_radar.analysis.source_references import build_source_index
from research_radar.exceptions import AnalysisError


def test_old_reading_has_unknown_not_invented_evaluation_context() -> None:
    reading = parse_paper_reading(_claim_units_fixture(["Memory benchmark fixture."]), _artifact())
    assert reading.evaluation_context == EvaluationContext()


def test_conditions_keep_literal_quotes_without_creating_public_claims() -> None:
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    payload["deep_readings"]["evaluation_context"] = {
        key: [{"text": "A proposed experimental condition.", "evidence": [{
            "quote": "Memory benchmark fixture.", "location": "Table 1",
        }]}] for key in ("data_construction", "available_inputs", "outcome_measurement")
    }
    reading = parse_paper_reading(json.dumps(payload), _artifact())
    claims, _ = validate_paper_reading(reading, _artifact())
    condition = reading.evaluation_context.data_construction[0]
    assert condition.evidence[0].quote == "Memory benchmark fixture."
    assert all("proposed experimental condition" not in claim.text for claim in claims)


@pytest.mark.parametrize("context", [
    "failed sessions excluded", [], {"other": []}, {"data_construction": "excluded"},
    {"available_inputs": [{"text": "condition"}]},
    {"outcome_measurement": [{"text": "condition", "evidence": []}]},
    {"data_construction": [{"text": 123, "evidence": [{"quote": "a"}]}]},
])
def test_context_shape_errors_do_not_get_coerced_or_silently_ignored(context: object) -> None:
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    payload["deep_readings"]["evaluation_context"] = context
    with pytest.raises(AnalysisError):
        parse_paper_reading(json.dumps(payload), _artifact())


def _referenced_context_payload(dimension: str) -> dict:
    """Create a synthetic source-selection response, not the lost LOTUS answer."""
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    body = payload["deep_readings"]
    evidence = [{"source_id": build_source_index(_artifact()).source_ids[0]}]
    for section in ("area_context", "problem_solution", "related_work", "limitations",
                    "critical_assessment"):
        body[section]["evidence"] = evidence
    body["claim_units"][0].update(claim_id="c7", evidence=evidence)
    body["method_flow"] = {"operations": [], "links": [], "gaps": []}
    body["reader_explanation"] = {}
    body["evaluation_context"] = {key: [] for key in (
        "data_construction", "available_inputs", "outcome_measurement")}
    body["evaluation_context"][dimension] = ["c7"]
    return payload


@pytest.mark.parametrize("dimension", [
    "data_construction", "available_inputs", "outcome_measurement",
])
def test_fresh_context_keeps_exact_fact_identity_and_source_block(dimension: str) -> None:
    payload = _referenced_context_payload(dimension)
    original = json.dumps(payload)

    reading = parse_paper_reading(original, _artifact(), require_source_references=True)

    assert reading.evaluation_context.claim_references[dimension] == ["c7"]
    assert reading.claim_units[0].claim_kind == "fact"
    assert reading.claim_units[0].evidence[0].quote == _artifact().text.strip()
    assert json.dumps(payload) == original


@pytest.mark.parametrize("dimension", ["available_inputs", "outcome_measurement"])
@pytest.mark.parametrize("kind,has_evidence", [("interpretation", True), ("fact", False)])
def test_context_failure_identifies_target_kind_and_evidence_without_repair(
    dimension: str, kind: str, has_evidence: bool,
) -> None:
    payload = _referenced_context_payload(dimension)
    unit = payload["deep_readings"]["claim_units"][0]
    unit["claim_kind"] = kind
    if not has_evidence:
        unit["evidence"] = []
    original = json.dumps(payload)

    with pytest.raises(ReaderContextError) as failed:
        parse_paper_reading(original, _artifact(), require_source_references=True)

    diagnostic = str(failed.value)
    assert f"evaluation_context.{dimension}[0]" in diagnostic
    assert "c7" in diagnostic
    assert f"claim_kind={kind!r}" in diagnostic
    assert f"evidence_count={int(has_evidence)}" in diagnostic
    assert json.dumps(payload) == original


def test_context_failure_redacts_and_bounds_untrusted_identity_and_kind() -> None:
    payload = _referenced_context_payload("available_inputs")
    identity = "sk-fake-secret-value-12345678901234567890"
    body = payload["deep_readings"]
    body["claim_units"][0].update(claim_id=identity, claim_kind="interpretation" * 100)
    body["evaluation_context"]["available_inputs"] = [identity]

    with pytest.raises(ReaderContextError) as failed:
        parse_paper_reading(json.dumps(payload), _artifact(), require_source_references=True)

    diagnostic = str(failed.value)
    assert "evaluation_context.available_inputs[0]" in diagnostic
    assert "claim_id=" in diagnostic
    assert identity not in diagnostic
    assert len(diagnostic) < 400
