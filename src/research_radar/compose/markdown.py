"""Markdown article composition."""

from __future__ import annotations

from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, Claim, SourceCandidate


def render_markdown(draft: ArticleDraft) -> str:
    """Render a platform-neutral draft as Markdown."""

    language = str(draft.metadata.get("language", "en"))
    lines = [f"# {draft.title}", "", draft.lede, ""]
    for section in draft.sections:
        lines.extend([f"## {section.title}", ""])
        if _section_kind(section) == "new_updated_sources":
            source_lines = _source_lines(section.metadata.get("sources", []), language=language)
            if source_lines:
                lines.extend(source_lines)
            elif section.body:
                lines.append(section.body)
        elif _section_kind(section) == "evidence_trail":
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
    *,
    language: str = "en",
) -> str:
    """Compose a daily monitoring report."""

    return render_markdown(build_daily_draft(topic_id, sources, claims, language=language))


def compose_weekly_markdown(topic_id: str, claims: list[Claim]) -> str:
    """Compose a weekly deep-dive draft."""

    return render_markdown(build_weekly_draft(topic_id, claims))


def _source_lines(raw_sources: object, *, language: str) -> list[str]:
    if not isinstance(raw_sources, list):
        return []
    lines: list[str] = []
    for group, items in group_source_entries(raw_sources):
        if not items:
            continue
        lines.extend([f"### {source_group_label(group, language=language)}", ""])
        for item in items:
            title = _escape_markdown_text(str(item.get("title", "Untitled source")))
            url = str(item.get("url", ""))
            descriptor = _source_descriptor(item)
            gist = str(item.get("gist") or "").strip()
            lines.append(f"- [{title}](<{url}>)")
            if descriptor:
                lines.append(f"  - {descriptor}")
            if gist:
                label = "摘要" if language == "zh" else "Gist"
                lines.append(f"  - {label}: {gist}")
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _section_kind(section: object) -> str:
    metadata = getattr(section, "metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get("kind"), str):
        return str(metadata["kind"])
    title = str(getattr(section, "title", "")).lower()
    if title.startswith("new / updated"):
        return "new_updated_sources"
    if title.startswith("evidence"):
        return "evidence_trail"
    return ""


def _source_descriptor(item: dict[object, object]) -> str:
    parts = []
    role = item.get("role")
    history_status = item.get("history_status")
    published_at = item.get("published_at")
    version = item.get("version")
    if role:
        parts.append(f"role={role}")
    if history_status:
        parts.append(f"status={history_status}")
    if published_at:
        parts.append(f"published={published_at}")
    if version:
        parts.append(f"version={version}")
    return ", ".join(str(part) for part in parts)


def _escape_markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
