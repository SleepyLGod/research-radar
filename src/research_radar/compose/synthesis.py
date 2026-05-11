"""Outline-first synthesis helpers."""

from __future__ import annotations

from research_radar.analysis.paper_reading import PaperReading
from research_radar.evidence.policy import publishable_claims
from research_radar.models import Claim, SourceCandidate


def render_synthesis_outline(
    topic_id: str,
    sources: list[SourceCandidate],
    claims: list[Claim],
    readings: list[PaperReading],
) -> str:
    """Render an audit-friendly synthesis outline before article drafting."""

    verified = publishable_claims(claims)
    lines = [
        "# Synthesis Outline",
        "",
        f"- Topic: `{topic_id}`",
        f"- Verified claim count: {len(verified)}",
        f"- Deep reading count: {len(readings)}",
        "",
        "## Perspective Questions",
        "",
        "- Researcher: what is the real problem and why is the evidence sufficient?",
        "- Builder: what implementation evidence exists, and what is still untested?",
        "- Evaluator: which benchmarks, baselines, and ablations support the claims?",
        "- Skeptic: which attractive claims are unsupported or overclaimed?",
        "",
        "## Source Basis",
        "",
    ]
    if sources:
        for source in sources[:8]:
            role = source.metadata.get("source_role", {}).get("role", "unknown")
            relevance = source.metadata.get("relevance", {}).get("score", "unknown")
            quality = source.metadata.get("source_quality", {}).get("score", "unknown")
            lines.append(f"- {source.title} ({role}, relevance={relevance}, quality={quality})")
    else:
        lines.append("- No relevant sources passed the gate.")

    lines.extend(["", "## Claim-Led Outline", ""])
    if not verified:
        lines.append("- No claim passed evidence verification; do not draft an article.")
    else:
        for index, claim in enumerate(verified, start=1):
            anchor_count = len(claim.evidence)
            lines.append(f"{index}. {claim.text} ({anchor_count} evidence anchor(s))")

    lines.extend(["", "## Deep Reading Essence", ""])
    if readings:
        for reading in readings:
            lines.append(f"- {reading.title}: {reading.essence}")
    else:
        lines.append("- No deep reading was produced.")

    lines.extend(
        [
            "",
            "## Draft Boundary",
            "",
            "Only supported claims with evidence anchors can enter publishable output. "
            "Speculation, weak critique, and source-selection doubts stay in review artifacts.",
        ]
    )
    return "\n".join(lines).strip() + "\n"
