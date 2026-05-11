"""Markdown rendering for a single-paper research brief."""

from __future__ import annotations

from research_radar.analysis.paper_reading import PaperReading
from research_radar.evidence.policy import publishable_claims
from research_radar.models import Claim


def render_paper_brief(reading: PaperReading, claims: list[Claim]) -> str:
    """Render a conservative, evidence-backed paper brief."""

    verified = publishable_claims(claims)
    lines = [
        f"# ResearchRadar Paper Brief: {reading.title}",
        "",
        "## Essence",
        _claim_body(verified, "Essence:") or "No verified essence claim.",
        "",
        "## Background",
        reading.area_context.background,
        "",
        "## Problem",
        _claim_body(verified, "Problem:") or "No verified problem claim.",
        "",
        "## Solution",
        _claim_body(verified, "Solution:") or "No verified solution claim.",
        "",
        "## Experiment",
        _claim_body(verified, "Experiment:") or "No verified experiment claim.",
        "",
        "## Related Work",
        _claim_body(verified, "Related work:") or "No verified related-work claim.",
        "",
        "## Limitations",
        _claim_body(verified, "Limitations:") or "No verified limitation claim.",
        "",
        "## Critique",
        _claim_body(verified, "Critical assessment:") or "No verified critique claim.",
        "",
        "## Evidence Trail",
        _evidence_trail(verified),
    ]
    return "\n".join(lines).strip() + "\n"


def _claim_body(claims: list[Claim], prefix: str) -> str:
    for claim in claims:
        if claim.text.startswith(prefix):
            return claim.text[len(prefix) :].strip()
    return ""


def _evidence_trail(claims: list[Claim]) -> str:
    if not claims:
        return "No publishable claims passed evidence validation."
    blocks = []
    for claim in claims:
        anchors = []
        for anchor in claim.evidence:
            location = f" ({anchor.location})" if anchor.location else ""
            source = anchor.source_title or anchor.source_url
            anchors.append(f"- {source}{location}: {anchor.quote}")
        blocks.append(f"{claim.text}\n" + "\n".join(anchors))
    return "\n\n".join(blocks)
