"""Matched text context survives schema review without supplying missing premises by guess."""

import copy
import json
from dataclasses import replace

import pytest
from test_review_presentation import expand_presentation

from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.analysis.review_targets import build_review_targets
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

URL = "https://example.test/memguide"
ANNOTATION = "The final session is annotated with confirmation-type responses."
CONTEXT = ANNOTATION + "\nOne held-out evaluation session is used per intent."


def material() -> tuple[Claim, Artifact]:
    """Small independent control: the qualifier is in existing context, not the selected quote."""
    artifact = Artifact(SourceCandidate("Study", URL, SourceType.PAPER, "offline"),
                        "[page 3]\n" + CONTEXT + "\nOther text.")
    claim = Claim("Evaluation uses held-out confirmation sessions.", ClaimStatus.SUPPORTED,
        [EvidenceAnchor(URL, ANNOTATION, "page 3")], metadata={"paper_reading": {
            "claim_id": "c29"}, "anchor_resolution": {"status": "matched",
            "evidence_contexts": [{"source_url": URL, "quote": ANNOTATION,
                                   "text": CONTEXT, "location": "page 3"}]}})
    return claim, artifact


def contract_for(claim: Claim, artifact: Artifact):
    context, _ = build_reading_review_context([], [claim], [artifact])
    return build_review_targets([claim], context), context


def test_exact_existing_context_is_selectable_with_its_original_anchor() -> None:
    claim, artifact = material()
    before = copy.deepcopy(claim)
    contract, context = contract_for(claim, artifact)
    fact = next(iter(contract.targets.values()))
    proof = next(iter(fact["direct_evidence"].values()))
    assert proof["quote"] == ANNOTATION
    assert proof["source_contexts"][0]["text"] == CONTEXT
    assert proof["source_contexts"][0]["start"] == 9
    assert proof["source_contexts"][0]["end"] == 9 + len(CONTEXT)
    assert len(fact["direct_evidence"]) == 1  # No redundant second citation/confirmation.
    assert expand_presentation(contract.presentation(context)) == {
        "source_context": json.loads(context), "targets": contract.targets}
    assert claim == before


@pytest.mark.parametrize("defect", ["foreign", "wrong_quote", "fabricated", "ambiguous",
                                  "unmatched", "positioned"])
def test_unbound_context_cannot_become_evidence(defect: str) -> None:
    claim, artifact = material()
    claim = copy.deepcopy(claim)
    context = claim.metadata["anchor_resolution"]["evidence_contexts"][0]
    if defect == "foreign":
        context["source_url"] = "https://foreign.test/paper"
    elif defect == "wrong_quote":
        context["quote"] = "A different quote."
    elif defect == "fabricated":
        context["text"] = ANNOTATION + "\nA fabricated qualifier."
    elif defect == "ambiguous":
        artifact = replace(artifact, text=artifact.text + "\n" + CONTEXT)
    elif defect == "unmatched":
        claim.metadata["anchor_resolution"]["status"] = "needs_review"
    else:
        context["positioned"] = {"table": {"table_id": "test", "cells": []},
                                 "selected_cell_ids": []}
        # This test isolates the context projection; the positioned validator has its own tests.
        reading_context, _ = build_reading_review_context([], [claim], [artifact])
        assert json.loads(reading_context).get("text_evidence_contexts", []) == []
        return
    contract, _ = contract_for(claim, artifact)
    assert all("source_contexts" not in proof
               for target in contract.targets.values()
               for proof in target["direct_evidence"].values())


def test_same_paper_context_of_another_fact_is_not_borrowed() -> None:
    claim, artifact = material()
    other = replace(claim, text="A different assertion.", metadata={"paper_reading": {
        "claim_id": "c55"}})
    context, _ = build_reading_review_context([], [claim, other], [artifact])
    contract = build_review_targets([claim, other], context)
    facts = {t["claim_id"]: t for t in contract.targets.values()}
    assert next(iter(facts["c29"]["direct_evidence"].values()))["source_contexts"]
    assert "source_contexts" not in next(iter(facts["c55"]["direct_evidence"].values()))


def test_added_context_cannot_reuse_an_old_positive_receipt() -> None:
    from test_review_evidence_selection import selection_reply

    claim, artifact = material()
    previous = build_review_targets([claim], "")
    receipt = json.loads(previous.normalize(json.dumps(selection_reply(previous))))
    current, _ = contract_for(claim, artifact)
    assert current.reuse_supported(receipt) == {}


def test_full_source_context_alone_never_grants_a_positive_decision() -> None:
    from test_review_evidence_selection import selection_reply

    claim, artifact = material()
    contract, _ = contract_for(claim, artifact)
    payload = selection_reply(contract)
    for decision in payload["decisions"].values():
        decision.update(status="needs_review", reason="Explicit offline unresolved control.",
                        evidence_refs=[])
    normalized = json.loads(contract.normalize(json.dumps(payload)))
    assert normalized["decisions"][0]["status"] == "needs_review"


def test_complete_comparison_does_not_reoffer_its_caption_as_an_unrelated_window() -> None:
    from test_table_comparison_review import DATA

    from research_radar.analysis.experimental_results import experimental_assertion_identity

    case = copy.deepcopy(DATA["cases"][0])
    caption = EvidenceAnchor(DATA["source_url"], "Table 3 compares FCP and MemGuide.",
                             "page 6; Table 3 caption", "MemGuide")
    text = caption.quote + "\nAn independent evaluation condition."
    row = case["claim"]
    claim = Claim(row["text"], ClaimStatus(row["status"]),
        [*[EvidenceAnchor(**e) for e in row["evidence"]], caption],
        row["rationale"], row["metadata"])
    claim.metadata["anchor_resolution"]["status"] = "matched"
    claim.metadata["anchor_resolution"]["evidence_contexts"].append({
        "source_url": caption.source_url, "quote": caption.quote, "text": text})
    case["proposal"]["evidence"].append({
        "source_url": caption.source_url, "quote": caption.quote, "location": caption.location,
        "source_title": caption.source_title, "confidence": caption.confidence})
    for assertion in case["binding"]["assertions"]:
        if assertion["claim_id"] == "c33":
            assertion["assertion_sha256"] = experimental_assertion_identity(claim)
    artifact = Artifact(SourceCandidate("Study", DATA["source_url"], SourceType.PAPER, "offline"),
                        text)
    context, _ = build_reading_review_context([], [claim], [artifact])
    context = json.loads(context)
    context["experimental_result_proposals"] = [{"source_url": DATA["source_url"],
        "results": [case["proposal"]], "bindings": [case["binding"]]}]
    contract = build_review_targets([claim], json.dumps(context))
    target = next(iter(contract.targets.values()))
    ordinary = set(target["direct_evidence"]) - set(target["comparison_units"])
    assert not ordinary
    unit = target["direct_evidence"][target["comparison_units"][0]]
    assert unit["complete"]
    assert any(e["quote"] == caption.quote for e in unit["proposal"]["evidence"])
