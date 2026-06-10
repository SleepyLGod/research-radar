"""WeChat Official Account HTML composition."""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape, unescape

from research_radar.analysis.figure_text import (
    FIGURE_EXPLANATION_CAPTION_ALIGNMENT_PREFIX,
    FIGURE_EXPLANATION_SOURCE_CONTEXT,
)
from research_radar.compose.draft import build_weekly_draft
from research_radar.compose.source_display import source_descriptor
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, ArticleSection, Claim

FORMULA_STYLE = (
    "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
    "font-size:0.95em;background:#f8fafc;border:1px solid #e2e8f0;"
    "border-radius:4px;padding:1px 4px;white-space:nowrap;"
)
PUBLISH_ROOT_STYLE = (
    "font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif;"
    "color:#1f2933;line-height:1.75;font-size:16px;margin:0 auto;padding:24px 14px;"
    "text-align:left;"
)
PUBLISH_UNSUPPORTED_TAGS = {
    "a",
    "article",
    "blockquote",
    "code",
    "details",
    "div",
    "figcaption",
    "figure",
    "iframe",
    "li",
    "ol",
    "script",
    "style",
    "summary",
    "table",
    "ul",
    "video",
}


def render_wechat_html(
    draft: ArticleDraft,
    *,
    publish_mode: bool = False,
    media_url_map: Mapping[str, str] | None = None,
) -> str:
    """Render a platform-neutral draft as WeChat-compatible HTML."""

    language = str(draft.metadata.get("language", "en"))
    long_form = draft.metadata.get("draft_type") == "daily_long_form"
    body = [
        _section(
            "section",
            f"""
            <h1>{escape(draft.title)}</h1>
            <p class="lede">{escape(_display_lede(draft.lede))}</p>
            """,
            class_name="rr-hero",
        )
    ]
    if long_form:
        body.append(_table_of_contents(draft, language=language))
    for index, section in enumerate(draft.sections, start=1):
        kind = _section_kind(section)
        if kind == "evidence_trail":
            content = "".join(_evidence_block(claim, language=language) for claim in section.claims)
        elif kind in {"references", "evidence_notes"}:
            content = _references(section.claims, section.metadata, language=language)
        elif kind == "deep_reads":
            content = _deep_reads(
                section.metadata.get("deep_reads", []),
                language=language,
                publish_mode=publish_mode,
                media_url_map=media_url_map,
            )
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        elif kind in {"new_updated_sources", "other_sources"}:
            content = _source_list(section.metadata.get("sources", []), language=language)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        elif kind == "seen_before":
            content = _seen_source_list(section.metadata.get("sources", []), language=language)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        elif kind == "today_summary":
            content = _today_summary(draft, section.body, language=language)
        else:
            content = "".join(_claim_card(claim, language=language) for claim in section.claims)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        body.append(
            _section(
                "section",
                f"<h2>{escape(section.title)}</h2>{content}",
                section_id=f"rr-section-{index}" if long_form else None,
                class_name="rr-section",
            )
        )
    return _html_shell("".join(body))


def compose_wechat_html(topic_id: str, claims: list[Claim]) -> str:
    """Compose a WeChat-compatible article body."""

    return render_wechat_html(build_weekly_draft(topic_id, claims))


def render_wechat_publish_html(
    draft: ArticleDraft,
    *,
    media_url_map: Mapping[str, str] | None = None,
) -> str:
    """Render a WeChat API-safe draft body using a conservative HTML subset."""

    language = str(draft.metadata.get("language", "en"))
    parts = [
        f'<section style="{PUBLISH_ROOT_STYLE}">',
        _publish_hero(draft),
    ]
    if draft.metadata.get("draft_type") == "daily_long_form":
        parts.append(_publish_toc(draft, language=language))
    for section in draft.sections:
        kind = _section_kind(section)
        if kind == "today_summary":
            content = _publish_today_summary(draft, section.body, language=language)
        elif kind == "deep_reads":
            content = _publish_deep_reads(
                section.metadata.get("deep_reads", []),
                language=language,
                media_url_map=media_url_map,
            )
            if not content:
                content = _publish_paragraph(str(section.body or ""))
        elif kind in {"new_updated_sources", "other_sources"}:
            content = _publish_source_list(section.metadata.get("sources", []), language=language)
            if not content:
                content = _publish_paragraph(str(section.body or ""))
        elif kind == "seen_before":
            content = _publish_seen_source_list(
                section.metadata.get("sources", []),
                language=language,
            )
            if not content:
                content = _publish_paragraph(str(section.body or ""))
        elif kind in {"references", "evidence_notes"}:
            content = _publish_references(section.claims, section.metadata, language=language)
        elif kind == "evidence_trail":
            content = _publish_evidence_list(section.claims, language=language)
        else:
            content = "".join(
                _publish_claim_card(claim, language=language) for claim in section.claims
            )
            if not content:
                content = _publish_paragraph(str(section.body or ""))
        parts.append(
            _publish_section(
                _publish_section_title(str(section.title), kind, language=language),
                content,
            )
        )
    parts.append("</section>")
    return "".join(parts)


def wechat_publish_html_issues(html: str) -> list[str]:
    """Return reasons why generated HTML is unsafe for WeChat draft publishing."""

    issues: list[str] = []
    tag_pattern = re.compile(r"</?\s*([a-zA-Z][a-zA-Z0-9]*)\b")
    present_tags = {match.group(1).casefold() for match in tag_pattern.finditer(html)}
    unsupported = sorted(present_tags & PUBLISH_UNSUPPORTED_TAGS)
    if unsupported:
        issues.append(f"unsupported tags: {', '.join(unsupported)}")
    if "figures/" in html or "Figure image requires WeChat media upload" in html:
        issues.append("local figure image remains in publish HTML")
    image_pattern = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', flags=re.IGNORECASE)
    for match in image_pattern.finditer(html):
        src = match.group(1)
        if not _is_wechat_image_src(src):
            issues.append(f"non-WeChat image src: {_shorten(src, limit=80)}")
            break
    return issues


