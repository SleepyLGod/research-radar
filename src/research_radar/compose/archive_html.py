"""Static HTML rendering for public archive article drafts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from typing import Any
from urllib.parse import urljoin, urlsplit

from research_radar.compose.archive_figures import (
    figure_source,
    is_pdf_page_fallback_figure,
)
from research_radar.compose.source_display import source_descriptor
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, ArticleSection, Claim


def render_archive_article(
    draft: ArticleDraft,
    *,
    run_id: str,
    base_url: str,
    asset_map: Mapping[str, str] | None = None,
) -> str:
    """Render a public archive article page."""

    language = str(draft.metadata.get("language", "en"))
    canonical_url = _article_url(base_url, run_id)
    sections = []
    for index, section in enumerate(draft.sections, start=1):
        sections.append(
            _render_section(
                section,
                index=index,
                language=language,
                asset_map=asset_map or {},
            )
        )
    toc = _table_of_contents(draft, language=language)
    body = f"""
<header class="rr-hero">
  <p class="rr-kicker">ResearchRadar</p>
  <h1>{escape(draft.title)}</h1>
  <p class="rr-lede">{_format_text(_display_lede(draft.lede))}</p>
</header>
{toc}
{''.join(sections)}
"""
    return _html_document(
        title=draft.title,
        canonical_url=canonical_url,
        language=language,
        body=body,
    )


def render_archive_index(entries: list[dict[str, Any]], *, base_url: str) -> str:
    """Render the archive landing page."""

    rows = []
    for entry in entries:
        href = _relative_article_href(str(entry["run_id"]))
        rows.append(
            f"""
<article class="rr-list-item">
  <p class="rr-kicker">{escape(str(entry.get("topic_id") or ""))}</p>
  <h2><a href="{escape(href)}">{escape(str(entry.get("title") or "Untitled article"))}</a></h2>
  <p>{_format_text(str(entry.get("digest") or ""))}</p>
  <p class="rr-meta">{escape(str(entry.get("created_at") or "")[:10])}</p>
</article>
"""
        )
    content = "".join(rows) or "<p>No archived articles yet.</p>"
    return _html_document(
        title="ResearchRadar Archive",
        canonical_url=base_url,
        language="en",
        body=f"""
<header class="rr-hero">
  <p class="rr-kicker">ResearchRadar</p>
  <h1>Research archive</h1>
  <p class="rr-lede">Evidence-gated daily research briefs.</p>
