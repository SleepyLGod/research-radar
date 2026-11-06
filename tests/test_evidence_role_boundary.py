"""Local provenance, operation structure and semantic review have separate responsibilities."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import legacy_saved_anchors
from test_method_flow import extract
from test_publication_composition import Composer

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.method_flow import (
    MethodLink,
    apply_method_decisions,
    parse_method_flow,
    reviewed_method_flow,
)
from research_radar.analysis.review import review_publication_facts
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

DATA = json.loads(
    (Path(__file__).parent / "fixtures/method_flow/evidence_role_boundary.json").read_text()
)


def saved_case(identity: str) -> tuple[Artifact, Claim]:
    """Use snapshot quotes as legacy evidence; original IDs do not address this excerpt."""
    case = next(c for c in DATA["claims"] if c["claim_id"] == identity)
    anchors = legacy_saved_anchors(case["evidence"])
    artifact = Artifact(
        SourceCandidate("MemConflict", DATA["source_url"], SourceType.PAPER, "offline"),
        "\n\n".join(a.quote for a in anchors),
    )
    return artifact, Claim(
        case["text"],
        ClaimStatus.SUPPORTED,
        evidence=anchors,
        metadata={"paper_reading": {"source": "claim_units", "claim_id": identity}},
    )


@pytest.mark.parametrize("identity", ["c14", "c29"])
def test_saved_generic_phrase_is_not_a_required_named_entity(identity: str) -> None:
    artifact, claim = saved_case(identity)
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert checked[0].text == claim.text and checked[0].evidence == claim.evidence
    assert "fact_review" not in checked[0].metadata


@pytest.mark.parametrize(
    "text",
    [
        "Experiment: The backend uses gpt-6.0-mini.",
        "Experiment: Qwen2.5-7B is evaluated.",
        "Experiment: A-Mem is evaluated.",
    ],
)
def test_specific_names_and_versions_are_still_required(text: str) -> None:
    artifact, original = saved_case("c29")
    claim = replace(original, text=text)
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


@pytest.mark.parametrize(
    "name",
    [
        "Qwen2.5-7B",
        "GPT-4o-mini",
        "all-MiniLM-L6-v2",
        "A-Mem",
    ],
)
def test_complete_identity_is_preserved_when_present(name: str) -> None:
    quote = f"The evaluated model is {name}."
    artifact = Artifact(
        SourceCandidate("Fixture", "https://example.test/paper", SourceType.PAPER, "offline"), quote
    )
    claim = Claim(
        quote, ClaimStatus.SUPPORTED, evidence=[EvidenceAnchor(artifact.source.url, quote)]
    )
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert checked[0].text == quote and checked[0].evidence == claim.evidence


def test_acronym_fragment_does_not_hide_a_wrong_version() -> None:
    quote = "The backend uses GPT-4o-mini."
    artifact = Artifact(
        SourceCandidate("Fixture", "https://example.test/paper", SourceType.PAPER, "offline"), quote
    )
    claim = Claim(
        "The backend uses GPT-5o-mini.",
        ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(artifact.source.url, quote)],
    )
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("bad", ["missing_quote", "changed_value", "wrong_depth"])
def test_syntax_and_numeric_failures_are_not_deferred_to_semantic_review(bad: str) -> None:
    quote = "The white-box retrieval uses K=3 and reports accuracy of 0.75."
    artifact = Artifact(
        SourceCandidate("Fixture", "https://example.test/paper", SourceType.PAPER, "offline"), quote
    )
    claim = Claim(
        "The white-box retrieval uses K=3 and reports accuracy of 0.75.",
        ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(artifact.source.url, quote)],
    )
    if bad == "missing_quote":
        claim = replace(claim, evidence=[replace(claim.evidence[0], quote="Not original.")])
    elif bad == "changed_value":
        claim = replace(claim, text=claim.text.replace("0.75", "0.95"))
    else:
        claim = replace(claim, text=claim.text.replace("K=3", "K=5"))
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


def test_saved_self_dependency_is_rejected_not_silently_removed() -> None:
    value = {
        "operations": [
            {
                "scope": "Query construction",
                "operation_claim_id": "c10",
                "inputs": [],
                "outputs": [],
                "conditions": [],
            }
        ],
        "links": [copy.deepcopy(DATA["self_link"])],
        "gaps": [],
    }
    before = copy.deepcopy(value)
    with pytest.raises(AnalysisError, match="distinct"):
        parse_method_flow(value, claim_ids={"c10"})
    assert value == before


def test_manually_loaded_self_link_cannot_inherit_model_approval() -> None:
    artifact, _, claims, _ = extract("memguide")
    flow = parse_method_flow(
        {
            "operations": [
                {
                    "scope": "Retrieval",
                    "operation_claim_id": "m2",
                    "inputs": [],
                    "outputs": [],
                    "conditions": [],
                }
            ],
            "links": [],
            "gaps": [],
        },
        claim_ids={"m2"},
    )
    flow = replace(flow, links=[MethodLink("m2", "m2", ["m2"])])
    approved = apply_method_decisions(
        flow,
        claims,
        {
            "method_operation_decisions": [
                {
                    "source_url": artifact.source.url,
                    "operation_claim_id": "m2",
                    "status": "supported",
                    "reason": "Offline deliberately incorrect approval.",
                }
            ],
            "method_link_decisions": [
                {
                    "source_url": artifact.source.url,
                    "from_claim_id": "m2",
                    "to_claim_id": "m2",
                    "status": "supported",
                    "reason": "Incorrect control.",
                }
            ],
        },
        source_url=artifact.source.url,
    )
    with pytest.raises(AnalysisError, match="distinct"):
        reviewed_method_flow(approved, claims, source_url=artifact.source.url)


@pytest.mark.parametrize("decision", ["supported", "unsupported", "needs_review", "missing"])
def test_true_condition_requires_a_separate_explicit_role_decision(
    decision: str,
) -> None:
    artifact, claim = saved_case("c3")
    _, reading, _, _ = extract("memconflict")
    operation = copy.deepcopy(DATA["condition_as_operation"])
    flow = parse_method_flow({"operations": [operation], "links": [], "gaps": []}, claim_ids={"c3"})
    reading = replace(reading, source_url=artifact.source.url, method_flow=flow)
    feedback = {
        "decisions": [
            {
                "claim_index": 1,
                "status": "supported",
                "reason": "The time range is a true setup fact.",
            }
        ]
    }
    if decision != "missing":
        feedback["method_operation_decisions"] = [
            {
                "source_url": artifact.source.url,
                "operation_claim_id": "c3",
                "status": decision,
                "reason": "Offline control of the proposed operation role.",
            }
        ]
    verifier = Composer(feedback)
    result = review_publication_facts(
        [claim], verifier, model="offline", readings=[reading], artifacts=[artifact]
    )
    context = json.loads(
        verifier.requests[0][-1].content.split("FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n")[1]
    )
    proposal = context["method_flow_proposals"][0]
    assert proposal["operations"] == [operation]
    assert proposal["supporting_claims"] == [
        {"claim_id": "c3", "claim_index": 1, "text": claim.text, "status": "supported"}
    ]
    assert result.claims[0].is_publishable()  # True fact does not license a method role.
    if decision == "supported":
        # This deliberately wrong semantic control documents the remaining model-risk boundary.
        assert reviewed_method_flow(
            result.readings[0].method_flow, result.claims, source_url=artifact.source.url
        )["operations"] == [operation]
    else:
        writer = Composer({})
        localized = localize_report_content(
            readings=result.readings,
            claims=result.claims,
            sources=[],
            provider=writer,
            model="offline",
            language="zh",
            verified_facts=True,
        )
        assert localization_failed(localized)
        assert writer.requests == []


def test_resolved_math_quote_does_not_prove_its_semantic_assertion() -> None:
    artifact, original = saved_case("c14")
    claim = replace(original, text="SRS assigns a larger score to worse memory rankings.")
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"  # Provenance is not entailment.
    _, reading, _, _ = extract("memconflict")
    reading = replace(
        reading,
        source_url=artifact.source.url,
        method_flow=parse_method_flow(None, claim_ids=set()),
    )
    result = review_publication_facts(
        checked,
        Composer(
            {
                "decisions": [
                    {
                        "claim_index": 1,
                        "status": "unsupported",
                        "reason": "Offline semantic rejection of reversed rank scoring.",
                    }
                ]
            }
        ),
        model="offline",
        readings=[reading],
        artifacts=[artifact],
    )
    assert not result.claims[0].is_publishable()