def _html_shell(body: str) -> str:
    shell_start = (
        "<section style=\"font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',"
        "Arial,sans-serif;color:#1f2933;line-height:1.75;font-size:16px;"
        "max-width:760px;margin:0 auto;padding:28px 18px;\">"
    )
    return f"""{shell_start}
<style>
.rr-card{{border-left:3px solid #dbeafe;padding:10px 0 10px 14px;
margin:12px 0;background:#ffffff;}}
.rr-tag{{display:inline-block;color:#0f766e;background:#ccfbf1;padding:2px 8px;
border-radius:999px;font-size:12px;}}
.rr-quote{{border-left:3px solid #94a3b8;padding:8px 12px;margin:10px 0;
background:#f8fafc;color:#334155;font-size:14px;}}
.rr-hero{{padding:0 0 20px;margin:0 0 18px;border-bottom:1px solid #e5e7eb;}}
.rr-section{{margin:26px 0;}}
.rr-toc{{border:1px solid #d1d5db;border-radius:8px;
padding:14px 16px;margin:20px 0;background:#fbfdfc;}}
.rr-toc ol{{margin:8px 0 0 20px;padding:0;}}
.rr-toc li{{margin:4px 0;}}
.rr-deep{{border-top:2px solid #111827;padding-top:24px;margin:30px 0 12px;}}
.rr-kicker{{font-size:13px;color:#64748b;margin:0 0 4px;}}
.rr-diagram{{display:block;border-left:3px solid #60a5fa;background:#f8fbff;
padding:12px 14px;margin:18px 0;}}
.rr-step{{display:block;margin:8px 0;padding:10px 12px;background:#ffffff;
border:1px solid #bfdbfe;border-radius:6px;}}
.rr-step strong{{display:block;color:#1e40af;margin-bottom:4px;}}
.rr-figure{{margin:20px 0;padding:14px 12px;border-top:1px solid #e5e7eb;
border-bottom:1px solid #e5e7eb;background:#fcfcfd;}}
.rr-figure img{{max-width:100%;height:auto;display:block;margin:10px auto 12px;}}
.rr-caption{{font-size:14px;color:#475569;margin:8px 0;}}
.rr-reference{{margin:14px 0;padding:10px 12px;border-top:1px solid #e5e7eb;
background:#fafafa;}}
.rr-reference summary{{cursor:pointer;color:#0f766e;font-weight:600;}}
.rr-summary{{border-left:3px solid #14b8a6;padding:8px 0 8px 14px;
margin:10px 0 4px;background:#f8fffd;}}
.rr-summary p{{margin:6px 0;}}
.lede{{font-size:18px;font-weight:600;color:#111827;margin:6px 0 18px;}}
p{{margin:10px 0;}}
h1{{font-size:28px;line-height:1.25;margin:0 0 14px;color:#111827;}}
h2{{font-size:21px;margin:26px 0 12px;padding-left:10px;border-left:4px solid #0f766e;}}
h3{{font-size:18px;margin:0 0 10px;color:#111827;}}
h4{{font-size:16px;margin:20px 0 8px;color:#0f172a;}}
a{{color:#0f766e;text-decoration:none;}}
</style>
{body}
</section>"""


def _publish_hero(draft: ArticleDraft) -> str:
    lede_style = "font-size:18px;font-weight:600;color:#111827;margin:8px 0 18px;"
    section_style = "padding:0 0 18px;margin:0 0 18px;border-bottom:1px solid #e5e7eb;"
    return (
        f'<section style="{section_style}">'
        f'<p style="{lede_style}">{escape(_display_lede(draft.lede))}</p>'
        "</section>"
    )


def _publish_toc(draft: ArticleDraft, *, language: str) -> str:
    title = "目录" if language == "zh" else "Contents"
    item_style = "margin:4px 0;color:#334155;"
    items = "".join(
        _publish_toc_item(index, section, item_style, language=language)
        for index, section in enumerate(draft.sections, start=1)
    )
    return (
        '<section style="border:1px solid #d1d5db;border-radius:8px;'
        'padding:14px 16px;margin:20px 0;background:#fbfdfc;">'
        f'<p style="margin:0 0 8px;"><strong>{title}</strong></p>{items}</section>'
    )


def _publish_toc_item(
    index: int,
    section: ArticleSection,
    item_style: str,
    *,
    language: str,
) -> str:
    title = _publish_section_title(str(section.title), _section_kind(section), language=language)
    return f'<p style="{item_style}">{index}. {escape(title)}</p>'


def _publish_section(title: str, content: str) -> str:
    if not content:
        return ""
    return (
        '<section style="margin:28px 0;">'
        f'<h2 style="font-size:21px;margin:24px 0 12px;padding-left:10px;'
        f'border-left:4px solid #0f766e;color:#111827;">{escape(title)}</h2>'
        f"{content}</section>"
    )


def _publish_section_title(title: str, kind: str, *, language: str) -> str:
    if language == "zh":
        replacements = {
            "seen_before": "历史相关来源",
            "new_updated_sources": "延伸阅读与线索",
            "other_sources": "延伸阅读与线索",
            "references": "参考资料",
            "evidence_notes": "参考资料",
        }
    else:
        replacements = {
            "seen_before": "Previously Seen Related Sources",
            "new_updated_sources": "Further Reading and Leads",
            "other_sources": "Further Reading and Leads",
            "references": "References",
            "evidence_notes": "References",
        }
    return replacements.get(kind, title)


def _publish_paragraph(text: str) -> str:
    if not text.strip():
        return ""
    return "".join(
        f'<p style="margin:10px 0;">{_publish_format_text(line.strip())}</p>'
        for line in text.splitlines()
        if line.strip()
    )


def _publish_today_summary(draft: ArticleDraft, fallback_body: str, *, language: str) -> str:
    lines = _today_summary_lines(draft, language=language)
    if not lines:
        lines = [
            _display_lede(line.strip())
            for line in fallback_body.splitlines()
            if line.strip()
        ]
    if not lines:
        return ""
    return (
        '<section style="border-left:3px solid #14b8a6;padding:8px 0 8px 14px;'
        'margin:10px 0 4px;background:#f8fffd;">'
        + "".join(f'<p style="margin:6px 0;">{_publish_format_text(line)}</p>' for line in lines)
        + "</section>"
    )


