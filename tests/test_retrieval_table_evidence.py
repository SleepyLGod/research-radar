"""Saved retrieval notation and literal multi-line table headers stay reviewable."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_resolution, resolve_quote
from research_radar.analysis.review import apply_model_review_decisions, fact_is_reviewed
from research_radar.evidence.tables import table_source_context
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

SAVED = json.loads(
    (Path(__file__).parent / "fixtures/method_flow/retrieval_table_evidence.json").read_text()
)


def source_and_claim(
    text: str, quotes: list[str], source: str | None = None,
) -> tuple[Artifact, Claim]:
    """Use public source text without repairing quotations or adding review decisions."""
    artifact = Artifact(
        SourceCandidate("MemConflict", SAVED["source_url"], SourceType.PAPER, "offline"),
        source if source is not None else "\n\n".join(quotes),
    )
    claim = Claim(text, ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(artifact.source.url, quote) for quote in quotes])
    return artifact, claim


def test_saved_retrieval_set_reaches_review_without_receiving_approval() -> None:
    artifact, claim = source_and_claim(**SAVED["retrieval"])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert checked[0].text == claim.text and checked[0].evidence == claim.evidence
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize(("value", "eligible"), [("3", True), ("2", False)])
def test_single_main_assignment_is_not_invalidated_by_additional_sensitivity_set(
    value: str, eligible: bool,
) -> None:
    artifact, claim = source_and_claim(**SAVED["retrieval"])
    claim = replace(claim, text=f"The main white-box evaluation uses K={value}.")
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].is_publishable() is eligible
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("notation", [
    "𝐾∈ {2,5}", "K ∈ { 5, 2 }", "K={2, 5}", "with𝐾∈{2,5}",
])
def test_explicit_retrieval_sets_match_the_same_enumerated_values(notation: str) -> None:
    quote = f"White-box retrieval uses K=3; retrieval sensitivity uses {notation}."
    artifact, claim = source_and_claim(
        "White-box retrieval uses K=3, with K=2 and K=5 in sensitivity analysis.", [quote]
    )
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("notation", [
    "K∈{2,4}", "K∈{2,5,7}", "K∈{2}", "N∈{2,5}",
    "K∈[2,5]", "K∈{2,...,5}", "K∈{2,5.5}", "K∈{2,5", "K∈{2,0}",
    "Model-K2 and Model-K5", "2 queries and 5 trials", "K∉{2,5}",
])
def test_retrieval_sets_do_not_borrow_values_or_expand_unproved_ranges(notation: str) -> None:
    quote = f"White-box retrieval uses K=3; sensitivity setup: {notation}."
    artifact, claim = source_and_claim(
        "White-box retrieval uses K=3, with K=2 and K=5 in sensitivity analysis.", [quote]
    )
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


def test_same_values_do_not_override_a_verifiers_default_role_rejection() -> None:
    artifact, original = source_and_claim(**SAVED["retrieval"])
    wrong = replace(original, text=(
        "The default white-box retrieval depth is K=2, with K=3 and K=5 in sensitivity analysis."
    ))
    checked, _, _ = apply_anchor_resolution([wrong], artifact)
    # Numeric presence is not a semantic approval of default versus sensitivity roles.
    assert not fact_is_reviewed(checked[0])
    reviewed, _ = apply_model_review_decisions(checked, json.dumps({"decisions": [{
        "claim_index": 1, "status": "unsupported",
        "reason": "Default and sensitivity roles are swapped; the main setting is K=3.",
    }]}))
    assert not reviewed[0].is_publishable()


@pytest.mark.parametrize("saved", SAVED["table"]["claims"], ids=lambda c: c["claim_id"])
def test_saved_multiline_headers_do_not_turn_metric_names_into_systems(saved: dict) -> None:
    artifact, claim = source_and_claim(saved["text"], saved["quotes"], SAVED["table"]["text"])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])
    context = resolve_quote(saved["quotes"][1], artifact).table
    assert context is not None and context["columns"] == []
    assert "SEH@3 SRS SEH@3 SRS SEH@3 SRS SEH@3 SRS" in context["headers"]
    assert all(
        artifact.text[s["start"]:s["end"]] == s["text"] for s in context["segments"]
    )


@pytest.mark.parametrize("text", [
    "OtherSystem has SRS of 0.5879.", "MemOS has SRS of 0.9879.",
])
def test_multiline_headers_preserve_entity_and_value_rejections(text: str) -> None:
    saved = SAVED["table"]["claims"][1]
    artifact, claim = source_and_claim(text, saved["quotes"], SAVED["table"]["text"])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()


def test_multiline_header_roles_come_from_source_not_a_metric_name_allowlist() -> None:
    row = "MemOS 0.80 0.59"
    source = "Table 4. Evaluation.\nMemory\nSystem\nMacro\nAverage\nZZZ YYY\n" + row
    artifact, claim = source_and_claim("MemOS reports ZZZ of 0.80.", [row], source)
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("boundary", ["[page 2]", "4 Results", "Table 5. Other results.", ""])
def test_multiline_header_search_does_not_borrow_earlier_table_metrics(boundary: str) -> None:
    row = "MemOS 0.80 0.59"
    source = f"Table 4. Earlier evaluation.\nMemory\nSystem\nZZZ YYY\n{boundary}\n{row}"
    artifact, claim = source_and_claim("MemOS reports ZZZ of 0.80.", [row], source)
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()


def test_multiline_header_search_keeps_its_character_budget() -> None:
    row = "MemOS 0.80 0.59"
    source = "Table 4. Evaluation.\n" + "Memory\n" * 200 + "ZZZ YYY\n" + row
    start = source.index(row)
    context = table_source_context(source, start, start + len(row))
    assert context is not None and context["segments"] == []
    assert context["headers"] == [] and context["columns"] == []
    artifact, claim = source_and_claim("MemOS reports ZZZ of 0.80.", [row], source)
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("value", ["0.4375", "0.8449"])
def test_glued_table_cells_are_not_split_to_recover_a_claim_value(value: str) -> None:
    row = "MemOS 0.37930.3818 0.43750.23610.8449 0.5539"
    source = "Table 3. Evaluation.\nMemory System Dynamic Static Conditional Average\n" + row
    artifact, claim = source_and_claim(f"MemOS reports {value}.", [row], source)
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].reason == "numeric anchor missing claim values"
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("identifier", [
    "rec𝐾=2 and rec𝐾=5", "rec𝐾∈{2,5}", "model𝐾∈{2,5}",
])
def test_glued_mathematical_letter_does_not_split_record_or_model_identifiers(
    identifier: str,
) -> None:
    quote = f"White-box retrieval returns identifiers {identifier}."
    artifact, claim = source_and_claim("White-box retrieval uses K=2 and K=5.", [quote])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("name", ["Figure 1", "Fig. 1"])
def test_table_headers_cannot_capture_a_distant_figure_title(name: str) -> None:
    row = "MemGuide 0.80 3.19"
    source = (
        f"{name}: WrongSystem performance across tasks\nLegend\nPrimary\nSecondary\n"
        f"Tertiary\nMethod JGA DTE\n{row}\nTable 2: Actual table."
    )
    artifact, claim = source_and_claim("WrongSystem reports JGA of 0.80.", [row], source)
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("notation", ["K∈{2,500}", "K∈{2, 500}", "K={500,2}"])
def test_set_delimiters_are_not_thousands_separators(notation: str) -> None:
    quote = f"White-box retrieval settings: {notation}."
    artifact, claim = source_and_claim("White-box retrieval uses K=2 and K=500.", [quote])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])


def test_nonset_thousands_separators_keep_their_numeric_meaning() -> None:
    quote = "White-box retrieval uses K=2 for 2,500 queries."
    artifact, claim = source_and_claim(
        "White-box retrieval uses K=2 for 2500 queries.", [quote]
    )
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "matched"
    assert not fact_is_reviewed(checked[0])
