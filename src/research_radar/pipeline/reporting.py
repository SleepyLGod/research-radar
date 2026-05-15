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
    groups = _group_findings(findings)
    rendered_sections = []
    for title, section_findings in groups:
        if not section_findings:
            continue
        rendered_sections.append(title)
        lines.extend([f"## {title}", ""])
        for finding in section_findings:
            target = f" ({finding.claim_text})" if finding.claim_text else ""
            lines.append(f"- **{finding.severity}**{target}: {finding.message}")
        lines.append("")
    if model_feedback:
        heading = (
            "### Raw Model Feedback"
            if "Model Review" in rendered_sections
            else "## Model Review"
        )
        lines.extend([heading, "", model_feedback.strip()])
    return "\n".join(lines).strip() + "\n"


def _group_findings(
    findings: list[ReviewFinding],
) -> list[tuple[str, list[ReviewFinding]]]:
    groups = {
        "Evidence Issues": [],
        "Needs Review": [],
        "Filtered Candidates": [],
        "Deep Selection": [],
        "Model Review": [],
    }
    for finding in findings:
        groups[_section_for(finding)].append(finding)
    return [(title, groups[title]) for title in groups]


def _section_for(finding: ReviewFinding) -> str:
    kind = str(finding.metadata.get("kind", ""))
    if kind.startswith("model_review"):
        return "Model Review"
    if kind == "deep_source_selection":
        return "Deep Selection"
    if kind == "daily_report_gate":
        return "Filtered Candidates"
    if kind == "source_relevance":
        if finding.metadata.get("source_status") == "needs_review":
            return "Needs Review"
        return "Filtered Candidates"
    if "evidence" in kind or finding.severity == "error":
        return "Evidence Issues"
    if finding.severity == "warning":
        return "Needs Review"
    return "Filtered Candidates"