def _publish_deep_reads(
    raw_deep_reads: object,
    *,
    language: str,
    media_url_map: Mapping[str, str] | None = None,
) -> str:
    if not isinstance(raw_deep_reads, list):
        return ""
    labels = _deep_read_labels(language)
    blocks = []
    for raw_entry in raw_deep_reads:
        if not isinstance(raw_entry, dict):
            continue
        title = str(raw_entry.get("title") or labels["untitled"])
        source = raw_entry.get("source") if isinstance(raw_entry.get("source"), dict) else {}
        narrative = _publish_reader_explanation(raw_entry.get("reader_explanation"), labels)
        sections = [narrative or _publish_text_block(labels["essence"], raw_entry.get("essence"))]
        sections.append(
            _publish_figure_gallery(
                raw_entry.get("figures"),
                labels,
                media_url_map=media_url_map,
            )
        )
        if not narrative:
            sections.extend(
                [
                    _publish_problem_block(raw_entry.get("problem"), labels),
                    _publish_solution_block(raw_entry.get("solution"), labels),
                    _publish_experiments_block(raw_entry.get("experiments"), labels),
                    _publish_related_work_block(raw_entry.get("related_work"), labels),
                    _publish_limitations_block(raw_entry.get("limitations"), labels),
                    _publish_critical_block(raw_entry.get("critical_assessment"), labels),
                    _publish_text_block(
                        labels["plain_example"],
                        raw_entry.get("plain_language_example"),
                    ),
                ]
            )
        sections.append(_publish_key_evidence(raw_entry.get("claims"), labels))
        descriptor = _publish_paper_descriptor(source, language=language)
        blocks.append(
            '<section style="border-top:2px solid #111827;padding-top:24px;'
            'margin:30px 0 12px;">'
            f'<p style="font-size:13px;color:#64748b;margin:0 0 4px;">'
            f'{escape(labels["deep_read_label"])}</p>'
            f'<h3 style="font-size:18px;margin:0 0 10px;color:#111827;">'
            f'{escape(title)}</h3>{descriptor}'
            f'{_publish_explanatory_diagram(raw_entry, labels)}'
            f'{"".join(section for section in sections if section)}</section>'
        )
    return "".join(blocks)


def _publish_paper_descriptor(source: object, *, language: str) -> str:
    if not isinstance(source, dict):
        return ""
    gist = str(source.get("gist") or "")
    url = str(source.get("url") or "")
    parts = []
    if gist:
        parts.append(_publish_paragraph(gist))
    if url:
        link_label = "论文链接" if language == "zh" else "Source"
        parts.append(
            '<p style="font-size:13px;color:#64748b;margin:6px 0;">'
            f"{link_label}: {escape(url)}</p>"
        )
    return "".join(parts)


def _publish_explanatory_diagram(
    entry: dict[object, object],
    labels: dict[str, str],
) -> str:
    steps = [
        (labels["problem_short"], _nested_value(entry.get("problem"), "core")),
        (labels["method_short"], _nested_value(entry.get("solution"), "core")),
        (labels["eval_short"], _nested_value(entry.get("experiments"), "summary")),
        (labels["caveat_short"], _first_nested_list(entry.get("limitations"))),
    ]
    rendered = []
    for title, value in steps:
        if value:
            rendered.append(
                '<section style="display:block;margin:8px 0;padding:10px 12px;'
                'background:#ffffff;border:1px solid #bfdbfe;border-radius:6px;">'
                f'<p style="margin:0;color:#1e40af;"><strong>{escape(title)}</strong></p>'
                f'<p style="margin:4px 0 0;">{_publish_format_text(_shorten(value))}</p>'
                '</section>'
            )
    if len(rendered) < 2:
        return ""
    return (
        '<section style="display:block;border-left:3px solid #60a5fa;'
        'background:#f8fbff;padding:12px 14px;margin:18px 0;">'
        f'{"".join(rendered)}</section>'
    )


def _publish_text_block(title: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return (
        f'<h3 style="font-size:18px;margin:24px 0 10px;color:#0f766e;'
        f'font-weight:700;">'
        f"{escape(title)}</h3>{_publish_paragraph(text)}"
    )


def _publish_problem_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _publish_text_block(labels["problem"], value.get("core")),
            _publish_text_block(labels["why_it_matters"], value.get("why_it_matters")),
            _publish_list_block(labels["hidden_assumptions"], value.get("hidden_assumptions")),
        ]
    )


def _publish_solution_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _publish_text_block(labels["solution"], value.get("core")),
            _publish_text_block(labels["mechanism"], value.get("mechanism")),
        ]
    )


def _publish_experiments_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return _publish_text_block(labels["experiments"], value.get("summary"))


def _publish_related_work_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _publish_text_block(labels["related_work"], value.get("novelty")),
            _publish_list_block(labels["prior_work"], value.get("prior_work")),
            _publish_text_block(labels["repackaging_risk"], value.get("repackaging_risk")),
        ]
    )


def _publish_limitations_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _publish_list_block(labels["explicit_limitations"], value.get("explicit_limitations")),
            _publish_list_block(labels["inferred_weaknesses"], value.get("inferred_weaknesses")),
            _publish_list_block(labels["future_work"], value.get("future_work")),
        ]
    )


def _publish_critical_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _publish_text_block(labels["critical"], value.get("bottom_line")),
            _publish_text_block(labels["overclaiming_risk"], value.get("overclaiming_risk")),
            _publish_list_block(labels["weak_evaluations"], value.get("weak_evaluations")),
            _publish_list_block(labels["missing_ablations"], value.get("missing_ablations")),
        ]
    )


