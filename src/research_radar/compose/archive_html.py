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
from research_radar.compose.archive_theme import ARCHIVE_CSS
from research_radar.compose.display_text import format_display_text
from research_radar.compose.source_display import source_descriptor
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, ArticleSection, Claim


def render_archive_article(
    draft: ArticleDraft,
    *,
    run_id: str,
    base_url: str,
    site_language: str,
    asset_map: Mapping[str, str] | None = None,
) -> str:
    """Render a public archive article page."""

    language = str(draft.metadata.get("language", "en"))
    canonical_url = _report_url(base_url, run_id)
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
    mobile_toc = _table_of_contents(draft, language=language, mobile=True)
    created_at = draft.created_at.date().isoformat()
    report_label = "研究报告" if site_language == "zh" else "Research report"
    stats = _report_stats(draft, language=site_language)
    body = f"""
{_site_header(home_href="../../", feed_href="../../feed.xml", language=site_language)}
<main id="main-content" class="rr-report">
  <header class="rr-report-hero">
    <p class="rr-eyebrow">
      {escape(report_label)} · {escape(draft.topic_id)} · {escape(created_at)}
    </p>
    <h1>{escape(draft.title)}</h1>
    <p class="rr-lede">{_format_text(_display_lede(draft.lede))}</p>
    {stats}
  </header>
  <div class="rr-report-layout">
    {toc}
    <div class="rr-report-main">
      {mobile_toc}
      {''.join(sections)}
    </div>
  </div>
</main>
{_footer(site_language)}
"""
    return _html_document(
        title=draft.title,
        canonical_url=canonical_url,
        language=language,
        body=body,
    )


