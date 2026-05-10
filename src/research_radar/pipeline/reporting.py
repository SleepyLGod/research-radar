"""Pipeline report rendering."""

from __future__ import annotations

from research_radar.models import ReviewFinding


def render_review_report(
    findings: list[ReviewFinding],
    *,
    model_feedback: str | None = None,
) -> str:
    """Render review findings as Markdown."""

    lines = ["# Review Report", ""]
    if not findings and not model_feedback:
        lines.append("No review findings.")
    for finding in findings:
        target = f" ({finding.claim_text})" if finding.claim_text else ""
        lines.append(f"- **{finding.severity}**{target}: {finding.message}")
    if model_feedback:
        lines.extend(["", "## Model Feedback", "", model_feedback.strip()])
    return "\n".join(lines).strip() + "\n"