</header>
<section class="rr-section">{content}</section>
""",
    )


def _render_section(
    section: ArticleSection,
    *,
    index: int,
    language: str,
    asset_map: Mapping[str, str],
) -> str:
    kind = _section_kind(section)
    if kind == "deep_reads":
        content = _deep_reads(
            section.metadata.get("deep_reads"),
            language=language,
            asset_map=asset_map,
        )
    elif kind in {"new_updated_sources", "other_sources"}:
        content = _source_list(section.metadata.get("sources"), language=language)
    elif kind == "seen_before":
        content = _seen_source_list(section.metadata.get("sources"), language=language)
    elif kind in {"references", "evidence_notes"}:
        content = _references(section.claims, section.metadata, language=language)
    elif kind == "evidence_trail":
        content = _evidence_list(section.claims, language=language)
    elif kind == "today_summary":
        content = _paragraphs(section.body)
    else:
        content = _paragraphs(section.body) + "".join(
            _claim_card(claim, language=language)
            for claim in section.claims
            if claim.is_publishable()
        )
    if not content:
        content = _paragraphs(section.body)
    return (
        f'<section id="section-{index}" class="rr-section">'
        f"<h2>{escape(section.title)}</h2>{content}</section>"
    )


def _deep_reads(raw_deep_reads: object, *, language: str, asset_map: Mapping[str, str]) -> str:
    if not isinstance(raw_deep_reads, list):
        return ""
    blocks = []
    labels = _labels(language)
    for raw_entry in raw_deep_reads:
        if not isinstance(raw_entry, dict):
            continue
        source = raw_entry.get("source") if isinstance(raw_entry.get("source"), dict) else {}
        title = str(raw_entry.get("title") or labels["untitled"])
        content = [
            _paper_header(title, source, language=language),
            _diagram(raw_entry.get("diagram")),
            _reader_explanation(raw_entry.get("reader_explanation"), labels),
            _figure_gallery(raw_entry.get("figures"), asset_map=asset_map),
        ]
        if not content[2]:
            content.extend(
                [
                    _text_block(labels["essence"], raw_entry.get("essence")),
                    _nested_text(
                        labels["problem"],
                        raw_entry.get("problem"),
                        ["core", "why_it_matters"],
                    ),
                    _nested_text(
                        labels["solution"],
                        raw_entry.get("solution"),
                        ["core", "mechanism"],
                    ),
                    _nested_text(labels["experiments"], raw_entry.get("experiments"), ["summary"]),
                    _nested_text(
                        labels["related_work"],
                        raw_entry.get("related_work"),
                        ["novelty", "repackaging_risk"],
                    ),
                    _list_from_nested(labels["limitations"], raw_entry.get("limitations")),
                    _text_block(labels["plain_example"], raw_entry.get("plain_language_example")),
                ]
            )
        content.append(_key_evidence(raw_entry.get("claims"), labels))
        blocks.append(
            f'<article class="rr-deep">{"".join(item for item in content if item)}</article>'
        )
    return "".join(blocks)


def _paper_header(title: str, source: object, *, language: str) -> str:
    source_link = escape(title)
    descriptor = ""
    gist = ""
    if isinstance(source, dict):
        url = _public_http_url(source.get("url"))
        if url:
            source_link = f'<a href="{escape(url)}">{escape(title)}</a>'
        descriptor = source_descriptor(source, language=language)
        gist = str(source.get("gist") or "")
    meta = f'<p class="rr-meta">{escape(descriptor)}</p>' if descriptor else ""
    gist_html = f"<p>{_format_text(gist)}</p>" if gist else ""
    return f"<h3>{source_link}</h3>{meta}{gist_html}"


def _reader_explanation(value: object, labels: dict[str, str]) -> str:
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
    return "".join(_text_block(title, value.get(key)) for key, title in sections)


def _figure_gallery(raw_figures: object, *, asset_map: Mapping[str, str]) -> str:
    if not isinstance(raw_figures, list):
        return ""
    blocks = []
    for figure in raw_figures[:3]:
        if not isinstance(figure, dict) or is_pdf_page_fallback_figure(figure):
            continue
        raw_src = figure_source(figure)
        archived_src = asset_map.get(raw_src)
        if not archived_src:
            continue
        caption = str(figure.get("localized_caption") or figure.get("caption") or "").strip()
        explanation = str(figure.get("explanation") or "").strip()
        caption_html = f"<figcaption>{_format_text(caption)}</figcaption>" if caption else ""
        explanation_html = (
            f"<p>{_format_text(_clean_figure_explanation(explanation))}</p>"
            if explanation
            else ""
        )
        blocks.append(
            f"""
<figure class="rr-figure">
  <img src="{escape(archived_src)}" alt="{escape(caption or 'Paper figure')}">
  {caption_html}
  {explanation_html}
