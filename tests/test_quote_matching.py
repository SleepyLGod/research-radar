"""Quote matching must tolerate extraction noise without changing numeric evidence."""

from dataclasses import replace

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_resolution, resolve_quote
from research_radar.analysis.paper_reading import (
    ClaimUnit,
    heuristic_paper_reading,
    validate_paper_reading,
)
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.wechat import render_wechat_html
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)


def _artifact(text: str) -> Artifact:
    return Artifact(
        source=SourceCandidate(
            title="Offline paper",
            url="https://example.com/paper",
            source_type=SourceType.PAPER,
            source_name="offline",
        ),
        text=text,
    )


@pytest.mark.parametrize(
    ("quote", "actual"),
    [
        ("Accuracy improved by 10.0%.", "Accuracy improved by 100%."),
        ("The measured change is -5%.", "The measured change is +5%."),
        ("Accuracy improved by 10% on the task.", "Accuracy improved by 10 on the task."),
        ("The reported ratio is 1:2.", "The reported ratio is 12."),
        ("Accuracy improved by 100%.", "Accuracy improved by 1 00%."),
    ],
)
def test_reader_and_anchor_resolution_reject_altered_numeric_quotes(
    quote: str,
    actual: str,
) -> None:
    artifact = _artifact(f"[page 1]\n{actual}")
    anchor = EvidenceAnchor(source_url=artifact.source.url, quote=quote)
    text = "The authors report improved accuracy."
    claim = Claim(text=text, status=ClaimStatus.SUPPORTED, evidence=[anchor])
    reading = replace(
        heuristic_paper_reading(artifact),
        claim_units=[
            ClaimUnit(
                section="experiment",
                claim_kind="fact",
                text=text,
                evidence=[anchor],
                claim_id="c1",
            )
        ],
    )

    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    reader_claims, _ = validate_paper_reading(reading, artifact)
    draft = build_daily_draft(
        "offline",
        [artifact.source],
        reader_claims,
        readings=[reading],
        deep_read_sources=[artifact.source],
    )

    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()
    assert not reader_claims[0].is_publishable()
    assert quote not in render_wechat_html(draft)


@pytest.mark.parametrize(
    "padding",
    [
        "Background      text without result values.\n" * 40,
        "Straße\t\tbackground information.\n" * 40,
    ],
)
def test_normalized_quote_uses_original_page_and_numeric_context(padding: str) -> None:
    artifact = _artifact(f" \t\n[page 1]\n{padding}[page 2]\nAccuracy  is 70.0% on this task.")
    quote = "ACCURACY IS 70.0%"
    claim = Claim(
        text="Experiment: The authors report accuracy of 70.0%.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=artifact.source.url, quote=quote)],
    )

    checked, resolutions, findings = apply_anchor_resolution([claim], artifact)

    assert resolutions[0].status == "matched"
    assert resolutions[0].page == 2
    assert resolutions[0].location == "page 2"
    assert "Accuracy  is 70.0%" in resolutions[0].resolved_quote
    assert checked[0].is_publishable()
    assert not findings


@pytest.mark.parametrize(
    ("quote", "text"),
    [
        ("The memory framework has four stages.", "The (memory) framework has four stages."),
        ("Memory selection uses retrieval.", "Memory-selection uses retrieval."),
        ("The framework decomposes memory.", "The framework decom-\nposes memory."),
        ("STRASSE supports retrieval.", "Straße supports retrieval."),
    ],
)
def test_cosmetic_pdf_noise_still_matches(quote: str, text: str) -> None:
    resolution = resolve_quote(quote, _artifact(f"[page 3]\n{text}"))

    assert resolution.status == "matched"
    assert resolution.page == 3
    assert text in resolution.resolved_quote
