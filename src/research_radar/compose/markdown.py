"""Markdown article composition."""

from __future__ import annotations

from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.compose.source_display import source_descriptor
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
        elif _section_kind(section) == "deep_reads":
            deep_lines = _deep_read_lines(section.metadata.get("deep_reads", []), language=language)
            if deep_lines:
                lines.extend(deep_lines)
            elif section.body:
                lines.append(section.body)
        elif _section_kind(section) == "seen_before":
            seen_lines = _seen_source_lines(section.metadata.get("sources", []))
            if seen_lines:
                lines.extend(seen_lines)
            elif section.body:
                lines.append(section.body)
        elif _section_kind(section) == "evidence_trail":
            lines.append(section.body)
        elif _section_kind(section) in {"evidence_notes", "references"}:
            lines.append(section.body)
        elif _section_kind(section) == "today_summary":
            lines.extend(section.body.splitlines())
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
            descriptor = source_descriptor(item, language=language)
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


def _deep_read_lines(raw_deep_reads: object, *, language: str) -> list[str]:
    if not isinstance(raw_deep_reads, list):
        return []
    labels = _deep_read_labels(language)
    lines: list[str] = []
    for entry in raw_deep_reads:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or labels["untitled"])
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        url = str(source.get("url") or "") if isinstance(source, dict) else ""
        lines.extend([f"### [{title}](<{url}>)" if url else f"### {title}", ""])
        has_explanation = _append_reader_explanation(
            lines,
            entry.get("reader_explanation"),
            labels,
        )
        if not has_explanation:
            _append_text(lines, labels["essence"], entry.get("essence"))
        _append_figures(lines, labels["figures"], entry.get("figures"))
        if not has_explanation:
            _append_nested(
                lines,
                labels["problem"],
                entry.get("problem"),
                ["core", "why_it_matters"],
            )
            _append_nested(lines, labels["solution"], entry.get("solution"), ["core", "mechanism"])
            _append_nested(lines, labels["experiments"], entry.get("experiments"), ["summary"])
            _append_nested(
                lines,
                labels["related_work"],
                entry.get("related_work"),
                ["novelty", "prior_work", "repackaging_risk"],
            )
            _append_nested(
                lines,
                labels["limitations"],
                entry.get("limitations"),
                ["explicit_limitations", "inferred_weaknesses", "future_work"],
            )
            _append_nested(
                lines,
                labels["critical"],
                entry.get("critical_assessment"),
                ["bottom_line", "overclaiming_risk", "weak_evaluations", "missing_ablations"],
            )
            _append_text(lines, labels["plain_example"], entry.get("plain_language_example"))
        claims = entry.get("claims")
        if isinstance(claims, list) and claims:
            lines.extend([f"#### {labels['key_evidence']}", ""])
            for claim in claims[:8]:
                if isinstance(claim, dict) and claim.get("text"):
                    lines.append(f"- {claim['text']}")
            lines.append("")
    return lines


def _append_reader_explanation(
    lines: list[str],
    value: object,
    labels: dict[str, str],
) -> bool:
    if not isinstance(value, dict):
        return False
    sections = [
        ("opening_context", labels["opening_context"]),
        ("core_thesis", labels["core_thesis"]),
        ("problem_walkthrough", labels["problem"]),
        ("solution_walkthrough", labels["solution"]),
        ("experiment_interpretation", labels["experiments"]),
        ("related_work_context", labels["related_work"]),
        ("limitations_discussion", labels["limitations"]),
        ("plain_language_story", labels["plain_example"]),
        ("reader_takeaway", labels["reader_takeaway"]),
    ]
    appended = False
    for key, label in sections:
        text = str(value.get(key) or "").strip()
        if not text:
            continue
        _append_text(lines, label, text)
        appended = True
    return appended


def _seen_source_lines(raw_sources: object) -> list[str]:
    if not isinstance(raw_sources, list):
        return []
    lines = []
    for item in raw_sources[:12]:
        if not isinstance(item, dict):
            continue
        title = _escape_markdown_text(str(item.get("title", "Untitled source")))
        url = str(item.get("url", ""))
        version = str(item.get("version") or "")
        suffix = f" ({version})" if version else ""
        note = _seen_source_note(item)
        lines.append(f"- [{title}](<{url}>){suffix}{note}")
    return lines


def _seen_source_note(item: dict[str, object]) -> str:
    created_at = str(item.get("wechat_created_at") or "").strip()
    wechat_title = _escape_markdown_text(str(item.get("wechat_title") or "").strip())
    if not created_at and not wechat_title:
        return ""
    pieces = []
    if created_at:
        pieces.append(f"previous draft: {created_at[:10]}")
    if wechat_title:
        pieces.append(wechat_title)
    return " · " + " · ".join(pieces)


def _append_figures(lines: list[str], label: str, value: object) -> None:
    if not isinstance(value, list) or not value:
        return
    lines.extend([f"#### {label}", ""])
    for figure in value[:3]:
        if not isinstance(figure, dict):
            continue
        title = str(figure.get("title") or "Paper figure")
        caption = str(figure.get("caption") or "")
        path = str(figure.get("relative_path") or figure.get("asset_path") or "")
        reuse_status = str(figure.get("reuse_status") or "needs_manual_review")
        lines.append(f"- {title}: {caption}")
        if path:
            lines.append(f"  - image: {path}")
        lines.append(f"  - reuse_status: {reuse_status}")
    lines.append("")


def _append_text(lines: list[str], label: str, value: object) -> None:
    text = str(value or "").strip()
    if text:
        lines.extend([f"#### {label}", "", text, ""])


def _append_nested(lines: list[str], label: str, value: object, keys: list[str]) -> None:
    if not isinstance(value, dict):
        return
    content: list[str] = []
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, list):
            content.extend(f"- {item}" for item in raw if str(item).strip())
        elif raw:
            content.append(str(raw))
    if content:
        lines.extend([f"#### {label}", "", *content, ""])


def _deep_read_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "untitled": "未命名论文",
            "essence": "本质判断",
            "problem": "问题与动机",
            "solution": "方法与机制",
            "experiments": "实验与评估",
            "related_work": "相关工作",
            "limitations": "局限与未来工作",
            "critical": "中立批判",
            "plain_example": "通俗例子",
            "opening_context": "背景知识速读",
            "core_thesis": "核心判断",
            "reader_takeaway": "读者 takeaway",
            "key_evidence": "关键证据",
            "figures": "论文关键图",
        }
    return {
        "untitled": "Untitled paper",
        "essence": "Essence",
        "problem": "Problem and Motivation",
        "solution": "Solution Mechanism",
        "experiments": "Experiments",
        "related_work": "Related Work",
        "limitations": "Limitations and Future Work",
        "critical": "Critical Assessment",
        "plain_example": "Plain-language Example",
        "opening_context": "Opening Context",
        "core_thesis": "Core Thesis",
        "reader_takeaway": "Reader Takeaway",
        "key_evidence": "Key Evidence",
        "figures": "Key Figures",
    }


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


def _escape_markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
