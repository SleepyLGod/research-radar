"""Evidence choices preserve mixed sources without model-written duplicate identities."""

import copy
import json
from dataclasses import replace

import pytest

from research_radar.analysis.review_targets import (
    REVIEW_SCHEMA_ID,
    ReviewTargets,
    build_review_targets,
    validate_review_response,
)
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

URL = "https://example.test/paper"
PROSE = "We constructed 12 benchmark instances for the experiments."
ROW = "Method A 0.5"


def mixed_claim() -> Claim:
    """Mirror the real c47 case: sample count in text, point estimate in a table."""
    return Claim(
        "The experiments use 12 instances and report a point estimate of 0.5.",
        ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(URL, PROSE), EvidenceAnchor(URL, ROW)],
        metadata={"paper_reading": {"claim_id": "c47"}, "anchor_resolution": {
            "evidence_contexts": [{"source_url": URL, "quote": ROW, "positioned": {
                "selected_cell_ids": ["cell1"], "table": {
                    "table_id": "document-bound-table", "physical_page": 1,
                    "cells": [{"cell_id": "cell1", "row_headers": ["Method A"],
                               "column_headers": ["Score"], "value": "0.5"}],
                },
            }}],
        }},
    )


def selection_reply(contract: ReviewTargets, *, status: str = "supported") -> dict:
    """Explicit offline decisions; source selection itself never supplies approval."""
    return {"decisions": {key: {
        "status": status, "reason": "Explicit offline judgment, not a real model result.",
        "evidence_refs": list(target["direct_evidence"]),
    } for key, target in contract.targets.items()}}


def test_mixed_text_and_positioned_cells_remain_separately_selectable():
    contract = build_review_targets([mixed_claim()], "")
    target, = contract.targets.values()
    offered = list(target["direct_evidence"].values())
    assert len(offered) == 2
    assert next(v for v in offered if v.get("quote") == PROSE)["source_url"] == URL
    assert next(v for v in offered if "cell_id" in v)["value"] == "0.5"


def test_selectable_text_survives_into_paragraph_evidence():
    claim = mixed_claim()
    context = json.dumps({"paragraphs": [{"paragraph_id": "p1.limitations_discussion.1",
        "source_url": URL, "text": "评测只有12个实例，表中报告点估计。",
        "supporting_claim_ids": ["c47"]}]})
    contract = build_review_targets([claim], context)
    fact, paragraph = contract.targets.values()
    assert fact["direct_evidence"] == paragraph["direct_evidence"]
    assert any(v.get("quote") == PROSE for v in paragraph["direct_evidence"].values())


def test_short_citations_keep_server_owned_content_bound_identities():
    contract = build_review_targets([mixed_claim()], "")
    assert contract.schema["$id"] == REVIEW_SCHEMA_ID == "urn:research-radar:review-targets:v4"
    for key, target in contract.targets.items():
        offered = target["direct_evidence"]
        assert all(ref.startswith("e") and ref[1:].isdigit() for ref in offered)
        choice = contract.schema["properties"]["decisions"]["properties"][key][
            "properties"]["evidence_refs"]
        assert choice["type"] == "array"
        assert set(choice["items"]["enum"]) == set(offered)
        assert choice["maxItems"] == len(offered)
        bindings = contract.evidence_bindings[key]
        assert set(bindings) == set(offered)
        assert len(set(bindings.values())) == len(bindings)
        assert all(len(identity) == 65 for identity in bindings.values())


def test_selection_changes_neither_status_nor_reason_and_preserves_raw_bytes():
    contract = build_review_targets([mixed_claim()], "")
    reply = selection_reply(contract, status="needs_review")
    raw = json.dumps(reply, ensure_ascii=False, indent=2)
    normalized = json.loads(contract.normalize(raw))
    assert normalized["decisions"][0]["status"] == "needs_review"
    assert normalized["decisions"][0]["reason"] == next(iter(reply["decisions"].values()))["reason"]
    audit = normalized["structured_review"]
    assert audit["raw_response"] == raw
    assert audit["evidence_bindings"] == contract.evidence_bindings
    assert audit["selected_evidence"] == {
        key: list(bindings.values()) for key, bindings in contract.evidence_bindings.items()
    }


@pytest.mark.parametrize("bad", ["missing", "unknown", "nonstring", "wrong_type", "empty"])
def test_invalid_choices_cannot_authorize_a_target(bad):
    contract = build_review_targets([mixed_claim()], "")
    reply = selection_reply(contract)
    decision = next(iter(reply["decisions"].values()))
    if bad == "missing":
        decision.pop("evidence_refs")
    elif bad == "unknown":
        decision["evidence_refs"] = ["not-offered"]
    elif bad == "nonstring":
        decision["evidence_refs"] = [1]
    elif bad == "wrong_type":
        decision["evidence_refs"] = {}
    else:
        decision["evidence_refs"] = []
    with pytest.raises(AnalysisError):
        contract.normalize(json.dumps(reply))


def test_legacy_v3_duplicate_json_choice_keys_fail_instead_of_being_deduplicated():
    from test_review_citations import v3_schema

    contract = build_review_targets([mixed_claim()], "")
    key, target = next(iter(contract.targets.items()))
    ref, other = target["direct_evidence"]
    raw = ('{"decisions":{' + json.dumps(key) + ':{"status":"supported",'
           '"reason":"Offline control","evidence_selection":{'
           + json.dumps(ref) + ':true,' + json.dumps(ref) + ':true,'
           + json.dumps(other) + ':true}}}}')
    with pytest.raises(AnalysisError, match="duplicate"):
        validate_review_response(raw, v3_schema(contract))