def _publish_reader_explanation(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
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
    return "".join(
        _publish_text_block(title, value.get(key))
        for key, title in sections
        if str(value.get(key) or "").strip()
    )


def _publish_list_block(title: str, value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    lines = [str(item).strip() for item in value if str(item).strip()]
    if not lines:
        return ""
    body = "".join(
        f'<p style="margin:8px 0;">• {_publish_format_text(line)}</p>' for line in lines
    )
    return (
        f'<h3 style="font-size:18px;margin:24px 0 10px;color:#0f766e;'
        f'font-weight:700;">'
        f"{escape(title)}</h3>{body}"
    )


def _publish_figure_gallery(
    value: object,
    labels: dict[str, str],
    *,
    media_url_map: Mapping[str, str] | None = None,
) -> str:
    if not isinstance(value, list) or not value:
        return ""
    blocks = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        if _is_pdf_page_fallback_figure(item):
            continue
        raw_src = str(item.get("relative_path") or item.get("asset_path") or "")
        uploaded_src = media_url_map.get(raw_src) if media_url_map else None
        media = ""
        if uploaded_src and _is_wechat_image_src(uploaded_src):
            title = escape(_figure_alt_text(item, labels))
            media = (
                f'<img src="{escape(uploaded_src)}" alt="{title}" '
                'style="max-width:100%;height:auto;display:block;margin:10px auto 12px;" />'
            )
        elif raw_src and _is_local_media_src(raw_src):
            media = (
                '<p style="font-size:14px;color:#475569;margin:8px 0;">'
                "Figure image requires WeChat media upload before publishing.</p>"
            )
        caption = _publish_format_text(
            str(item.get("localized_caption") or item.get("caption") or "")
        )
        explanation = _publish_figure_explanation(str(item.get("explanation") or ""), labels)
        parts = [media]
        if caption:
            parts.append(
                '<p style="font-size:14px;color:#475569;margin:8px 0;">'
                f"{caption}</p>"
            )
        if explanation:
            parts.append(
                '<p style="font-size:14px;color:#334155;margin:8px 0;">'
                f"<strong>{'图解' if labels['figure'] == '论文图' else 'Figure note'}:</strong> "
                f"{_publish_format_text(explanation)}</p>"
            )
        blocks.append(
            '<section style="margin:20px 0;padding:14px 12px;border-top:1px solid #e5e7eb;'
            'border-bottom:1px solid #e5e7eb;background:#fcfcfd;">'
            f'{"".join(part for part in parts if part)}</section>'
        )
    if not blocks:
        return ""
    return (
        f'<h3 style="font-size:18px;margin:24px 0 10px;color:#0f766e;'
        f'font-weight:700;">'
        f'{escape(labels["figures"])}</h3>{"".join(blocks)}'
    )


def _figure_alt_text(item: dict[object, object], labels: dict[str, str]) -> str:
    title = str(item.get("title") or "")
    if title.startswith("fig:"):
        return labels["figure"]
    return title or labels["figure"]


def _publish_figure_explanation(explanation: str, labels: dict[str, str]) -> str:
    if explanation in {
        FIGURE_EXPLANATION_SOURCE_CONTEXT,
    } or explanation.startswith(FIGURE_EXPLANATION_CAPTION_ALIGNMENT_PREFIX):
        return ""
    if labels["figure"] == "论文图" and (
        explanation.startswith("该图被包含")
        or explanation.startswith("这张图用于辅助理解")
    ):
        return ""
    return _localized_figure_explanation(explanation, labels)


def _publish_key_evidence(value: object, labels: dict[str, str]) -> str:
    return ""


def _publish_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    blocks = []
    for group, items in group_source_entries(raw_sources):
        if not items:
            continue
        blocks.append(
            f'<h3 style="font-size:16px;margin:20px 0 8px;color:#0f172a;">'
            f"{escape(source_group_label(group, language=language))}</h3>"
        )
        for item in items:
            title = str(item.get("title", "Untitled source"))
            url = str(item.get("url", ""))
            gist = str(item.get("gist", ""))
            gist_label = "摘要" if language == "zh" else "Gist"
            gist_html = (
                f'<p style="margin:6px 0;"><strong>{gist_label}:</strong> '
                f'{_publish_format_text(gist)}</p>'
                if gist
                else ""
            )
            url_html = (
                f'<p style="margin:6px 0;color:#64748b;font-size:13px;">'
                f'URL: {escape(url)}</p>'
                if url
                else ""
            )
            blocks.append(
                '<section style="border-left:3px solid #dbeafe;padding:10px 0 10px 14px;'
                'margin:12px 0;background:#ffffff;">'
                f'<h3 style="font-size:17px;margin:0 0 8px;color:#111827;">'
                f'{escape(title)}</h3>'
                f'{gist_html}{url_html}'
                '</section>'
            )
    return "".join(blocks)


def _publish_seen_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    lines = []
    for source in raw_sources[:8]:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "Untitled source")
        url = str(source.get("url") or "")
        version = str(source.get("version") or "")
        suffix = f" ({version})" if version else ""
        lines.append(f"{title}{suffix}" + (f" | {url}" if url else ""))
    if not lines:
        return ""
    return "".join(
        '<p style="margin:8px 0;padding-left:18px;text-indent:-18px;">'
        f'{index}. {escape(line)}</p>'
        for index, line in enumerate(lines, start=1)
    )


def _publish_references(
    claims: list[Claim],
    metadata: dict[object, object],
    *,
    language: str,
) -> str:
    sources = metadata.get("sources", []) if isinstance(metadata, dict) else []
    figures = metadata.get("figures", []) if isinstance(metadata, dict) else []
    pieces = [
        _publish_reference_source_list(sources, language=language),
        _publish_reference_figure_list(figures, language=language),
        _publish_evidence_list(claims[:6], language=language),
    ]
    return "".join(piece for piece in pieces if piece)


def _publish_reference_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list) or not raw_sources:
        return ""
    title = "来源链接" if language == "zh" else "Source links"
    rows = []
    for source in raw_sources[:10]:
        if not isinstance(source, dict):
            continue
        source_title = str(source.get("title") or "Untitled source")
        url = str(source.get("url") or "")
        arxiv_id = _arxiv_id_from_url(url)
        suffix = f" ({arxiv_id})" if arxiv_id else ""
        rows.append(f"{source_title}{suffix}" + (f" | {url}" if url else ""))
    return _publish_simple_list(title, rows)


def _publish_reference_figure_list(raw_figures: object, *, language: str) -> str:
    if not isinstance(raw_figures, list) or not raw_figures:
        return ""
    title = "论文图来源" if language == "zh" else "Figure sources"
    rows = []
    for figure in raw_figures[:6]:
        if not isinstance(figure, dict):
            continue
        if _is_pdf_page_fallback_figure(figure):
            continue
        figure_title = _shorten(str(
            figure.get("localized_caption") or figure.get("caption") or "Paper figure"
        ), limit=160)
        attribution = str(figure.get("attribution") or "")
        rows.append(f"{figure_title}: {attribution}" if attribution else figure_title)
    return _publish_simple_list(title, rows)


