"""Evaluation conditions stay source-bound proposals, never public claims by themselves."""

import json

import pytest
from test_paper_reading import _artifact, _claim_units_fixture

from research_radar.analysis.paper_reading import (
    EvaluationContext,
    parse_paper_reading,
    validate_paper_reading,
)
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
