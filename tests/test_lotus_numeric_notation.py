"""Saved LOTUS notation can reach review without becoming a semantic approval."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.method_flow import MethodFlow, MethodOperation, reviewed_method_flow
from research_radar.analysis.review import fact_is_reviewed
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

SAVED = json.loads((Path(__file__).parent / "fixtures/lotus_numeric_notation.json").read_text())


def source_and_claim(text: str, quotes: list[str]) -> tuple[Artifact, Claim]:
    """Bind explicit same-paper quotes, without generated context or decisions."""
    artifact = Artifact(SourceCandidate("LOTUS v3", SAVED["source_url"], SourceType.PAPER,
                                        "offline"), "\n\n".join(quotes))
    claim = Claim(text, ClaimStatus.SUPPORTED, evidence=[
        EvidenceAnchor(artifact.source.url, quote) for quote in quotes])
    return artifact, claim


@pytest.mark.parametrize("identity", ["c32", "c48"])
def test_saved_quantities_reach_local_review_without_changing_source(identity: str) -> None:
    saved = SAVED["cases"][identity]
    artifact, claim = source_and_claim(saved["text"], [saved["quote"]])

    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)

    assert resolutions[0].status == "matched"
    assert checked[0].text == claim.text
    assert checked[0].evidence == claim.evidence
    assert not fact_is_reviewed(checked[0])


def test_saved_metric_cutoffs_need_both_literal_notation_and_explicit_topic_context() -> None:
    saved = SAVED["cases"]["c35"]
    artifact, claim = source_and_claim(saved["text"], [saved["quote"]])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].reason == "anchor missing key entities: BioDEX"
    assert not checked[0].is_publishable()

    # This editorial control supplies another real quote explicitly, not by inference.
    artifact, claim = source_and_claim(saved["text"], [
        saved["quote"], SAVED["cases"]["c32"]["quote"]])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("source", ["65, 000", "65,\t000", "65,000", "65000"])
def test_same_grouped_integer_has_one_value(source: str) -> None:
    artifact, claim = source_and_claim("The corpus contains 65000 articles.", [
        f"The corpus contains {source} articles."])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("source", ["65, 00", "65, 0001", "65 000", "65,\n000", "65, 001"])
def test_grouping_does_not_merge_malformed_or_different_values(source: str) -> None:
    artifact, claim = source_and_claim("The corpus contains 65000 articles.", [
        f"The corpus contains {source} articles."])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("source", ["16 - 32%", "16\u221232%", "16 to 32%", "16% to 32%"])
def test_percent_range_retains_the_shared_endpoint_unit(source: str) -> None:
    artifact, claim = source_and_claim("Time is reduced by 16% to 32%.", [
        f"Time is reduced by {source}."])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("source", ["16 and 32%", "16 pp to 32%", "16 to 33%", "16 to 32 pp"])
def test_percent_units_are_not_borrowed_from_lists_or_other_units(source: str) -> None:
    artifact, claim = source_and_claim("Time is reduced by 16% to 32%.", [
        f"Time is reduced by {source}."])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("text,quote", [
    ("The metric is rank-precision at 5.", "The metric is rank-precision@5."),
    ("The metric is rank-precision@5.", "The metric is rank-precision at 5."),
    ("The metric is rank-precision at 5.", "The metric is rank-precision at 5."),
])
def test_metric_cutoff_notation_preserves_the_same_name_and_index(text: str, quote: str) -> None:
    artifact, claim = source_and_claim(text, [quote])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("text,quote", [
    ("The metric is rank-precision at 10.", "The metric is rank-precision@5."),
    ("The metric is rank-precision@10.", "The metric is rank-precision@5."),
    ("The metric is rank-precision@5.", "The metric is recall@5."),
    ("The observed score is 5.", "The metric is rank-precision@5."),
])
def test_metric_indices_cannot_support_other_indices_names_or_measured_values(
    text: str, quote: str,
) -> None:
    artifact, claim = source_and_claim(text, [quote])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


def test_saved_incomplete_method_is_not_promoted_or_relabelled_false() -> None:
    saved = SAVED["cases"]["c8"]
    artifact, claim = source_and_claim(saved["text"], [saved["quote"]])
    claim = replace(claim, status=ClaimStatus(saved["review_status"]), metadata={
        "paper_reading": {"claim_id": "c8"},
        "fact_review": {"status": saved["review_status"], "reason": saved["review_reason"]},
    })
    checked, _, _ = apply_anchor_resolution([claim], artifact)

    assert checked[0].status == ClaimStatus.NEEDS_REVIEW
    assert checked[0].text == saved["text"]
    assert checked[0].evidence == claim.evidence
    assert checked[0].metadata["fact_review"] == claim.metadata["fact_review"]
    flow = MethodFlow(operations=[MethodOperation("Apply the filter", "c8", [], [], [])])
    with pytest.raises(AnalysisError, match="unavailable factual step"):
        reviewed_method_flow(flow, checked, source_url=artifact.source.url)