def _publish_simple_list(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    body = "".join(
        '<p style="margin:8px 0;padding-left:18px;text-indent:-18px;">'
        f'{index}. {escape(row)}</p>'
        for index, row in enumerate(rows, start=1)
    )
    return (
        f'<h3 style="font-size:17px;margin:22px 0 8px;color:#0f172a;">'
        f"{escape(title)}</h3>{body}"
    )


def _publish_evidence_list(claims: list[Claim], *, language: str) -> str:
    if not claims:
        return ""
    title = "关键证据摘录" if language == "zh" else "Key evidence excerpts"
    rows = []
    for claim in claims[:6]:
        quote = claim.evidence[0].quote if claim.evidence else ""
        rows.append(
            '<section style="border-left:3px solid #94a3b8;padding:8px 12px;'
            'margin:10px 0;background:#f8fafc;color:#334155;font-size:14px;">'
            f'<p style="margin:0;">{escape(_shorten(quote, limit=260))}</p></section>'
        )
    return (
        f'<h3 style="font-size:16px;margin:20px 0 8px;color:#0f172a;">{title}</h3>'
        f'{"".join(rows)}'
    )


def _publish_claim_card(claim: Claim, *, language: str) -> str:
    tag = "已核验" if language == "zh" else "Verified"
    text = _localized_claim_text(claim.text, language=language)
    return (
        '<section style="border-left:3px solid #dbeafe;padding:10px 0 10px 14px;'
        'margin:12px 0;background:#ffffff;">'
        f'<p style="margin:0 0 6px;color:#0f766e;font-size:13px;"><strong>{tag}</strong></p>'
        f'<h3 style="font-size:17px;margin:0 0 8px;color:#111827;">'
        f'{_publish_format_text(text)}</h3></section>'
    )


def _publish_format_text(value: str) -> str:
    text = unescape(value)
    text = re.sub(r"<span\b[^>]*>(.*?)</span>", r"\1", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</?[^>]+>", "", text)
    return _format_display_text(text).replace('<span class="rr-formula" ', "<span ")


def _is_wechat_image_src(src: str) -> bool:
    lowered = src.casefold()
    return lowered.startswith("http://mmbiz.qpic.cn/") or lowered.startswith(
        "https://mmbiz.qpic.cn/"
    )


def _section(
    tag: str,
    content: str,
    *,
    section_id: str | None = None,
    class_name: str | None = None,
) -> str:
    id_attr = f' id="{escape(section_id)}"' if section_id else ""
    class_attr = f' class="{escape(class_name)}"' if class_name else ""
    return f"<{tag}{id_attr}{class_attr}>{content}</{tag}>"


def _table_of_contents(draft: ArticleDraft, *, language: str) -> str:
    title = "目录" if language == "zh" else "Contents"
    items = []
    for index, section in enumerate(draft.sections, start=1):
        items.append(f'<li><a href="#rr-section-{index}">{escape(section.title)}</a></li>')
    return _section(
        "section",
        f'<div class="rr-toc"><strong>{title}</strong><ol>{"".join(items)}</ol></div>',
    )


def _paragraphs(text: str) -> str:
    return "".join(
        f"<p>{_format_display_text(line.strip())}</p>"
        for line in text.splitlines()
        if line.strip()
    )


def _today_summary(draft: ArticleDraft, fallback_body: str, *, language: str) -> str:
    lines = _today_summary_lines(draft, language=language)
    if not lines:
        lines = [
            _display_lede(line.strip())
            for line in fallback_body.splitlines()
            if line.strip()
        ]
    if not lines:
        return ""
    return '<div class="rr-summary">' + "".join(
        f"<p>{_format_display_text(line)}</p>" for line in lines
    ) + "</div>"


def _today_summary_lines(draft: ArticleDraft, *, language: str) -> list[str]:
    if draft.metadata.get("draft_type") != "daily_long_form":
        return []
    metadata = draft.metadata
    deep_read_count = _int_metadata(metadata.get("deep_read_count"))
    source_count = _int_metadata(metadata.get("source_count"))
    seen_count = _int_metadata(metadata.get("seen_source_count"))
    verified_count = len(draft.publishable_claims())
    other_count = max(source_count - deep_read_count, 0)
    if language == "zh":
        lines = [
            f"今日精读：{deep_read_count} 篇论文。",
            f"已核验证据点：{verified_count} 条。",
        ]
        if other_count:
            lines.append(f"其他新增来源：{other_count} 个，见下方列表。")
        if seen_count:
            lines.append(f"历史相关来源：{seen_count} 个。")
        return lines
    lines = [
        f"Deep reads: {deep_read_count} paper(s).",
        f"Verified observations: {verified_count}.",
    ]
    if other_count:
        lines.append(f"Other new or updated sources: {other_count}; see list below.")
    if seen_count:
        lines.append(f"Seen-before sources: {seen_count}.")
    return lines


def _int_metadata(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _display_lede(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return _strip_appended_claim(text)


def _strip_appended_claim(value: str) -> str:
    claim_prefixes = (
        "method",
        "problem",
        "solution",
        "experiment",
        "related work",
        "limitations",
        "critical assessment",
        "essence",
    )
    pattern = re.compile(
        r"(?<=[。.!?])\s+(?:" + "|".join(re.escape(prefix) for prefix in claim_prefixes) + r")\s*:",
        flags=re.IGNORECASE,
    )
    match = pattern.search(value)
    if not match:
        return value
    return value[: match.start()].strip()


def _deep_reads(
    raw_deep_reads: object,
    *,
    language: str,
    publish_mode: bool,
    media_url_map: Mapping[str, str] | None = None,
) -> str:
    if not isinstance(raw_deep_reads, list):
        return ""
    blocks = []
    labels = _deep_read_labels(language)
    for raw_entry in raw_deep_reads:
        if not isinstance(raw_entry, dict):
            continue
        title = escape(str(raw_entry.get("title") or labels["untitled"]))
        source = raw_entry.get("source") if isinstance(raw_entry.get("source"), dict) else {}
        source_link = _source_title_link(source, fallback=title)
        narrative = _reader_explanation_blocks(raw_entry.get("reader_explanation"), labels)
        sections = [narrative or _deep_text_block(labels["essence"], raw_entry.get("essence"))]
        sections.append(
            _figure_gallery(
                raw_entry.get("figures"),
                labels,
                publish_mode=publish_mode,
                media_url_map=media_url_map,
            )
        )
        if not narrative:
            sections.extend(
                [
                    _problem_block(raw_entry.get("problem"), labels),
                    _solution_block(raw_entry.get("solution"), labels),
                    _experiments_block(raw_entry.get("experiments"), labels),
                    _related_work_block(raw_entry.get("related_work"), labels),
                    _limitations_block(raw_entry.get("limitations"), labels),
                    _critical_block(raw_entry.get("critical_assessment"), labels),
                    _deep_text_block(
                        labels["plain_example"],
                        raw_entry.get("plain_language_example"),
                    ),
                ]
            )
        sections.append(_key_evidence_block(raw_entry.get("claims"), labels))
        blocks.append(
            f"""<article class="rr-deep">
<p class="rr-kicker">{labels["deep_read_label"]}</p>
<h3>{source_link}</h3>
{_paper_descriptor(source, language=language)}
{_explanatory_diagram(raw_entry, labels)}
{''.join(section for section in sections if section)}
</article>"""
        )
    return "".join(blocks)


def _source_title_link(source: object, *, fallback: str) -> str:
    if not isinstance(source, dict):
        return fallback
    title = escape(str(source.get("title") or fallback))
    url = escape(str(source.get("url") or ""))
    if not url:
        return title
    return f'<a href="{url}">{title}</a>'


def _paper_descriptor(source: object, *, language: str) -> str:
    if not isinstance(source, dict):
        return ""
    descriptor = escape(source_descriptor(source, language=language))
    gist = escape(str(source.get("gist") or ""))
    lines = []
    if descriptor:
        lines.append(f'<p class="rr-kicker">{descriptor}</p>')
    if gist:
        lines.append(f"<p>{gist}</p>")
    return "".join(lines)


def _explanatory_diagram(entry: dict[object, object], labels: dict[str, str]) -> str:
    steps = [
        (labels["problem_short"], _nested_value(entry.get("problem"), "core")),
        (labels["method_short"], _nested_value(entry.get("solution"), "core")),
        (labels["eval_short"], _nested_value(entry.get("experiments"), "summary")),
        (labels["caveat_short"], _first_nested_list(entry.get("limitations"))),
    ]
    rendered = []
    for title, value in steps:
        if value:
            rendered.append(
                '<span class="rr-step">'
                f"<strong>{escape(title)}</strong>{_format_display_text(_shorten(value))}</span>"
            )
    if len(rendered) < 2:
        return ""
    return f'<div class="rr-diagram">{"".join(rendered)}</div>'


def _deep_text_block(title: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"<h4>{escape(title)}</h4><p>{_format_display_text(text)}</p>"


def _problem_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    parts = [
        _deep_text_block(labels["problem"], value.get("core")),
        _deep_text_block(labels["why_it_matters"], value.get("why_it_matters")),
        _list_block(labels["hidden_assumptions"], value.get("hidden_assumptions")),
    ]
    return "".join(parts)


def _solution_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _deep_text_block(labels["solution"], value.get("core")),
            _deep_text_block(labels["mechanism"], value.get("mechanism")),
        ]
    )


def _experiments_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return _deep_text_block(labels["experiments"], value.get("summary"))


def _related_work_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _deep_text_block(labels["related_work"], value.get("novelty")),
            _list_block(labels["prior_work"], value.get("prior_work")),
            _deep_text_block(labels["repackaging_risk"], value.get("repackaging_risk")),
        ]
    )


def _limitations_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _list_block(labels["explicit_limitations"], value.get("explicit_limitations")),
            _list_block(labels["inferred_weaknesses"], value.get("inferred_weaknesses")),
            _list_block(labels["future_work"], value.get("future_work")),
        ]
    )


