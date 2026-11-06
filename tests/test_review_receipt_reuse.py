"""Reuse exact prior approvals, never changed evidence or missing decisions."""

import copy
import json
from dataclasses import replace

import pytest
from test_review_evidence_selection import mixed_claim, selection_reply

from research_radar.analysis.review_targets import build_review_targets
from research_radar.exceptions import AnalysisError


def contracts():
    """Keep one target and change the other, without relying on its list position."""
    first = mixed_claim()
    other = replace(copy.deepcopy(first), text="Another exact source assertion.")
    other.metadata["paper_reading"]["claim_id"] = "c48"
    old = build_review_targets([first, other], "")
    changed = replace(other, text="A revised source assertion.")
    current = build_review_targets([changed, first], "")
    raw = json.dumps(selection_reply(old))
    return old, current, json.loads(old.normalize(raw))


def test_reuse_preserves_content_not_positions_and_keeps_both_original_receipts():
    old, current, receipt = contracts()
    original = copy.deepcopy(receipt)
    reused = current.reuse_supported(receipt)
    assert set(reused) == old.targets.keys() & current.targets.keys()
    pending = current.select(current.targets.keys() - reused.keys())
    fresh = json.loads(pending.normalize(json.dumps(selection_reply(pending))))
    combined = current.assemble(receipt, fresh)
    assert receipt == original
    assert len(combined["decisions"]) == 2
    assert [d["claim_index"] for d in combined["decisions"]] == [1, 2]
    provenance = combined["structured_review"]
    assert "raw_response" not in provenance
    assert provenance["kind"] == "assembled_receipts"
    assert provenance["receipts"] == [receipt, fresh]
    assert provenance["reused_target_ids"] == sorted(reused)
    assert set(provenance["selected_evidence"]) == current.targets.keys()


@pytest.mark.parametrize("status", ["needs_review", "unsupported", "speculative"])
def test_prior_nonapproval_is_never_reused(status):
    old, current, _ = contracts()
    response = selection_reply(old)
    for decision in response["decisions"].values():
        decision["status"] = status
    receipt = json.loads(old.normalize(json.dumps(response)))
    assert current.reuse_supported(receipt) == {}


@pytest.mark.parametrize("defect", ["text", "binding", "selected", "reason", "missing"])
def test_tampered_original_receipt_is_rejected(defect):
    _, current, receipt = contracts()
    structured = receipt["structured_review"]
    key = next(iter(structured["targets"]))
    if defect == "text":
        structured["targets"][key]["text"] += " changed"
    elif defect == "binding":
        mapping = structured["evidence_bindings"][key]
        mapping[next(iter(mapping))] = "not-the-original-proof"
    elif defect == "selected":
        structured["selected_evidence"][key] = []
    elif defect == "reason":
        receipt["decisions"][0]["reason"] = "A substituted reason."
    else:
        del structured["raw_response"]
    with pytest.raises(AnalysisError):
        current.reuse_supported(receipt)


@pytest.mark.parametrize("defect", ["missing", "old_target", "unoffered_evidence"])
def test_fresh_receipt_must_cover_exactly_the_pending_targets(defect):
    old, current, receipt = contracts()
    reused = current.reuse_supported(receipt)
    pending = current.select(current.targets.keys() - reused.keys())
    response = selection_reply(pending)
    key = next(iter(response["decisions"]))
    if defect == "missing":
        response["decisions"].clear()
    elif defect == "old_target":
        response["decisions"][next(k for k in old.targets if k not in current.targets)] = (
            response["decisions"].pop(key))
    else:
        response["decisions"][key]["evidence_refs"] = ["not-offered"]
    with pytest.raises(AnalysisError):
        current.assemble(receipt, json.loads(pending.normalize(json.dumps(response))))


def test_changed_source_or_cell_binding_requires_a_new_decision():
    claim = mixed_claim()
    old = build_review_targets([claim], "")
    receipt = json.loads(old.normalize(json.dumps(selection_reply(old))))
    changed = replace(claim, evidence=[replace(claim.evidence[0], source_url="https://other.test")])
    assert build_review_targets([changed], "").reuse_supported(receipt) == {}
    changed = copy.deepcopy(claim)
    positioned = changed.metadata["anchor_resolution"]["evidence_contexts"][0]["positioned"]
    positioned["table"]["cells"][0]["value"] = "0.99"
    assert build_review_targets([changed], "").reuse_supported(receipt) == {}


def test_shared_factual_path_only_requests_changed_targets_and_rebinds_current_positions():
    from test_publication_composition import candidates
    from test_review_targets import SchemaReviewer

    from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
    from research_radar.models import Artifact, SourceCandidate, SourceType

    reading, first = candidates()
    second = replace(copy.deepcopy(first), text="A second source-bound assertion.")
    second.metadata["paper_reading"]["claim_id"] = "c2"
    source = SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "offline")
    artifact = Artifact(source, first.evidence[0].quote)
    original = review_publication_facts([first, second], SchemaReviewer(), model="offline",
                                      readings=[reading], artifacts=[artifact])
    receipt = json.loads(original.raw_feedback)
    changed = replace(second, text="Changed second assertion.")
    provider = SchemaReviewer()
    result = review_publication_facts([changed, first], provider, model="offline",
        readings=[reading], artifacts=[artifact], previous_review=receipt)
    assert len(provider.requests) == 1
    offered = provider.requests[0][2]
    assert len(offered) == 1 and next(iter(offered.values()))["claim_id"] == "c2"
    assert all(fact_is_reviewed(c) for c in result.claims)
    assert json.loads(result.raw_feedback)["structured_review"]["kind"] == "assembled_receipts"


def test_prior_fact_receipt_cannot_skip_final_language_review():
    from test_publication_composition import candidates
    from test_review_targets import SchemaReviewer

    from research_radar.analysis.review import model_review_publishable_claims

    reading, claim = candidates()
    with pytest.raises(AnalysisError, match="reuse|Reuse"):
        model_review_publishable_claims([claim], SchemaReviewer(), model="offline",
            readings=[reading], analysis_claims=[claim], previous_review={})


def test_default_direct_review_still_calls_provider_for_an_empty_checklist():
    from test_review_targets import SchemaReviewer

    from research_radar.analysis.review import model_review

    provider = SchemaReviewer()
    model_review([], provider, model="offline")
    assert len(provider.requests) == 1
