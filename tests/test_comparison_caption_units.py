"""Only losslessly bundled source anchors can stop being separate evidence choices."""

import copy
import json

import pytest
from test_table_comparison_review import DATA, approval

from research_radar.analysis.experimental_results import experimental_assertion_identity
from research_radar.analysis.review_targets import build_review_targets
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, dataclass_to_dict


def caption_contract(*, defect: str = "", extra: bool = False):
    case = copy.deepcopy(DATA["cases"][0])
    row = case["claim"]
    # Reproduce the duplication pattern with a synthetic caption and original table cells.
    caption = {"source_url": DATA["source_url"], "quote": "Table 3 compares FCP and MemGuide.",
               "location": "page 6; Table 3 caption", "source_title": "MemGuide", "confidence": 1}
    case["proposal"]["evidence"].append(copy.deepcopy(caption))
    offered = {**caption, "confidence": 0.7}
    if defect == "quote":
        offered["quote"] += " Independent evaluation condition."
    elif defect == "location":
        offered["location"] = "page 7; separate paragraph"
    elif defect == "source":
        offered["source_url"] = "https://other.test/paper"
    elif defect == "not_source_evidence":
        case["proposal"]["evidence"].pop()
        case["proposal"]["conditions"].append(caption["quote"])
    elif defect == "incomplete":
        cells = case["binding"]["source_evidence"]["cells"]
        cells.remove(next(cell for cell in cells if cell["column_headers"] == ["JGA"]))
    row["evidence"].append(offered)
    if extra:
        row["evidence"].append({**caption, "quote": "Scores are measured on held-out sessions."})
    claim = Claim(row["text"], ClaimStatus(row["status"]), [EvidenceAnchor(**e)
        for e in row["evidence"]], row["rationale"], row["metadata"])
    for binding in case["binding"]["assertions"]:
        if binding["claim_id"] == "c33":
            binding["assertion_sha256"] = experimental_assertion_identity(claim)
    context = {"experimental_result_proposals": [{"source_url": DATA["source_url"],
        "results": [case["proposal"]], "bindings": [case["binding"]]}]}
    return claim, build_review_targets([claim], json.dumps(context))


def test_caption_already_in_the_complete_unit_is_confirmed_once_without_losing_source() -> None:
    claim, targets = caption_contract()
    target, = targets.targets.values()
    ordinary = set(target["direct_evidence"]) - set(target["comparison_units"])
    assert not ordinary
    unit = target["direct_evidence"][target["comparison_units"][0]]
    assert unit["complete"]
    assert {**dataclass_to_dict(claim.evidence[-1]), "confidence": 1} in unit[
        "proposal"]["evidence"]
    reply = approval(targets)
    decision, = reply["decisions"].values()
    assert decision["evidence_refs"] == []
    assert targets.normalize(json.dumps(reply))


@pytest.mark.parametrize("defect", ["quote", "location", "source", "not_source_evidence",
                                    "incomplete"])
def test_nonidentical_unbundled_or_incomplete_context_keeps_its_own_choice(defect: str) -> None:
    _, targets = caption_contract(defect=defect)
    target, = targets.targets.values()
    assert set(target["direct_evidence"]) - set(target.get("comparison_units", []))
    reply = approval(targets)
    decision, = reply["decisions"].values()
    decision["evidence_refs"] = []
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(reply))


def test_a_comparison_confirmation_never_covers_additional_independent_text() -> None:
    _, targets = caption_contract(extra=True)
    target, = targets.targets.values()
    ordinary = set(target["direct_evidence"]) - set(target["comparison_units"])
    assert len(ordinary) == 1
    proof = target["direct_evidence"][next(iter(ordinary))]
    assert proof["quote"] == "Scores are measured on held-out sessions."
    reply = approval(targets)
    assert targets.normalize(json.dumps(reply))
    next(iter(reply["decisions"].values()))["evidence_refs"] = []
    with pytest.raises(AnalysisError, match="without_evidence"):
        targets.normalize(json.dumps(reply))


@pytest.mark.parametrize("checked", [False, "true", None])
def test_bundling_does_not_waive_explicit_valid_comparison_confirmation(checked: object) -> None:
    _, targets = caption_contract()
    reply = approval(targets)
    checks = next(iter(reply["decisions"].values()))["comparison_checks"]
    checks[next(iter(checks))] = checked
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(reply))
