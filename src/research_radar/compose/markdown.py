"""Markdown article composition."""

from __future__ import annotations

from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.models import ArticleDraft, Claim, SourceCandidate


def render_markdown(draft: ArticleDraft) -> str:
    """Render a platform-neutral draft as Markdown."""

    lines = [f"# {draft.title}", "", draft.lede, ""]
    for section in draft.sections:
        lines.extend([f"## {section.title}", ""])
        if section.title.lower().startswith("high-signal"):
            for line in section.body.splitlines():
                if ": http" in line:
                    title, rest = line.split(": ", 1)
                    url, _, summary = rest.partition(" - ")
                    lines.append(f"- [{title}]({url})")
                    if summary:
                        lines.append(f"  - {summary}")
                elif line:
                    lines.append(f"- {line}")
        elif section.title.lower().startswith("evidence"):
            lines.append(section.body)
        else:
            for line in section.body.splitlines():
                lines.append(f"- {line}" if line else "")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def compose_daily_markdown(
    topic_id: str,
    sources: list[SourceCandidate],
    claims: list[Claim],
) -> str:
    """Compose a daily monitoring report."""

    return render_markdown(build_daily_draft(topic_id, sources, claims))


def compose_weekly_markdown(topic_id: str, claims: list[Claim]) -> str:
    """Compose a weekly deep-dive draft."""

    return render_markdown(build_weekly_draft(topic_id, claims))