def test_positioned_anchor_with_missing_cell_never_falls_back_to_plain_text():
    claim = mixed_claim()
    claim.metadata["anchor_resolution"]["evidence_contexts"][0]["positioned"][
        "selected_cell_ids"] = ["missing-cell"]
    with pytest.raises(AnalysisError, match="positioned"):
        build_review_targets([claim], "")


def test_reference_numbers_do_not_define_identity_or_change_with_claim_order():
    left = mixed_claim()
    right = replace(copy.deepcopy(left), text="Another assertion from the same paper.")
    right.metadata["paper_reading"]["claim_id"] = "c48"
    a = build_review_targets([left, right], "")
    b = build_review_targets([right, left], "")
    assert set(a.targets) == set(b.targets)
    assert a.evidence_bindings == b.evidence_bindings
    changed = copy.deepcopy(left)
    changed.evidence[0] = replace(changed.evidence[0], quote=PROSE + " Different scope.")
    assert set(build_review_targets([changed], "").targets) != set(
        build_review_targets([left], "").targets)


def test_legacy_v2_duplicate_ids_stay_invalid_and_cannot_approve_v3():
    legacy = ReviewTargets({"t-old": {"kind": "fact", "claim_index": 1,
        "direct_evidence": {"e-old": {"source_url": URL, "quote": PROSE}}}})
    assert legacy.schema["$id"] == "urn:research-radar:review-targets:v2"
    raw = json.dumps({"decisions": {"t-old": {"status": "supported", "reason": "Saved reply",
        "evidence_ids": ["e-old", "e-old"]}}})
    with pytest.raises(AnalysisError):
        validate_review_response(raw, legacy.schema)
    with pytest.raises(AnalysisError):
        build_review_targets([mixed_claim()], "").normalize(raw)


def test_original_cell_and_plain_text_requirements_are_both_preserved():
    claim = mixed_claim()
    original = copy.deepcopy(claim)
    contract = build_review_targets([claim], "")
    assert claim == original
    key, = contract.targets
    reply = selection_reply(contract, status="unsupported")
    normal = json.loads(contract.normalize(json.dumps(reply)))
    assert normal["decisions"][0]["status"] == "unsupported"
    assert set(normal["structured_review"]["selected_evidence"][key]) == set(
        contract.evidence_bindings[key].values())


def test_foreign_choices_do_not_become_valid_when_another_target_offers_them():
    left = mixed_claim()
    right = replace(copy.deepcopy(left), text="A different assertion.")
    right.metadata["paper_reading"]["claim_id"] = "c48"
    contract = build_review_targets([left, right], "")
    first, other = contract.targets
    reply = selection_reply(contract)
    reply["decisions"][first]["evidence_refs"] = list(contract.targets[other]["direct_evidence"])
    with pytest.raises(AnalysisError):
        contract.normalize(json.dumps(reply))


@pytest.mark.parametrize("selected", [[], ["cell1", "missing-cell"]])
def test_incomplete_positioned_selection_does_not_discard_missing_cells(selected):
    claim = mixed_claim()
    claim.metadata["anchor_resolution"]["evidence_contexts"][0]["positioned"][
        "selected_cell_ids"] = selected
    with pytest.raises(AnalysisError, match="positioned"):
        build_review_targets([claim], "")


def test_shared_review_preserves_mixed_sources_and_only_applies_explicit_decision():
    from test_review_targets import SchemaReviewer

    from research_radar.analysis.review import review_publication_facts
    from research_radar.models import Artifact, SourceCandidate, SourceType

    class Reviewing(SchemaReviewer):
        def complete_with_schema(self, messages, *, model, response_schema):
            answer = super().complete_with_schema(messages, model=model,
                                                  response_schema=response_schema)
            payload = json.loads(answer.content)
            for decision in payload["decisions"].values():
                decision["status"] = "needs_review"
            return replace(answer, content=json.dumps(payload))

    claim = mixed_claim()
    provider = Reviewing()
    result = review_publication_facts([claim], provider, model="offline", readings=[],
        artifacts=[Artifact(SourceCandidate("Paper", URL, SourceType.PAPER, "fixture"),
                            PROSE + "\n" + ROW)])
    offered, = provider.requests[0][2].values()
    assert any(p.get("quote") == PROSE for p in offered["direct_evidence"].values())
    assert any(p.get("cell_id") == "cell1" for p in offered["direct_evidence"].values())
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert not result.claims[0].is_publishable()
    assert len(provider.requests) == 1


def test_cache_rejects_empty_positive_citations_without_writing_an_entry(tmp_path):
    from test_review_targets import SchemaReviewer

    from research_radar.analysis.model_cache import CachedLLMProvider

    class InvalidSelection(SchemaReviewer):
        def complete_with_schema(self, messages, *, model, response_schema):
            answer = super().complete_with_schema(messages, model=model,
                                                  response_schema=response_schema)
            payload = json.loads(answer.content)
            decision = next(iter(payload["decisions"].values()))
            decision["evidence_refs"] = []
            return replace(answer, content=json.dumps(payload))

    contract = build_review_targets([mixed_claim()], "")
    provider = InvalidSelection()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="review")
    from research_radar.analysis.providers import Message

    with pytest.raises(AnalysisError):
        cached.complete_with_schema([Message("user", "REVIEW TARGETS (JSON):\n"
            + json.dumps(contract.targets))], model="offline", response_schema=contract.schema)
    assert not list(tmp_path.rglob("*.json"))
    assert len(provider.requests) == 1