def _critical_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _deep_text_block(labels["critical"], value.get("bottom_line")),
            _deep_text_block(labels["overclaiming_risk"], value.get("overclaiming_risk")),
            _list_block(labels["weak_evaluations"], value.get("weak_evaluations")),
            _list_block(labels["missing_ablations"], value.get("missing_ablations")),
        ]
    )


def _key_evidence_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, list) or not value:
        return ""
    claims = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        text = _format_display_text(str(item.get("text") or ""))
        evidence = item.get("evidence")
        quote = ""
        if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
            location = str(evidence[0].get("location") or "")
            raw_quote = str(evidence[0].get("quote") or "")
            quote = (
                f'<blockquote class="rr-quote"><em>{escape(location)}</em>'
                f"<p>{escape(raw_quote)}</p></blockquote>"
            )
        claims.append(f"<li>{text}{quote}</li>")
    if not claims:
        return ""
    return (
        '<details class="rr-reference">'
        f'<summary>{escape(labels["key_evidence"])}</summary>'
        f'<ol>{"".join(claims)}</ol></details>'
    )


def _figure_gallery(
    value: object,
    labels: dict[str, str],
    *,
    publish_mode: bool = False,
    media_url_map: Mapping[str, str] | None = None,
) -> str:
    if not isinstance(value, list) or not value:
        return ""
    blocks = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        if _is_pdf_page_fallback_figure(item):
            continue
        original_caption = str(item.get("caption") or "")
        localized_caption = str(item.get("localized_caption") or "")
        caption = _format_display_text(localized_caption or original_caption)
        original_caption_block = _original_caption_block(
            original_caption,
            localized_caption,
            labels,
        )
        explanation = str(item.get("explanation") or "")
        attribution = escape(str(item.get("attribution") or ""))
        reuse_status = escape(str(item.get("reuse_status") or "needs_manual_review"))
        license_value = escape(str(item.get("license") or "unknown"))
        raw_src = str(item.get("relative_path") or item.get("asset_path") or "")
        src = escape(raw_src)
        title = escape(str(item.get("title") or labels["figure"]))
        if not src:
            continue
        uploaded_src = media_url_map.get(raw_src) if media_url_map else None
        if publish_mode and uploaded_src:
            media = f'<img src="{escape(uploaded_src)}" alt="{title}" />'
        elif publish_mode and _is_local_media_src(src):
            media = (
                '<p class="rr-caption">'
                "Figure image requires WeChat media upload before publishing."
                "</p>"
            )
        elif item.get("renderable") is False:
            media = f'<p><a href="{src}">{title}</a></p>'
        else:
            media = f'<img src="{src}" alt="{title}" />'
        blocks.append(
            f"""<figure class="rr-figure">
{media}
<figcaption class="rr-caption"><strong>{title}</strong><br />{caption}</figcaption>
<p>{_localized_figure_explanation(explanation, labels)}</p>
{original_caption_block}
<p class="rr-caption">{labels["attribution"]}: {attribution}<br />
{labels["license"]}: {license_value}; {labels["reuse_status"]}: {reuse_status}</p>
</figure>"""
        )
    if not blocks:
        return ""
    return f'<h4>{escape(labels["figures"])}</h4>{"".join(blocks)}'


def _is_pdf_page_fallback_figure(item: Mapping[str, object]) -> bool:
    """Return true for legacy PDF page screenshots masquerading as figures."""

    original_path = str(item.get("original_path") or "").strip()
    if re.fullmatch(r"page\s+\d+", original_path, flags=re.IGNORECASE):
        return True
    source_path = str(item.get("relative_path") or item.get("asset_path") or "")
    return bool(re.search(r"(?:^|/)\d{2}-page-\d+\.png$", source_path))