</figure>
"""
        )
    if not blocks:
        return ""
    return '<div class="rr-figures">' + "".join(blocks) + "</div>"


def _diagram(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or len(nodes) < 2:
        return ""
    title = str(value.get("title") or "").strip()
    rendered = []
    for node in nodes[:5]:
        if not isinstance(node, dict):
            continue
        label = str(node.get("label") or "").strip()
        text = str(node.get("text") or "").strip()
        if label and text:
            rendered.append(
                f'<span><strong>{escape(label)}</strong>{_format_text(_shorten(text))}</span>'
            )
    if len(rendered) < 2:
        return ""
    title_html = f"<h4>{escape(title)}</h4>" if title else ""
    return f'<div class="rr-diagram">{title_html}{"".join(rendered)}</div>'


def _source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    blocks = []
    for group, items in group_source_entries(raw_sources):
        if not items:
            continue
        blocks.append(f"<h3>{escape(source_group_label(group, language=language))}</h3>")
        for item in items:
            title = escape(str(item.get("title") or "Untitled source"))
            url = _public_http_url(item.get("url"))
            descriptor = escape(source_descriptor(item, language=language))
            gist = str(item.get("gist") or "").strip()
            link = f'<a href="{escape(url)}">{title}</a>' if url else title
            meta_html = f'<p class="rr-meta">{descriptor}</p>' if descriptor else ""
            gist_html = f"<p>{_format_text(gist)}</p>" if gist else ""
            blocks.append(
                f'<article class="rr-card"><h4>{link}</h4>{meta_html}{gist_html}</article>'
            )
    return "".join(blocks)


def _seen_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    rows = []
    for item in raw_sources[:12]:
        if not isinstance(item, dict):
            continue
        title = escape(str(item.get("title") or "Untitled source"))
        url = _public_http_url(item.get("url"))
        created_at = str(item.get("wechat_created_at") or "").strip()
        previous_label = "上次草稿" if language == "zh" else "previous draft"
        note = f" · {previous_label}: {escape(created_at[:10])}" if created_at else ""
        rows.append(
            f'<li><a href="{escape(url)}">{title}</a>{note}</li>'
            if url
            else f"<li>{title}{note}</li>"
        )
    return f"<ol>{''.join(rows)}</ol>" if rows else ""


def _references(claims: list[Claim], metadata: dict[str, Any], *, language: str) -> str:
    sources = metadata.get("sources", []) if isinstance(metadata, dict) else []
    parts = [
        _source_list(sources, language=language),
        _evidence_list(claims[:8], language=language),
    ]
    return "".join(part for part in parts if part)


def _evidence_list(claims: list[Claim], *, language: str) -> str:
    blocks = []
    label = "Evidence" if language != "zh" else "证据"
    for claim in claims:
        if not claim.is_publishable():
            continue
        anchors = []
        for anchor in claim.evidence:
            title = anchor.source_title or anchor.source_url
            location = f" ({anchor.location})" if anchor.location else ""
            source_url = _public_http_url(anchor.source_url)
            source_link = (
                f'<p><a href="{escape(source_url)}">'
                f'{"原文链接" if language == "zh" else "Original source"}</a></p>'
                if source_url
                else ""
            )
            anchors.append(
                f'<blockquote><strong>{escape(title)}{escape(location)}</strong>'
                f"<p>{escape(anchor.quote)}</p>"
                f"{source_link}</blockquote>"
            )
        blocks.append(
            f'<details class="rr-evidence"><summary>{escape(label)}: '
            f'{_format_text(_localized_claim_text(claim.text, language=language))}</summary>'
            f'{"".join(anchors)}</details>'
        )
    return "".join(blocks)


def _claim_card(claim: Claim, *, language: str) -> str:
    if not claim.is_publishable():
        return ""
    return (
        '<article class="rr-card"><p>'
        f"{_format_text(_localized_claim_text(claim.text, language=language))}</p></article>"
    )


def _text_block(title: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    title_html = f"<h4>{escape(title)}</h4>" if title else ""
    return f"{title_html}{_paragraphs(text)}"


def _nested_text(title: str, value: object, keys: list[str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        _text_block(title if index == 0 else "", value.get(key))
        for index, key in enumerate(keys)
    )


def _list_from_nested(title: str, value: object) -> str:
    if not isinstance(value, dict):
        return ""
    rows = []
    for key in ["explicit_limitations", "inferred_weaknesses", "future_work"]:
        raw_items = value.get(key)
        if isinstance(raw_items, list):
            rows.extend(str(item).strip() for item in raw_items if str(item).strip())
    if not rows:
        return ""
    return (
        f"<h4>{escape(title)}</h4><ul>"
        f"{''.join(f'<li>{_format_text(item)}</li>' for item in rows)}</ul>"
    )


def _key_evidence(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, list) or not value:
        return ""
    rows = []
    for item in value[:8]:
        if isinstance(item, dict) and item.get("text"):
            rows.append(f"<li>{_format_text(str(item['text']))}</li>")
    if not rows:
        return ""
    return (
        f'<details class="rr-evidence"><summary>{escape(labels["key_evidence"])}</summary>'
        f'<ul>{"".join(rows)}</ul></details>'
    )


def _table_of_contents(draft: ArticleDraft, *, language: str) -> str:
    items = []
    for index, section in enumerate(draft.sections, start=1):
        items.append(f'<li><a href="#section-{index}">{escape(section.title)}</a></li>')
    label = "目录" if language == "zh" else "Contents"
    return f'<nav class="rr-toc"><strong>{label}</strong><ol>{"".join(items)}</ol></nav>'


def _paragraphs(text: str) -> str:
    return "".join(
        f"<p>{_format_text(line.strip())}</p>"
        for line in text.splitlines()
        if line.strip()
    )


def _format_text(value: str) -> str:
    return escape(_strip_html(value))


def _strip_html(value: str) -> str:
    return re.sub(r"</?[^>]+>", "", value)


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


def _section_kind(section: ArticleSection) -> str:
    if isinstance(section.metadata.get("kind"), str):
        return str(section.metadata["kind"])
    return ""


def _labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "untitled": "未命名论文",
            "essence": "核心要点",
            "problem": "问题与动机",
            "solution": "方法与机制",
            "experiments": "实验解读",
            "related_work": "相关工作",
            "limitations": "局限与未来工作",
            "plain_example": "通俗例子",
            "opening_context": "背景知识速读",
            "core_thesis": "核心判断",
            "reader_takeaway": "读者 takeaway",
            "key_evidence": "关键证据",
        }
    return {
        "untitled": "Untitled paper",
        "essence": "Essence",
        "problem": "Problem and Motivation",
        "solution": "Solution Mechanism",
        "experiments": "Experiments",
        "related_work": "Related Work",
        "limitations": "Limitations and Future Work",
        "plain_example": "Plain-language Example",
        "opening_context": "Opening Context",
        "core_thesis": "Core Thesis",
        "reader_takeaway": "Reader Takeaway",
        "key_evidence": "Key Evidence",
    }


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


def _clean_figure_explanation(value: str) -> str:
    text = re.sub(r"^This figure is included as source context;\s*", "", value).strip()
    return text or value


def _shorten(value: str, limit: int = 130) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _relative_article_href(run_id: str) -> str:
    return f"articles/{run_id}/"


def _article_url(base_url: str, run_id: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", f"articles/{run_id}/")


def _public_http_url(value: object) -> str:
    text = str(value or "").strip()
    if not text or any(character.isspace() for character in text):
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return text


def _html_document(*, title: str, canonical_url: str, language: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="{escape(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="canonical" href="{escape(canonical_url)}">
  <style>
    body {{
      margin: 0;
      background: #f6f7f9;
      color: #1f2933;
      font: 16px/1.75 -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    }}
    a {{ color: #1d4ed8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .rr-hero, .rr-section, .rr-toc {{
      max-width: 880px;
      margin: 0 auto;
      padding: 28px 22px;
      box-sizing: border-box;
    }}
    .rr-hero {{ padding-top: 54px; }}
    .rr-kicker, .rr-meta {{ color: #64748b; font-size: 0.92rem; margin: 0 0 8px; }}
    h1 {{
      font-size: clamp(2rem, 5vw, 3.4rem);
      line-height: 1.08;
      margin: 0 0 18px;
      letter-spacing: 0;
    }}
    h2 {{ font-size: 1.65rem; margin: 0 0 18px; padding-top: 12px; border-top: 1px solid #d7dde5; }}
    h3 {{ font-size: 1.3rem; margin: 26px 0 10px; }}
    h4 {{ font-size: 1.06rem; margin: 22px 0 8px; color: #334155; }}
    p {{ margin: 10px 0; }}
    .rr-lede {{ font-size: 1.15rem; color: #475569; max-width: 720px; }}
    .rr-toc ol {{ margin: 10px 0 0; padding-left: 22px; }}
    .rr-deep, .rr-card, .rr-list-item {{
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      margin: 18px 0;
    }}
    .rr-figure {{ margin: 24px 0; }}
    .rr-figure img {{
      max-width: 100%;
      border-radius: 8px;
      border: 1px solid #d7dde5;
      background: #fff;
    }}
    figcaption {{ color: #475569; font-size: 0.95rem; margin-top: 8px; }}
    .rr-diagram {{
      display: grid;
      gap: 10px;
      margin: 18px 0;
      padding: 14px;
      border: 1px solid #dbe3ec;
      border-radius: 10px;
      background: #f8fafc;
    }}
    .rr-diagram span {{ display: block; padding: 10px 12px; border-radius: 8px; background: #fff; }}
    .rr-diagram strong {{ display: block; color: #0f172a; }}
    details.rr-evidence {{
      margin: 12px 0;
      padding: 12px 14px;
      border: 1px solid #dbe3ec;
      border-radius: 8px;
      background: #fff;
    }}
    blockquote {{
      margin: 12px 0;
      padding-left: 14px;
      border-left: 3px solid #94a3b8;
      color: #334155;
    }}
    code, .rr-formula {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  </style>
</head>
<body>{body}</body>
</html>
"""
