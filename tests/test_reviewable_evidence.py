"""Local table ambiguity is reviewable, not already public or semantically disproven."""

import copy
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from test_experimental_cell_bindings import saved_result
from test_experimental_results_contract import fixture
from test_method_review_catalog import BoundaryReviewer
from test_review_targets import SchemaReviewer

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.paper_reading import EvaluationContext, parse_paper_reading
from research_radar.analysis.reading_review import (
    build_reading_review_context,
    context_coverage_requirements,
)
from research_radar.analysis.review import (
    fact_is_reviewed,
    model_review_publishable_claims,
    review_publication_facts,
)
from research_radar.models import ClaimStatus
from research_radar.security.secrets import KeychainSecretBackend


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("No service or secret access during evidence admission tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def pending_input(tmp_path: Path):
    artifact, experiment, original = saved_result(tmp_path)
    original = replace(original, status=ClaimStatus.SUPPORTED)
    checked, _, _ = apply_anchor_resolution([original], artifact)
    base, payload = fixture()
    reading = replace(parse_paper_reading(json.dumps(payload), base),
                      source_url=artifact.source.url, experimental_results=[experiment])
    return artifact, reading, original, checked[0]


def test_table_ambiguity_reaches_factual_review_without_being_public_before_it(tmp_path: Path):
    artifact, reading, original, pending = pending_input(tmp_path)
    assert pending.status == ClaimStatus.NEEDS_REVIEW
    assert not pending.is_publishable()
    assert pending.metadata["evidence_review_candidate"]["code"] == "table_semantics"
    reviewer = BoundaryReviewer()
    result = review_publication_facts([pending], reviewer, model="offline",
                                     readings=[reading], artifacts=[artifact])
    assert len(reviewer.requests) == 1
    assert fact_is_reviewed(result.claims[0])
    assert result.claims[0].text == original.text
    assert result.claims[0].evidence == original.evidence
    assert result.claims[0].metadata["fact_review_admission"]["prior_status"] == "needs_review"
    assert not pending.is_publishable()  # caller's input is never mutated


def test_final_review_cannot_use_the_factual_admission_exception(tmp_path: Path):
    artifact, reading, _, pending = pending_input(tmp_path)
    reviewer = BoundaryReviewer()
    result = model_review_publishable_claims([pending], reviewer, model="offline",
                                            readings=[reading], artifacts=[artifact])
    assert reviewer.requests == []
    assert result.claims == [pending]


def test_negative_decision_is_not_upgraded_or_retried(tmp_path: Path):
    artifact, reading, _, pending = pending_input(tmp_path)
    reviewer = BoundaryReviewer(reject_id="c51")
    result = review_publication_facts([pending], reviewer, model="offline",
                                     readings=[reading], artifacts=[artifact])
    assert result.claims[0].status == ClaimStatus.UNSUPPORTED
    assert not fact_is_reviewed(result.claims[0])
    again = review_publication_facts(result.claims, reviewer, model="offline",
                                    readings=[reading], artifacts=[artifact])
    assert len(reviewer.requests) == 1
    assert again.claims == result.claims


@pytest.mark.parametrize("bad", ["text", "quote", "source", "prior_review", "marker"])
def test_stale_or_reviewed_candidate_is_never_admitted(tmp_path: Path, bad: str):
    artifact, reading, _, pending = pending_input(tmp_path)
    if bad == "text":
        pending = replace(pending, text="Altered assertion")
    elif bad == "quote":
        pending = replace(pending, evidence=[replace(pending.evidence[0], quote="Changed quote")])
    elif bad == "source":
        artifact = replace(artifact, text=artifact.text + "\nDifferent version")
    elif bad == "prior_review":
        pending = replace(pending, metadata={**pending.metadata,
                                           "model_review": {"requested_status": "needs_review"}})
    else:
        metadata = copy.deepcopy(pending.metadata)
        metadata["evidence_review_candidate"]["binding_sha256"] = "forged"
        pending = replace(pending, metadata=metadata)
    reviewer = BoundaryReviewer()
    result = review_publication_facts([pending], reviewer, model="offline",
                                     readings=[reading], artifacts=[artifact])
    assert not reviewer.requests
    assert result.claims == [pending]


@pytest.mark.parametrize("bad", ["wrong_value", "missing_quote", "foreign_source"])
def test_invalid_evidence_does_not_gain_a_candidate_marker(tmp_path: Path, bad: str):
    artifact, _, original, _ = pending_input(tmp_path)
    if bad == "wrong_value":
        original = replace(original, text="On SGD, MemGuide reports JGA 0.879.")
    elif bad == "missing_quote":
        original = replace(original, evidence=[replace(original.evidence[0], quote="Not present")])
    else:
        original = replace(original, evidence=[replace(e, source_url="https://example.org/other")
                                               for e in original.evidence])
    checked, _, _ = apply_anchor_resolution([original], artifact)
    assert not checked[0].is_publishable()
    assert "evidence_review_candidate" not in checked[0].metadata


def test_reader_nonpublic_proposal_needs_a_real_explicit_fact_decision(tmp_path: Path):
    artifact, payload = fixture()
    reading = parse_paper_reading(json.dumps(payload), artifact)
    from research_radar.analysis.paper_reading import reading_to_claims

    proposal = reading_to_claims(reading)[0]
    proposal = replace(proposal, status=ClaimStatus.NEEDS_REVIEW, metadata={
        **proposal.metadata, "paper_reading": {**proposal.metadata["paper_reading"],
            "publishable_default": False}})
    pending, _, _ = apply_anchor_resolution([proposal], artifact)
    assert pending[0].metadata["evidence_review_candidate"]["code"] == "reader_proposal"
    reviewer = BoundaryReviewer()
    result = review_publication_facts(pending, reviewer, model="offline",
                                     readings=[reading], artifacts=[artifact])
    assert fact_is_reviewed(result.claims[0])


def test_known_unverified_context_is_visible_but_not_a_positive_prose_obligation(tmp_path: Path):
    artifact, reading, _, pending = pending_input(tmp_path)
    known = replace(pending, status=ClaimStatus.SUPPORTED, metadata={"paper_reading": {
        "claim_id": "known", "source": "claim_units"}})
    reading = replace(reading, evaluation_context=EvaluationContext(claim_references={
        "data_construction": ["c51", "known"], "available_inputs": [], "outcome_measurement": []}))
    required = context_coverage_requirements([known], source_url=artifact.source.url,
        evaluation_context=reading.evaluation_context, source_claims=[pending, known])
    assert required == {"experiment_interpretation": ["known"]}
    context, _ = build_reading_review_context([reading], [known], [artifact],
                                             source_claims=[pending, known])
    proposal = json.loads(context)["evaluation_context_proposals"][0]
    assert proposal["conditions"]["data_construction"] == ["c51", "known"]
    assert proposal["unavailable_claim_ids"] == ["c51"]
    # Missing/foreign identity remains an invalid index, never silently discarded.
    from research_radar.exceptions import AnalysisError

    with pytest.raises(AnalysisError):
        context_coverage_requirements([], source_url=artifact.source.url,
            evaluation_context=reading.evaluation_context, source_claims=[])


def test_a_whole_declared_evaluation_dimension_cannot_disappear(tmp_path: Path):
    from research_radar.exceptions import AnalysisError

    artifact, reading, _, pending = pending_input(tmp_path)
    reading = replace(reading, evaluation_context=EvaluationContext(claim_references={
        "data_construction": ["c51"], "available_inputs": [], "outcome_measurement": []}))
    with pytest.raises(AnalysisError, match="Evaluation context"):
        context_coverage_requirements([], source_url=artifact.source.url,
            evaluation_context=reading.evaluation_context, source_claims=[pending])


@pytest.mark.parametrize("bad", ["missing", "unknown", "duplicate", "state", "reason"])
def test_invalid_pending_decisions_cannot_escape_as_public_claims(tmp_path: Path, bad: str):
    from research_radar.exceptions import AnalysisError

    artifact, reading, _, pending = pending_input(tmp_path)
    before = copy.deepcopy(pending)
    reviewer = SchemaReviewer(bad)
    with pytest.raises(AnalysisError):
        review_publication_facts([pending], reviewer, model="offline",
                                 readings=[reading], artifacts=[artifact])
    assert pending == before and not pending.is_publishable()
    assert len(reviewer.requests) == 1


def test_pending_evidence_cannot_fall_back_to_an_unconstrained_reviewer(tmp_path: Path):
    from research_radar.exceptions import AnalysisError

    artifact, reading, _, pending = pending_input(tmp_path)
    reviewer = BoundaryReviewer()
    reviewer.supports_response_schema = False
    with pytest.raises(AnalysisError, match="structured"):
        review_publication_facts([pending], reviewer, model="offline",
                                 readings=[reading], artifacts=[artifact])
    assert not reviewer.requests


def test_local_table_ambiguity_does_not_trigger_a_quote_repair_call(tmp_path: Path):
    from research_radar.analysis.anchor_repair import apply_anchor_repair

    artifact, _, original, _ = pending_input(tmp_path)
    class ForbiddenRepair:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("Semantic ambiguity is not a missing quotation")
    claims, _, attempts, _ = apply_anchor_repair([original], artifact, ForbiddenRepair(),
                                                model="offline")
    assert not attempts and not claims[0].is_publishable()
