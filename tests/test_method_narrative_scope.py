"""Method indexing is not completeness, and paragraph support is never borrowed."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_composition_scope_boundary import scoped_material, writer_answer
from test_publication_composition import Composer
from test_review_targets import SchemaReviewer

from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.method_flow import MethodFlow
from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.analysis.review import model_review_publishable_claims
from research_radar.analysis.review_targets import build_review_targets

FIXTURE = Path(__file__).parent / "fixtures/method_narrative_scope.json"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from research_radar.security.secrets import KeychainSecretBackend

    def forbidden(*_args, **_kwargs):
        raise AssertionError("This regression cannot access networks or credentials")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def write_control():
    """Use explicit editorial prose through the shared writer, never synthesize approval."""
    data, reading, facts, artifact = scoped_material()
    writer = Composer(writer_answer(data))
    result = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(result)
    payload = json.loads(writer.requests[0][-1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    return reading, facts, artifact, result, payload


def test_individually_approved_operations_do_not_certify_a_complete_workflow() -> None:
    reading, facts, artifact, result, payload = write_control()
    assert reading.method_flow.gaps == []
    assert all(op.review.status == "supported" for op in reading.method_flow.operations)
    assert payload["method_scope"] == {
        "coverage": "indexed_facts_only", "order": "explicit_links_only",
        "operation_support": {"c8": ["c8"], "c9": ["c9"],
                              "c12": ["c12"], "c16": ["c16"]},
    }
    reviewer = SchemaReviewer()
    model_review_publishable_claims(result.claims, reviewer, model="offline",
        readings=result.readings, artifacts=[artifact], analysis_claims=facts)
    context = json.loads(reviewer.requests[0][0][-1].content.split(
        "FULL SOURCE CONTEXT (JSON):\n")[1].split("\nREVIEW TARGETS (JSON):\n")[0])
    assert context["method_flow_proposals"][0]["narrative_scope"] == payload["method_scope"]


def test_empty_legacy_index_cannot_be_promoted_to_complete_coverage() -> None:
    from research_radar.analysis.method_flow import method_narrative_scope

    for flow in (MethodFlow(), MethodFlow(step_claim_ids=["legacy"]),
                 MethodFlow(operations=[])):
        assert method_narrative_scope(flow) == {
            "coverage": "indexed_facts_only", "order": "explicit_links_only",
            "operation_support": {},
        }


@pytest.mark.parametrize("include_consumer", [False, True])
def test_paragraph_evidence_remains_attached_to_its_declared_facts(include_consumer: bool) -> None:
    _, reading, facts, artifact = scoped_material()
    support = ["c12", "c16"] if include_consumer else ["c12"]
    original = ReaderExplanationParagraph("缺失槽位还用于回答生成。", support)
    reading = replace(reading, reader_explanation=ReaderExplanation(
        solution_walkthrough=[original]))
    before = copy.deepcopy((reading, facts))
    context, _ = build_reading_review_context([reading], facts, [artifact])
    contract = build_review_targets(facts, context, method_sources=set())
    target = next(t for t in contract.targets.values() if t["kind"] == "paragraph")
    records = {row["claim_id"]: row for row in target["supporting_claims"]}
    assert set(records) == set(support)
    assert records["c12"]["evidence"] == [{
        "source_url": reading.source_url, "quote": facts[2].evidence[0].quote,
        "location": facts[2].evidence[0].location, "source_title": None, "confidence": 1.0,
    }]
    if include_consumer:
        assert records["c16"]["evidence"][0]["quote"] == facts[3].evidence[0].quote
        assert records["c16"]["evidence"] != records["c12"]["evidence"]
    else:
        assert "c16" not in records
        assert all(proof.get("quote") != facts[3].evidence[0].quote
                   for proof in target["direct_evidence"].values())
    from test_review_presentation import expand_presentation

    assert expand_presentation(contract.presentation(context)) == {
        "source_context": json.loads(context), "targets": contract.targets}
    assert (reading, facts) == before


def test_source_and_paragraph_changes_cannot_inherit_prior_approval() -> None:
    from research_radar.analysis.reading_review import paragraph_is_public

    _, facts, artifact, localized, _ = write_control()
    final = model_review_publishable_claims(localized.claims, SchemaReviewer(), model="offline",
        readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    paragraph = final.readings[0].reader_explanation.solution_walkthrough[0]
    assert paragraph_is_public(paragraph, final.claims, source_url=artifact.source.url)
    assert not paragraph_is_public(replace(paragraph, text="整个流程没有其他步骤。"),
                                   final.claims, source_url=artifact.source.url)
    assert not paragraph_is_public(replace(paragraph, supporting_claim_ids=["c12"]),
                                   final.claims, source_url=artifact.source.url)
    assert not paragraph_is_public(paragraph, final.claims, source_url="https://foreign.test")


def test_saved_consumer_clause_is_not_auto_bound_or_borrowed_from_another_paragraph() -> None:
    """Replay the actual rejected clause against a source-scoped target, not a guessed ID."""
    from research_radar.analysis.reading_review import apply_explanation_decisions
    from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

    data = json.loads(FIXTURE.read_text())
    _, reading, _, _ = scoped_material()
    original = data["cases"][1]
    facts = [Claim(text, ClaimStatus.SUPPORTED, [EvidenceAnchor(data["source_url"], quote)],
        metadata={"paper_reading": {"claim_id": identity}, "model_review": {
            "status": "supported", "requested_status": "supported"}})
        for identity, text, quote in [
            ("c12", "The reasoner lists unresolved task slots.",
             "The reasoner lists unresolved slots."),
            ("c18", "Missing slots are identified after retrieval.", "Retrieve before reasoning."),
            ("c19", "Missing slots precede utility scoring.", "Reason before scoring."),
            ("c16", "The response generator receives missing slots.", data["generation_source"]),
            ("c21", "Selection precedes response generation.", "Select before generating."),
        ]]
    paragraphs = [ReaderExplanationParagraph(**original["original"]),
                  ReaderExplanationParagraph(**data["unchanged_consumer"])]
    reading = replace(reading, method_flow=MethodFlow(), reader_explanation=ReaderExplanation(
        solution_walkthrough=paragraphs))
    context, _ = build_reading_review_context([reading], facts, [])
    contract = build_review_targets(facts, context, method_sources=set())
    targets = [t for t in contract.targets.values() if t["kind"] == "paragraph"]
    assert targets[0]["supporting_claim_ids"] == ["c18", "c12", "c19"]
    assert all(proof.get("quote") != data["generation_source"]
               for proof in targets[0]["direct_evidence"].values())
    assert any(proof.get("quote") == data["generation_source"]
               for proof in targets[1]["direct_evidence"].values())
    reviewed = apply_explanation_decisions([reading], facts, {"explanation_decisions": [{
        "paragraph_id": "p1.solution_walkthrough.1", "status": original["status"],
        "reason": original["reason"], "covered_claim_ids": ["c18", "c12", "c19"],
    }]}, source_urls={data["source_url"]})
    rejected = reviewed[0].reader_explanation.solution_walkthrough[0]
    assert rejected.review.status == "needs_review"
    assert rejected.text == original["original"]["text"]
    assert rejected.supporting_claim_ids == ["c18", "c12", "c19"]
    assert reviewed[0].reader_explanation.solution_walkthrough[1].review.status == "needs_review"


def test_operation_support_keeps_explicit_role_facts_without_inferring_consumers() -> None:
    from research_radar.analysis.method_flow import (
        MethodOperation,
        MethodRoleValue,
        method_narrative_scope,
    )

    operation = MethodOperation("Generate response", "c16",
        [MethodRoleValue("Selected memory", ["c14", "c16"])],
        [MethodRoleValue("Response", ["c16"])], [])
    flow = MethodFlow(operations=[operation])
    scope = method_narrative_scope(flow)
    assert scope["operation_support"] == {"c16": ["c16", "c14"]}
    scope["operation_support"]["c16"].append("invented")
    assert method_narrative_scope(flow)["operation_support"] == {"c16": ["c16", "c14"]}
