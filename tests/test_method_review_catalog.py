"""Method context retains blocked facts without turning them into public approvals."""

import copy
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from test_paper_reading import _claim_units_fixture

from research_radar.analysis.method_flow import MethodRoleValue, reviewed_method_flow
from research_radar.analysis.paper_reading import (
    PaperReading,
    parse_paper_reading,
    validate_paper_reading,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import ReaderContextBudget
from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
from research_radar.analysis.review_targets import ReviewContractError, build_review_targets
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, Claim, ClaimStatus, SourceCandidate, SourceType
from research_radar.security.secrets import KeychainSecretBackend

FIXTURE = Path(__file__).parent / "fixtures/method_flow/memguide_score_operations.json"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("No network or real credentials in a method-contract regression")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def score_reading() -> tuple[Artifact, PaperReading, list[Claim]]:
    """Reuse real assertion text in an explicitly reduced, source-grounded regression."""
    saved = json.loads(FIXTURE.read_text())
    artifact = Artifact(SourceCandidate(saved["title"], saved["source_url"], SourceType.PAPER,
                                        "offline"), "\n\n".join(saved["source_excerpts"]))
    response = json.loads(_claim_units_fixture(["Offline fixture initialization."]))
    body = response["deep_readings"]
    body["claim_units"] = [{**u, "section": "solution", "claim_kind": "fact",
        "publishable_default": True, "evidence": [{"quote": q} for q in saved["source_excerpts"]]}
        for u in saved["claims"]]
    body["reader_explanation"] = {}
    body["method_flow"] = {"operations": [{"scope": u["text"],
        "operation_claim_id": u["claim_id"], "inputs": [], "outputs": [], "conditions": []}
        for u in saved["claims"] if u["method"]["kind"] == "operation"], "links": [{
            "from_claim_id": "c13", "to_claim_id": "c14", "relation_claim_id": "c20"}],
        "gaps": []}
    reading = parse_paper_reading(json.dumps(response), artifact, require_method_assertions=True)
    claims, _ = validate_paper_reading(reading, artifact)
    return artifact, reading, claims


class BoundaryReviewer:
    """Declared offline decisions; constrained output cannot approve blocked method support."""

    name = "offline-catalog"
    supports_response_schema = True
    reader_contexts = {"offline": ReaderContextBudget(1000000, 32768, 8192)}

    def __init__(self, *, reject_id: str | None = None) -> None:
        self.reject_id = reject_id
        self.requests = []
        self.contexts = []

    def complete_with_schema(
        self, messages: list[Message], *, model: str, response_schema: dict,
    ) -> ModelResponse:
        manifest = json.loads(messages[-1].content.split("REVIEW TARGETS (JSON):\n")[1])
        self.contexts.append(json.loads(messages[-1].content.split(
            "FULL SOURCE CONTEXT (JSON):\n")[1].split("\nREVIEW TARGETS (JSON):\n")[0]))
        self.requests.append((manifest, response_schema))
        result = {}
        for key, target in manifest.items():
            status = "needs_review" if target.get("blocked_claim_ids") else (
                "unsupported" if self.reject_id and target.get("claim_id") == self.reject_id
                else "supported")
            result[key] = {
                "status": status, "reason": "Explicit offline decision, not model quality.",
                "evidence_refs": list(target["direct_evidence"]),
            }
        return ModelResponse(json.dumps({"decisions": result}), model)


@pytest.mark.parametrize("identity", ["c14", "c20"])
def test_saved_score_operations_are_not_rejected_as_empirical_results(identity: str) -> None:
    _, _, claims = score_reading()
    claim = next(c for c in claims if c.metadata["paper_reading"]["claim_id"] == identity)
    assert claim.is_publishable()
    assert "split method and result" not in claim.metadata["paper_reading"]["status_reason"]
    assert not fact_is_reviewed(claim)


def test_score_operations_require_explicit_fact_and_method_approval() -> None:
    artifact, reading, claims = score_reading()
    provider = BoundaryReviewer()
    result = review_publication_facts(claims, provider, model="offline",
                                      readings=[reading], artifacts=[artifact])
    assert len(provider.requests) == 1
    assert all(fact_is_reviewed(c) for c in result.claims)
    assert reviewed_method_flow(result.readings[0].method_flow, result.claims,
                                source_url=reading.source_url)["operations"]


@pytest.mark.parametrize("status", [ClaimStatus.NEEDS_REVIEW, ClaimStatus.UNSUPPORTED,
                                     ClaimStatus.SPECULATIVE])
def test_filtered_method_fact_is_context_only_and_never_promoted(status: ClaimStatus) -> None:
    artifact, reading, claims = score_reading()
    claims = [replace(c, status=status) if c.metadata["paper_reading"]["claim_id"] == "c14"
              else replace(c, status=ClaimStatus.SUPPORTED) for c in claims]
    before = copy.deepcopy(claims)
    provider = BoundaryReviewer()
    result = review_publication_facts(claims, provider, model="offline",
                                      readings=[reading], artifacts=[artifact])
    manifest, schema = provider.requests[0]
    assert not any(t["kind"] == "fact" and t["claim_id"] == "c14" for t in manifest.values())
    blocked = {k: t for k, t in manifest.items() if t.get("blocked_claim_ids")}
    assert {t["kind"] for t in blocked.values()} == {"operation", "link"}
    assert all(t["blocked_claim_ids"] == ["c14"] for t in blocked.values())
    for key in blocked:
        assert "supported" not in schema["properties"]["decisions"]["properties"][key][
            "properties"]["status"]["enum"]
    context_fact = next(t for t in blocked.values() if t["kind"] == "operation")["assertion"]
    assert context_fact["status"] == status.value
    proposal = provider.contexts[0]["method_flow_proposals"][0]
    omitted = next(c for c in proposal["supporting_claims"] if c["claim_id"] == "c14")
    assert omitted["claim_index"] is None and omitted["status"] == status.value
    assert claims == before and result.claims[1].status == status
    assert not fact_is_reviewed(result.claims[1])
    assert result.readings[0].method_flow.operations[1].review.status == "needs_review"
    with pytest.raises(AnalysisError, match="unavailable"):
        reviewed_method_flow(result.readings[0].method_flow, result.claims,
                             source_url=reading.source_url)


def test_a_new_negative_fact_decision_cannot_authorize_the_method() -> None:
    artifact, reading, claims = score_reading()
    claims = [replace(c, status=ClaimStatus.SUPPORTED) for c in claims]
    provider = BoundaryReviewer(reject_id="c14")
    result = review_publication_facts(claims, provider, model="offline",
                                      readings=[reading], artifacts=[artifact])
    assert result.claims[1].status == ClaimStatus.UNSUPPORTED
    assert result.readings[0].method_flow.operations[1].review.status == "needs_review"
    with pytest.raises(AnalysisError, match="unavailable"):
        reviewed_method_flow(result.readings[0].method_flow, result.claims,
                             source_url=reading.source_url)


@pytest.mark.parametrize("role", ["inputs", "outputs", "conditions"])
def test_blocked_material_or_condition_cannot_approve_an_otherwise_valid_operation(
    role: str,
) -> None:
    artifact, reading, claims = score_reading()
    claims[0] = replace(claims[0], status=ClaimStatus.NEEDS_REVIEW)
    first, second = reading.method_flow.operations
    second = replace(second, **{role: [MethodRoleValue("Slot-utility score", ["c13"])]})
    reading = replace(reading, method_flow=replace(reading.method_flow, operations=[first, second]))
    provider = BoundaryReviewer()
    result = review_publication_facts(claims, provider, model="offline",
                                      readings=[reading], artifacts=[artifact])
    operation = next(t for t in provider.requests[0][0].values()
                     if t["kind"] == "operation" and t["operation_claim_id"] == "c14")
    assert operation["blocked_claim_ids"] == ["c13"]
    assert fact_is_reviewed(result.claims[1])
    assert result.readings[0].method_flow.operations[1].review.status == "needs_review"
    with pytest.raises(AnalysisError):
        reviewed_method_flow(result.readings[0].method_flow, result.claims,
                             source_url=reading.source_url)


def test_missing_decision_still_fails_and_never_fills_in_a_method_approval() -> None:
    class Incomplete(BoundaryReviewer):
        def complete_with_schema(self, *args, **kwargs) -> ModelResponse:
            response = super().complete_with_schema(*args, **kwargs)
            result = json.loads(response.content)
            result["decisions"].pop(next(iter(result["decisions"])))
            return replace(response, content=json.dumps(result))

    artifact, reading, claims = score_reading()
    claims = [replace(c, status=ClaimStatus.SUPPORTED) for c in claims]
    with pytest.raises(ReviewContractError, match="target_set_mismatch"):
        review_publication_facts(claims, Incomplete(), model="offline",
                                 readings=[reading], artifacts=[artifact])


@pytest.mark.parametrize("bad", ["missing", "duplicate", "foreign", "no_evidence"])
def test_full_catalog_never_invents_source_identity_or_evidence(bad: str) -> None:
    artifact, reading, claims = score_reading()
    claims = [replace(c, status=ClaimStatus.SUPPORTED) for c in claims]
    catalog = list(claims)
    if bad == "missing":
        catalog.pop(1)
    elif bad == "duplicate":
        catalog.append(claims[1])
    elif bad == "foreign":
        catalog[1] = replace(claims[1], evidence=[replace(a, source_url="https://other.test")
                                                for a in claims[1].evidence])
    else:
        catalog[1] = replace(claims[1], evidence=[])
    context, _ = build_reading_review_context([reading], claims, [artifact])
    with pytest.raises(ReviewContractError, match="unavailable_direct_fact"):
        build_review_targets([claims[0], claims[2]], context, source_claims=catalog)


def test_a_paragraph_cannot_use_a_filtered_fact_just_because_it_is_in_the_catalog() -> None:
    artifact, reading, claims = score_reading()
    context, _ = build_reading_review_context([reading], claims, [artifact])
    payload = json.loads(context)
    payload["method_flow_proposals"] = []
    payload["paragraphs"] = [{"paragraph_id": "p1.solution_walkthrough.1",
        "source_url": reading.source_url, "text": "Not independently approved.",
        "supporting_claim_ids": ["c14"]}]
    with pytest.raises(ReviewContractError, match="unavailable_direct_fact"):
        build_review_targets([claims[0]], json.dumps(payload), source_claims=claims)


def test_blocked_method_cannot_be_approved_by_an_invalid_positive_response() -> None:
    artifact, reading, claims = score_reading()
    claims[1] = replace(claims[1], status=ClaimStatus.NEEDS_REVIEW)
    eligible = [c for c in claims if c.is_publishable()]
    context, _ = build_reading_review_context([reading], eligible, [artifact])
    contract = build_review_targets(eligible, context, source_claims=claims)
    response = {key: {"status": "supported", "reason": "Unjustified approval.",
        "evidence_refs": list(t["direct_evidence"])} for key, t in contract.targets.items()}
    with pytest.raises(ReviewContractError, match="invalid_decision"):
        contract.normalize(json.dumps({"decisions": response}))


def test_a_combined_method_and_false_result_still_fails_evidence_validation() -> None:
    from research_radar.analysis.anchor_repair import apply_anchor_resolution

    artifact, _, claims = score_reading()
    combined = replace(claims[1], text=claims[1].text + " It reports F1 of 99.99%.")
    checked, _, _ = apply_anchor_resolution([combined], artifact)
    assert not checked[0].is_publishable()
    assert checked[0].metadata["anchor_resolution"]["status"] == "failed"


def test_an_empty_review_subset_cannot_create_method_approval() -> None:
    artifact, reading, claims = score_reading()
    claims = [replace(c, status=ClaimStatus.NEEDS_REVIEW) for c in claims]
    provider = BoundaryReviewer()
    result = review_publication_facts(claims, provider, model="offline",
                                      readings=[reading], artifacts=[artifact])
    assert provider.requests == [] and not any(fact_is_reviewed(c) for c in result.claims)
    with pytest.raises(AnalysisError, match="unavailable"):
        reviewed_method_flow(result.readings[0].method_flow, result.claims,
                             source_url=reading.source_url)


def test_unconstrained_review_cannot_promote_filtered_method_support() -> None:
    from test_publication_composition import Composer

    artifact, reading, claims = score_reading()
    claims[1] = replace(claims[1], status=ClaimStatus.UNSUPPORTED)
    provider = Composer({"decisions": [{"claim_index": i, "status": "supported",
        "reason": "Explicit offline fact control."} for i in (1, 2)],
        "method_operation_decisions": [{"source_url": reading.source_url,
            "operation_claim_id": identity, "status": "supported",
            "reason": "Invalid approval over blocked support."} for identity in ("c13", "c14")],
        "method_link_decisions": [{"source_url": reading.source_url,
            "from_claim_id": "c13", "to_claim_id": "c14", "status": "supported",
            "reason": "Invalid approval over blocked support."}]})
    result = review_publication_facts(claims, provider, model="offline",
                                      readings=[reading], artifacts=[artifact])
    assert len(provider.requests) == 1
    context = json.loads(provider.requests[0][-1].content.split(
        "FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n")[1])
    record = next(c for c in context["method_flow_proposals"][0]["supporting_claims"]
                  if c["claim_id"] == "c14")
    assert record["status"] == "unsupported" and record["claim_index"] is None
    assert result.claims[1].status == ClaimStatus.UNSUPPORTED
    assert result.readings[0].method_flow.operations[1].review.status == "needs_review"
    with pytest.raises(AnalysisError):
        reviewed_method_flow(result.readings[0].method_flow, result.claims,
                             source_url=reading.source_url)