def _original_caption_block(
    original_caption: str,
    localized_caption: str,
    labels: dict[str, str],
) -> str:
    original = original_caption.strip()
    if not original:
        return ""
    localized = localized_caption.strip()
    if localized and _clean_display_text(localized) != _clean_display_text(original):
        return (
            '<details class="rr-reference">'
            f'<summary>{escape(labels["original_caption"])}</summary>'
            f"<p>{_format_display_text(original)}</p></details>"
        )
    return ""


def _is_local_media_src(src: str) -> bool:
    lowered = src.casefold()
    return not (
        lowered.startswith("https://")
        or lowered.startswith("http://")
        or lowered.startswith("data:")
    )


def _list_block(title: str, value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    items = "".join(
        f"<li>{_format_display_text(str(item))}</li>" for item in value if str(item).strip()
    )
    if not items:
        return ""
    return f"<h4>{escape(title)}</h4><ul>{items}</ul>"


def _reader_explanation_blocks(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
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
    blocks = []
    for key, title in sections:
        text = str(value.get(key) or "").strip()
        if not text:
            continue
        blocks.append(_deep_text_block(title, text))
    return "".join(blocks)


def _seen_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    label = "已读过" if language == "zh" else "Seen"
    items = []
    for source in raw_sources[:12]:
        if not isinstance(source, dict):
            continue
        title = escape(str(source.get("title") or "Untitled source"))
        url = escape(str(source.get("url") or ""))
        version = escape(str(source.get("version") or ""))
        suffix = f" ({version})" if version else ""
        items.append(f'<li><a href="{url}">{title}</a>{suffix}</li>')
    if not items:
        return ""
    return f"<p>{label}</p><ul>{''.join(items)}</ul>"


def _references(
    claims: list[Claim],
    metadata: dict[object, object],
    *,
    language: str,
) -> str:
    sources = metadata.get("sources", []) if isinstance(metadata, dict) else []
    figures = metadata.get("figures", []) if isinstance(metadata, dict) else []
    if not claims and not sources and not figures:
        fallback = (
            "今天没有可发布的参考证据。"
            if language == "zh"
            else "No verified references today."
        )
        return f"<p>{fallback}</p>"
    label = "展开参考证据" if language == "zh" else "Open references"
    body = "".join(
        [
            _reference_source_list(sources, language=language),
            _reference_figure_list(figures, language=language),
            "".join(_evidence_block(claim, language=language) for claim in claims[:12]),
        ]
    )
    return (
        '<details class="rr-reference">'
        f"<summary>{label}</summary>"
        f"{body}</details>"
    )


def _reference_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list) or not raw_sources:
        return ""
    title = "来源链接" if language == "zh" else "Source links"
    items = []
    for source in raw_sources[:16]:
        if not isinstance(source, dict):
            continue
        source_title = escape(str(source.get("title") or "Untitled source"))
        url = escape(str(source.get("url") or ""))
        if not url:
            continue
        arxiv_id = _arxiv_id_from_url(url)
        suffix = f" ({arxiv_id})" if arxiv_id else ""
        items.append(f'<li><a href="{url}">{source_title}</a>{escape(suffix)}</li>')
    if not items:
        return ""
    return f"<h4>{title}</h4><ul>{''.join(items)}</ul>"


def _reference_figure_list(raw_figures: object, *, language: str) -> str:
    if not isinstance(raw_figures, list) or not raw_figures:
        return ""
    title = "图片许可与复用" if language == "zh" else "Figure license and reuse"
    items = []
    for figure in raw_figures[:8]:
        if not isinstance(figure, dict):
            continue
        figure_title = escape(str(figure.get("title") or "Paper figure"))
        license_value = escape(str(figure.get("license") or "unknown"))
        reuse_status = escape(str(figure.get("reuse_status") or "needs_manual_review"))
        attribution = escape(str(figure.get("attribution") or ""))
        items.append(
            f"<li><strong>{figure_title}</strong>: license={license_value}; "
            f"reuse_status={reuse_status}; {attribution}</li>"
        )
    if not items:
        return ""
    return f"<h4>{title}</h4><ul>{''.join(items)}</ul>"


def _deep_read_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "untitled": "未命名论文",
            "deep_read_label": "精读论文",
            "essence": "本质判断",
            "problem": "问题与动机",
            "why_it_matters": "为什么重要",
            "hidden_assumptions": "隐藏假设",
            "solution": "方法与机制",
            "mechanism": "机制展开",
            "experiments": "实验与评估",
            "related_work": "相关工作",
            "prior_work": "代表性已有工作",
            "repackaging_risk": "重新包装风险",
            "limitations": "局限与未来工作",
            "explicit_limitations": "作者明确局限",
            "inferred_weaknesses": "证据支持的推断弱点",
            "future_work": "未来工作",
            "critical": "中立批判",
            "overclaiming_risk": "过度声称风险",
            "weak_evaluations": "薄弱评估",
            "missing_ablations": "缺失消融",
            "plain_example": "通俗例子",
            "opening_context": "背景知识速读",
            "core_thesis": "核心判断",
            "reader_takeaway": "读者 takeaway",
            "key_evidence": "关键证据",
            "figures": "论文关键图",
            "figure": "论文图",
            "original_caption": "原始图注",
            "attribution": "来源",
            "license": "许可",
            "reuse_status": "复用状态",
            "problem_short": "问题",
            "method_short": "方法",
            "eval_short": "评估",
            "caveat_short": "局限",
        }
    return {
        "untitled": "Untitled paper",
        "deep_read_label": "Deep-read paper",
        "essence": "Essence",
        "problem": "Problem and Motivation",
        "why_it_matters": "Why it matters",
        "hidden_assumptions": "Hidden assumptions",
        "solution": "Solution Mechanism",
        "mechanism": "Mechanism details",
        "experiments": "Experiments",
        "related_work": "Related Work",
        "prior_work": "Representative prior work",
        "repackaging_risk": "Repackaging risk",
        "limitations": "Limitations and Future Work",
        "explicit_limitations": "Explicit limitations",
        "inferred_weaknesses": "Evidence-backed inferred weaknesses",
        "future_work": "Future work",
        "critical": "Critical Assessment",
        "overclaiming_risk": "Overclaiming risk",
        "weak_evaluations": "Weak evaluations",
        "missing_ablations": "Missing ablations",
        "plain_example": "Plain-language Example",
        "opening_context": "Opening Context",
        "core_thesis": "Core Thesis",
        "reader_takeaway": "Reader Takeaway",
        "key_evidence": "Key Evidence",
        "figures": "Key Figures",
        "figure": "Paper figure",
        "original_caption": "Original caption",
        "attribution": "Attribution",
        "license": "License",
        "reuse_status": "Reuse status",
        "problem_short": "Problem",
        "method_short": "Method",
        "eval_short": "Evaluation",
        "caveat_short": "Caveat",
    }