def render_archive_index(
    entries: list[dict[str, Any]],
    *,
    base_url: str,
    site_language: str,
) -> str:
    """Render the archive landing page."""

    latest = entries[0] if entries else None
    rows = []
    for entry in entries[1:] if latest else []:
        href = _relative_report_href(str(entry["run_id"]))
        entry_title = str(entry.get("title") or _site_labels(site_language)["untitled"])
        rows.append(
            f"""
<article class="rr-list-item">
  <p class="rr-eyebrow">{escape(str(entry.get("topic_id") or ""))}</p>
  <h2><a href="{escape(href)}">{escape(entry_title)}</a></h2>
  <p>{_format_text(str(entry.get("digest") or ""))}</p>
  <p class="rr-meta">{escape(str(entry.get("created_at") or "")[:10])}</p>
</article>
"""
        )
    labels = _site_labels(site_language)
    if latest:
        latest_html = _latest_report(latest, language=site_language)
        recent_html = (
            f'<section class="rr-recent"><p class="rr-eyebrow">{escape(labels["recent"])}</p>'
            f'<div class="rr-report-list">{"".join(rows)}</div></section>'
            if rows
            else ""
        )
        content = latest_html + recent_html
    else:
        content = f'<p class="rr-empty">{escape(labels["empty"])}</p>'
    return _html_document(
        title=labels["site_title"],
        canonical_url=base_url,
        language=site_language,
        body=f"""
{_site_header(home_href="./", feed_href="feed.xml", language=site_language)}
<main id="main-content" class="rr-home">{content}</main>
{_footer(site_language)}
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
        content = f'<div class="rr-summary">{_paragraphs(section.body)}</div>'
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
            f'<p class="rr-figure-note">{_format_text(_clean_figure_explanation(explanation))}</p>'
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
        rows = []
        for item in items:
            title = escape(str(item.get("title") or "Untitled source"))
            url = _public_http_url(item.get("url"))
            descriptor = escape(source_descriptor(item, language=language))
            gist = str(item.get("gist") or "").strip()
            link = f'<a href="{escape(url)}">{title}</a>' if url else title
            meta_html = f'<p class="rr-meta">{descriptor}</p>' if descriptor else ""
            gist_html = f"<p>{_format_text(gist)}</p>" if gist else ""
            rows.append(
                f'<article class="rr-source"><h4>{link}</h4>{meta_html}{gist_html}</article>'
            )
        blocks.append(
            '<div class="rr-source-group">'
            f"<h3>{escape(source_group_label(group, language=language))}</h3>"
            f'<div class="rr-source-list">{"".join(rows)}</div></div>'
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
    return f'<ol class="rr-seen">{"".join(rows)}</ol>' if rows else ""


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


def _table_of_contents(
    draft: ArticleDraft,
    *,
    language: str,
    mobile: bool = False,
) -> str:
    items = []
    for index, section in enumerate(draft.sections, start=1):
        items.append(f'<li><a href="#section-{index}">{escape(section.title)}</a></li>')
    label = "目录" if language == "zh" else "Contents"
    contents = f'<strong>{label}</strong><ol>{"".join(items)}</ol>'
    if mobile:
        return (
            f'<details class="rr-mobile-toc"><summary>{label}</summary>'
            f'<ol>{"".join(items)}</ol></details>'
        )
    return f'<nav class="rr-toc" aria-label="{escape(label)}">{contents}</nav>'


def _paragraphs(text: str) -> str:
    return "".join(
        f"<p>{_format_text(line.strip())}</p>"
        for line in text.splitlines()
        if line.strip()
    )


def _format_text(value: str) -> str:
    return format_display_text(_strip_html(value))


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


def _relative_report_href(run_id: str) -> str:
    return f"reports/{run_id}/"


def _report_url(base_url: str, run_id: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", f"reports/{run_id}/")


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


def _site_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "archive": "研究报告",
            "rss": "RSS",
            "skip": "跳到正文",
            "latest": "最新研究报告",
            "recent": "近期报告",
            "empty": "还没有可公开的研究报告。",
            "untitled": "未命名报告",
            "site_title": "ResearchRadar 研究归档",
            "deep_reads": "精读论文",
            "verified": "核验证据",
            "sources": "相关来源",
            "footer": "ResearchRadar 只公开通过证据门控的研究内容。",
        }
    return {
        "archive": "Research reports",
        "rss": "RSS",
        "skip": "Skip to content",
        "latest": "Latest report",
        "recent": "Recent reports",
        "empty": "No public research reports yet.",
        "untitled": "Untitled report",
        "site_title": "ResearchRadar Archive",
        "deep_reads": "Deep reads",
        "verified": "Verified observations",
        "sources": "Related sources",
        "footer": "ResearchRadar publishes only evidence-gated research content.",
    }


def _site_header(*, home_href: str, feed_href: str, language: str) -> str:
    labels = _site_labels(language)
    return f"""
<a class="rr-skip" href="#main-content">{escape(labels["skip"])}</a>
<header class="rr-site-header">
  <div class="rr-site-bar">
    <a class="rr-brand" href="{escape(home_href)}">RESEARCHRADAR</a>
    <nav class="rr-site-nav" aria-label="{escape(labels["archive"])}">
      <a href="{escape(home_href)}">{escape(labels["archive"])}</a>
      <a href="{escape(feed_href)}">{escape(labels["rss"])}</a>
    </nav>
  </div>
</header>
"""


def _footer(language: str) -> str:
    return f'<footer class="rr-footer">{escape(_site_labels(language)["footer"])}</footer>'


def _latest_report(entry: dict[str, Any], *, language: str) -> str:
    labels = _site_labels(language)
    run_id = str(entry.get("run_id") or "")
    href = _relative_report_href(run_id)
    title = str(entry.get("title") or labels["untitled"])
    topic_id = str(entry.get("topic_id") or "")
    created_at = str(entry.get("created_at") or "")[:10]
    digest = str(entry.get("digest") or "")
    lead_asset = _public_asset_href(entry.get("lead_asset"))
    media = (
        '<div class="rr-home-latest-media">'
        f'<a href="{escape(href)}"><img src="{escape(lead_asset)}" alt="{escape(title)}"></a>'
        "</div>"
        if lead_asset
        else ""
    )
    no_media_class = " rr-no-media" if not media else ""
    return f"""
<section class="rr-home-latest{no_media_class}">
  <div>
    <p class="rr-eyebrow">{escape(labels["latest"])} · {escape(created_at)}</p>
    <h1><a href="{escape(href)}">{escape(title)}</a></h1>
    <p class="rr-lede">{_format_text(digest)}</p>
    <p class="rr-meta">{escape(topic_id)}</p>
    {_entry_stats(entry, language=language)}
  </div>
  {media}
</section>
"""


def _entry_stats(entry: Mapping[str, Any], *, language: str) -> str:
    labels = _site_labels(language)
    values = [
        (labels["deep_reads"], _entry_count(entry, "deep_read_count")),
        (labels["verified"], _entry_count(entry, "claim_count")),
        (labels["sources"], _entry_count(entry, "source_count")),
    ]
    items = [
        f'<span class="rr-stat">{escape(label)} {count}</span>'
        for label, count in values
        if count
    ]
    return f'<div class="rr-stats">{"".join(items)}</div>' if items else ""


def _report_stats(draft: ArticleDraft, *, language: str) -> str:
    return _entry_stats(
        {
            "deep_read_count": draft.metadata.get("deep_read_count", 0),
            "claim_count": len(draft.publishable_claims()),
            "source_count": draft.metadata.get("source_count", 0),
        },
        language=language,
    )


def _entry_count(entry: Mapping[str, Any], key: str) -> int:
    value = entry.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _public_asset_href(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/"):
        return ""
    parts = text.split("/")
    if ".." in parts or parts[0] != "assets":
        return ""
    if not text.casefold().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
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
  <style>{ARCHIVE_CSS}</style>
</head>
<body>{body}</body>
</html>
"""
