"""Saved generalization rejection stays unresolved until explicit evidence and fresh review."""

import copy
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from test_explanation_support_contract import _reading
from test_publication_composition import Composer
from test_review_targets import SchemaReviewer

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.analysis.review import (
    fact_is_reviewed,
    model_review_publishable_claims,
    review_publication_facts,
)
from research_radar.analysis.review_targets import build_review_targets
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)
from research_radar.security.secrets import KeychainSecretBackend

FIXTURE = Path(__file__).parent / "fixtures/generalization_evidence_binding.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No network or key access in saved generalization regressions")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def material():
    """Use exact saved claims and decisions, with explicitly bounded public source excerpts."""
    claims = [Claim(row["analysis_text"], ClaimStatus.SUPPORTED,
        [EvidenceAnchor(**e) for e in row["evidence"]], metadata={
            "paper_reading": copy.deepcopy(row["paper_reading"]),
            "fact_review": copy.deepcopy(row["fact_review"]),
            "anchor_resolution": {"status": "matched", "evidence_contexts": copy.deepcopy(
                row["matched_contexts"])}}) for row in DATA["facts"].values()]
    source = SourceCandidate("MemGuide", DATA["source_url"], SourceType.PAPER, "saved-excerpts")
    texts = list(dict.fromkeys(c["text"] for row in DATA["facts"].values()
                              for c in row["matched_contexts"]))
    artifact = Artifact(source, "\n\n".join([*texts, DATA["explicit_source_selection"]["quote"]]))
    reading = replace(_reading("", []), source_url=source.url, title="MemGuide",
        reader_explanation=ReaderExplanation(limitations_discussion=[
            ReaderExplanationParagraph(**DATA["original_paragraph"])]))
    return claims, artifact, reading


def test_saved_critique_is_missing_a_premise_not_a_new_translation_or_adapter_loss():
    claims, artifact, _ = material()
    before = copy.deepcopy(claims)
    context, _ = build_reading_review_context([], claims, [artifact])
    contract = build_review_targets(claims, context)
    targets = {t["claim_id"]: t for t in contract.targets.values()}
    original = DATA["facts"]["c55"]
    assert "held-out" in original["analysis_text"]
    assert "留出" in original["chinese_text"]
    assert fact_is_reviewed(next(c for c in claims
                                if c.metadata["paper_reading"]["claim_id"] == "c55"))
    assert all("held-out" not in proof["quote"]
               for proof in targets["c55"]["direct_evidence"].values())
    assert all("held-out" not in c["text"]
               for proof in targets["c55"]["direct_evidence"].values()
               for c in proof.get("source_contexts", []))
    assert any("held-out" in c["text"]
               for proof in targets["c29"]["direct_evidence"].values()
               for c in proof.get("source_contexts", []))
    assert claims == before  # Context forwarding never edits the original evidence/receipt.


def test_replaying_actual_negative_decisions_preserves_the_original_limit_for_audit():
    claims, artifact, reading = material()
    original = next(c for c in claims if c.metadata["paper_reading"]["claim_id"] == "c55")
    decision = DATA["facts"]["c55"]["final_decision"]
    reviewer = Composer({"decisions": [{"claim_index": 1, "status": decision["status"],
        "reason": decision["reason"]}], "explanation_decisions": [{
            "paragraph_id": "p1.limitations_discussion.1", **{
                k: DATA["paragraph_decision"][k]
                for k in ("status", "reason", "covered_claim_ids")}}]})
    final = model_review_publishable_claims([original], reviewer, model="offline",
        readings=[reading], artifacts=[artifact])
    paragraph = final.readings[0].reader_explanation.limitations_discussion[0]
    assert paragraph.text == DATA["original_paragraph"]["text"]
    assert paragraph.review.status == "needs_review"
    assert paragraph.review.reason == DATA["paragraph_decision"]["reason"]
    assert final.claims[0].status == ClaimStatus.NEEDS_REVIEW
    public, _ = public_explanation(final.readings[0].reader_explanation, final.claims,
                                   source_url=artifact.source.url)
    assert not public["limitations_discussion"]
    assert len(reviewer.requests) == 1  # No automatic repair or extra model attempt.


def explicit_proposal(original):
    """An editorial source selection, never automatic ID inference or old-receipt repair."""
    source = DATA["explicit_source_selection"]
    return replace(original, evidence=[*original.evidence, EvidenceAnchor(
        DATA["source_url"], source["quote"], source["location"])])


def test_explicit_extra_source_selection_invalidates_the_old_fact_approval():
    claims, _, _ = material()
    original = next(c for c in claims if c.metadata["paper_reading"]["claim_id"] == "c55")
    assert fact_is_reviewed(original)
    proposal = explicit_proposal(original)
    assert proposal.text == original.text and proposal.evidence[:-1] == original.evidence
    assert "one held-out evaluation session" in proposal.evidence[-1].quote
    assert not fact_is_reviewed(proposal)


@pytest.mark.parametrize("final_status", ["supported", "needs_review"])
def test_complete_explicit_proposal_requires_both_fresh_fact_and_final_review(final_status):
    claims, artifact, reading = material()
    original = next(c for c in claims if c.metadata["paper_reading"]["claim_id"] == "c55")
    proposal = explicit_proposal(original)
    facts = review_publication_facts([proposal], SchemaReviewer(), model="offline",
                                    readings=[reading], artifacts=[artifact])
    assert fact_is_reviewed(facts.claims[0])
    chinese = replace(facts.claims[0], text=DATA["facts"]["c55"]["chinese_text"])

    class FinalControl(SchemaReviewer):
        def complete_with_schema(self, messages, *, model, response_schema):
            result = super().complete_with_schema(messages, model=model,
                                                  response_schema=response_schema)
            payload = json.loads(result.content)
            for key, target in self.requests[-1][2].items():
                if target["kind"] == "paragraph":
                    payload["decisions"][key].update(status=final_status,
                        reason="Explicit offline editorial control, not real model approval.")
            return type(result)(json.dumps(payload), model)

    final = model_review_publishable_claims([chinese], FinalControl(), model="offline",
        readings=[reading], artifacts=[artifact], analysis_claims=facts.claims)
    public, _ = public_explanation(final.readings[0].reader_explanation, final.claims,
                                   source_url=artifact.source.url)
    assert (DATA["original_paragraph"]["text"] in public["limitations_discussion"]) is (
        final_status == "supported")
    assert final.readings[0].reader_explanation.limitations_discussion[0].text == (
        DATA["original_paragraph"]["text"])