def _localized_figure_explanation(explanation: str, labels: dict[str, str]) -> str:
    if (
        labels["figure"] == "论文图"
        and explanation == FIGURE_EXPLANATION_SOURCE_CONTEXT
    ):
        return "这张图作为来源上下文展示，不新增研究判断。"
    if labels["figure"] == "论文图" and explanation.startswith(
        FIGURE_EXPLANATION_CAPTION_ALIGNMENT_PREFIX
    ):
        return "这张图用于辅助理解；它的图注与一条已核验判断相关，具体证据见本节“关键证据”。"
    if labels["figure"] == "论文图" and explanation:
        return _format_display_text(explanation)
    return _format_display_text(explanation)


def _clean_display_text(value: str) -> str:
    text = value.replace("~", " ")
    text = text.replace("\\%", "%")
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text)
    text = re.sub(r"\$(.*?)\$", r"\1", text)
    text = re.sub(r"\${2,}", "", text)
    text = re.sub(r"\\([A-Za-z]+)\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _format_display_text(value: str) -> str:
    text = _preclean_formula_text(value)
    explicit_pattern = re.compile(r"\\\((.*?)\\\)|\$([^$\n]{1,120})\$")
    formulas: list[str] = []

    def replace_explicit(match: re.Match[str]) -> str:
        formula = match.group(1) if match.group(1) is not None else match.group(2)
        if match.group(2) is not None and not _looks_like_formula(formula or ""):
            return match.group(0)
        formulas.append(_formula_span(formula or ""))
        return f"@@RR_FORMULA_{len(formulas) - 1}@@"

    with_placeholders = explicit_pattern.sub(replace_explicit, text)
    formatted = _format_implicit_formulas(escape(with_placeholders))
    for index, formula in enumerate(formulas):
        formatted = formatted.replace(f"@@RR_FORMULA_{index}@@", formula)
    return formatted


def _preclean_formula_text(value: str) -> str:
    text = value.replace("~", " ")
    text = text.replace("\\%", "%")
    text = re.sub(r"\${2,}", "", text)
    text = text.replace("\\times", "×").replace("\\Delta", "∆")
    text = re.sub(r"\\([A-Za-z]+)\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_formula(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if re.search(r"[=^_{}\\]|[κλθ∆×]", text):
        return True
    if re.fullmatch(r"[A-Za-z]\s+\d+(?:\.\d+)?", text):
        return True
    if re.search(r"[A-Za-z]\([A-Za-z0-9, _+\-]{0,30}\)", text):
        return True
    return False


def _format_implicit_formulas(html: str) -> str:
    formula_pattern = re.compile(
        r"(?<![A-Za-z0-9_-])("
        r"[A-Za-z]\([A-Za-z0-9, _+\-]{0,30}\)\s*=\s*"
        r"[A-Za-z0-9κλθ+\-*/^{}().]+"
        r"|[A-Za-z]\([A-Za-z0-9, _+\-]{0,30}\)"
        r"|\d+(?:\.\d+)?×"
        r"|[κλθ]\s*=\s*\d+(?:\.\d+)?"
        r")(?![A-Za-z0-9_-])"
    )
    return formula_pattern.sub(lambda match: _formula_span(match.group(1)), html)


def _formula_span(value: str) -> str:
    formula = _preclean_formula_text(value)
    if not formula:
        return ""
    return f'<span class="rr-formula" style="{FORMULA_STYLE}">{escape(formula)}</span>'


def _arxiv_id_from_url(url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf|html)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)", url)
    if not match:
        return ""
    return f"arXiv:{match.group('id')}"


def _nested_value(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get(key) or "")


def _first_nested_list(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ["explicit_limitations", "inferred_weaknesses", "future_work"]:
        values = value.get(key)
        if isinstance(values, list) and values:
            return str(values[0])
    return ""


def _shorten(value: str, limit: int = 130) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _claim_card(claim: Claim, *, language: str) -> str:
    tag = "已核验" if language == "zh" else "Verified"
    fallback = (
        "这条判断由下方证据链支撑。"
        if language == "zh"
        else "This claim is backed by the evidence trail below."
    )
    return f"""<section class="rr-card">
<span class="rr-tag">{tag}</span>
<h3>{_format_display_text(_localized_claim_text(claim.text, language=language))}</h3>
<p>{_format_display_text(claim.rationale or fallback)}</p>
</section>"""


def _source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    blocks = []
    for group, items in group_source_entries(raw_sources):
        if not items:
            continue
        blocks.append(f"<h3>{escape(source_group_label(group, language=language))}</h3>")
        for item in items:
            title = escape(str(item.get("title", "Untitled source")))
            url = escape(str(item.get("url", "")))
            gist = _format_display_text(str(item.get("gist", "")))
            descriptor = escape(source_descriptor(item, language=language))
            gist_label = "摘要" if language == "zh" else "Gist"
            blocks.append(
                f"""<section class="rr-card">
<h3><a href="{url}">{title}</a></h3>
<p>{descriptor}</p>
<p><strong>{gist_label}:</strong> {gist}</p>
</section>"""
            )
    return "".join(blocks)


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


def _evidence_block(claim: Claim, *, language: str) -> str:
    anchors = []
    for anchor in claim.evidence:
        title = escape(anchor.source_title or anchor.source_url)
        quote = escape(anchor.quote)
        location = escape(anchor.location or "")
        anchors.append(
            f"""<section class="rr-quote">
<strong>{title}</strong>{f" <em>{location}</em>" if location else ""}
<p>{quote}</p>
<p><a href="{escape(anchor.source_url)}">Original source</a></p>
</section>"""
        )
    claim_text = _format_display_text(_localized_claim_text(claim.text, language=language))
    return f"<section><h3>{claim_text}</h3>{''.join(anchors)}</section>"


def _localized_claim_text(text: str, *, language: str) -> str:
    if language != "zh":
        return text
    prefix_map = {
        "Problem:": "问题：",
        "Solution:": "方法：",
        "Related work:": "相关工作：",
        "Experiment:": "实验：",
        "Limitations:": "局限：",
        "Critical assessment:": "批判判断：",
        "Essence:": "本质：",
    }
    for prefix, localized in prefix_map.items():
        if text.startswith(prefix):
            return localized + text[len(prefix) :].lstrip()
    return text
