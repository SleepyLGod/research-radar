"""Private email rendering from a verified ArticleDraft."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_radar.compose.archive_figures import (
    figure_source,
    is_pdf_page_fallback_figure,
)
from research_radar.compose.display_text import clean_display_text, format_display_text
from research_radar.compose.public_assets import safe_run_asset_path
from research_radar.models import ArticleDraft, ArticleSection
from research_radar.storage.files import ensure_dir

_EMAIL_IMAGE_SUFFIXES = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}


@dataclass(frozen=True)
class EmailAsset:
    """One safe image prepared for email preview and CID attachment."""

    raw_source: str
    source_path: Path
    preview_source: str
    content_id: str
    mime_subtype: str


def prepare_email_assets(draft: ArticleDraft, run_dir: Path) -> list[EmailAsset]:
    """Copy safe PNG/JPEG figures into the run's email preview directory."""

    asset_dir = ensure_dir(run_dir / "email-assets")
    assets: list[EmailAsset] = []
    used_names: set[str] = set()
    seen_sources: set[str] = set()
    for figure in _draft_figures(draft):
        raw_source = figure_source(figure)
        if (
            not raw_source
            or raw_source in seen_sources
            or figure.get("renderable") is False
            or is_pdf_page_fallback_figure(figure)
        ):
            continue
        source_path = safe_run_asset_path(run_dir, raw_source)
        if source_path is None:
            continue
        mime_subtype = _EMAIL_IMAGE_SUFFIXES.get(source_path.suffix.casefold())
        if mime_subtype is None:
            continue
        seen_sources.add(raw_source)
        target_name = _unique_name(source_path.name, used_names)
        target = asset_dir / target_name
        shutil.copy2(source_path, target)
        assets.append(
            EmailAsset(
                raw_source=raw_source,
                source_path=source_path,
                preview_source=f"email-assets/{target_name}",
                content_id=f"rr-figure-{len(assets) + 1}",
                mime_subtype=mime_subtype,
            )
        )
    return assets


def render_email_html(draft: ArticleDraft, *, image_sources: Mapping[str, str]) -> str:
    """Render a standalone email-safe HTML body."""

    language = _language(draft)
    sections = "".join(
        _render_html_section(section, language=language, image_sources=image_sources)
        for section in draft.sections
    )
    return (
        '<!doctype html><html lang="' + ("zh-CN" if language == "zh" else "en") + '">'
        '<head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:#f4f7f8;color:#17202a;">'
        '<main style="max-width:720px;margin:0 auto;background:#fff;padding:32px 28px;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;line-height:1.75;">'
        f'<h1 style="font-size:28px;line-height:1.25;margin:0 0 14px;">{escape(draft.title)}</h1>'
        f'<p style="font-size:17px;color:#475569;margin:0 0 28px;">'
        f'{format_display_text(draft.lede)}</p>{sections}'
        '</main></body></html>\n'
    )


def render_email_text(draft: ArticleDraft) -> str:
    """Render a plain-text fallback from the same public draft."""

    language = _language(draft)
    lines = [draft.title, "", clean_display_text(draft.lede), ""]
    for section in draft.sections:
        kind = str(section.metadata.get("kind") or "")
        lines.extend([section.title, "=" * len(section.title), ""])
        if kind == "deep_reads":
            lines.extend(_render_text_deep_reads(section.metadata.get("deep_reads"), language))
        elif kind in {"new_updated_sources", "seen_before", "references"}:
            lines.extend(_render_text_sources(section.metadata.get("sources")))
        elif section.body.strip():
            lines.extend([clean_display_text(section.body), ""])
    return "\n".join(lines).strip() + "\n"


def _render_html_section(
    section: ArticleSection,
    *,
    language: str,
    image_sources: Mapping[str, str],
) -> str:
    kind = str(section.metadata.get("kind") or "")
    heading = (
        f'<h2 style="font-size:21px;margin:34px 0 14px;border-bottom:1px solid #dce5e7;'
        f'padding-bottom:8px;">{escape(section.title)}</h2>'
    )
    if kind == "deep_reads":
        content = _render_html_deep_reads(
            section.metadata.get("deep_reads"),
            language=language,
            image_sources=image_sources,
        )
    elif kind in {"new_updated_sources", "seen_before", "references"}:
        content = _render_html_sources(section.metadata.get("sources"))
    else:
        content = _html_paragraphs(section.body)
    return heading + (content or _html_paragraphs(section.body))


def _render_html_deep_reads(
    value: object,
    *,
    language: str,
    image_sources: Mapping[str, str],
) -> str:
    if not isinstance(value, list):
        return ""
    labels = _explanation_labels(language)
    blocks: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or ("未命名论文" if language == "zh" else "Untitled paper"))
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        source_url = _public_http_url(source.get("url"))
        title_html = escape(title)
        if source_url:
            title_html = f'<a href="{escape(source_url)}" style="color:#075985;">{title_html}</a>'
        parts = [
            f'<article style="margin:22px 0 36px;">'
            f'<h3 style="font-size:19px;">{title_html}</h3>'
        ]
        gist = str(source.get("gist") or "").strip()
        if gist:
            parts.append(_html_paragraphs(gist))
        explanation = entry.get("reader_explanation")
        if isinstance(explanation, dict):
            for key, label in labels:
                text = str(explanation.get(key) or "").strip()
                if text:
                    parts.append(
                        f'<h4 style="font-size:17px;color:#0f766e;margin:24px 0 8px;">'
                        f'{escape(label)}</h4>{_html_paragraphs(text)}'
                    )
        else:
            parts.extend(_fallback_reading_html(entry, language=language))
        parts.append(_render_html_figures(entry.get("figures"), image_sources=image_sources))
        parts.append("</article>")
        blocks.append("".join(parts))
    return "".join(blocks)


def _render_html_figures(
    value: object,
    *,
    image_sources: Mapping[str, str],
) -> str:
    if not isinstance(value, list):
        return ""
    blocks = []
    for figure in value[:3]:
        if not isinstance(figure, dict):
            continue
        raw_source = figure_source(figure)
        image_source = image_sources.get(raw_source)
        if not image_source:
            continue
        caption = clean_display_text(
            str(figure.get("localized_caption") or figure.get("caption") or "Paper figure")
        )
        explanation = clean_display_text(str(figure.get("explanation") or ""))
        note = (
            f'<p style="font-size:14px;color:#475569;">{escape(explanation)}</p>'
            if explanation
            else ""
        )
        blocks.append(
            '<figure style="margin:24px 0;">'
            f'<img src="{escape(image_source)}" alt="{escape(caption)}" '
            'style="display:block;width:100%;height:auto;">'
            f'<figcaption style="font-size:14px;color:#475569;margin-top:8px;">'
            f'{escape(caption)}</figcaption>{note}</figure>'
        )
    return "".join(blocks)


def _render_html_sources(value: object) -> str:
    if not isinstance(value, list):
        return ""
    items = []
    for source in value:
        if not isinstance(source, dict):
            continue
        title = escape(str(source.get("title") or "Untitled source"))
        url = _public_http_url(source.get("url"))
        gist = str(source.get("gist") or source.get("summary") or "").strip()
        label = f'<a href="{escape(url)}" style="color:#075985;">{title}</a>' if url else title
        suffix = f"：{format_display_text(gist)}" if gist else ""
        items.append(f'<li style="margin:8px 0;">{label}{suffix}</li>')
    return f'<ul style="padding-left:22px;">{"".join(items)}</ul>' if items else ""


def _render_text_deep_reads(value: object, language: str) -> list[str]:
    if not isinstance(value, list):
        return []
    labels = _explanation_labels(language)
    lines: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        lines.extend([str(entry.get("title") or "Untitled paper"), ""])
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        url = _public_http_url(source.get("url"))
        if url:
            lines.extend([url, ""])
        explanation = entry.get("reader_explanation")
        if isinstance(explanation, dict):
            for key, label in labels:
                text = str(explanation.get(key) or "").strip()
                if text:
                    lines.extend([label, clean_display_text(text), ""])
        else:
            for text in _fallback_reading_text(entry):
                lines.extend([clean_display_text(text), ""])
    return lines


def _render_text_sources(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    lines = []
    for source in value:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "Untitled source")
        url = _public_http_url(source.get("url"))
        gist = str(source.get("gist") or source.get("summary") or "").strip()
        line = f"- {title}"
        if url:
            line += f": {url}"
        if gist:
            line += f" — {clean_display_text(gist)}"
        lines.append(line)
    return [*lines, ""] if lines else []


def _fallback_reading_html(entry: Mapping[str, object], *, language: str) -> list[str]:
    labels = (
        [("essence", "核心判断"), ("plain_language_example", "通俗解释")]
        if language == "zh"
        else [("essence", "Essence"), ("plain_language_example", "Plain-language example")]
    )
    parts = []
    for key, label in labels:
        text = str(entry.get(key) or "").strip()
        if text:
            parts.append(
                f'<h4 style="font-size:17px;">{escape(label)}</h4>'
                f'{_html_paragraphs(text)}'
            )
    for key in ("problem", "solution", "experiments", "limitations"):
        value = entry.get(key)
        if isinstance(value, dict):
            text = " ".join(str(item) for item in value.values() if isinstance(item, str))
            if text:
                parts.append(_html_paragraphs(text))
    return parts


def _fallback_reading_text(entry: Mapping[str, object]) -> list[str]:
    values = []
    for key in ("essence", "plain_language_example"):
        text = str(entry.get(key) or "").strip()
        if text:
            values.append(text)
    return values


def _html_paragraphs(value: str) -> str:
    return "".join(
        f'<p style="margin:10px 0;">{format_display_text(line.strip())}</p>'
        for line in value.splitlines()
        if line.strip()
    )


def _draft_figures(draft: ArticleDraft) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for section in draft.sections:
        deep_reads = section.metadata.get("deep_reads")
        if not isinstance(deep_reads, list):
            continue
        for entry in deep_reads:
            if isinstance(entry, dict) and isinstance(entry.get("figures"), list):
                figures.extend(item for item in entry["figures"] if isinstance(item, dict))
    return figures


def _explanation_labels(language: str) -> list[tuple[str, str]]:
    if language == "zh":
        return [
            ("opening_context", "背景知识速读"),
            ("core_thesis", "核心判断"),
            ("problem_walkthrough", "问题与动机"),
            ("solution_walkthrough", "方法与机制"),
            ("experiment_interpretation", "实验与评估"),
            ("related_work_context", "相关工作"),
            ("limitations_discussion", "局限与未来工作"),
            ("plain_language_story", "通俗解释"),
            ("reader_takeaway", "读完可以记住什么"),
        ]
    return [
        ("opening_context", "Opening context"),
        ("core_thesis", "Core thesis"),
        ("problem_walkthrough", "Problem and motivation"),
        ("solution_walkthrough", "Solution mechanism"),
        ("experiment_interpretation", "Experiments"),
        ("related_work_context", "Related work"),
        ("limitations_discussion", "Limitations"),
        ("plain_language_story", "Plain-language explanation"),
        ("reader_takeaway", "What to remember"),
    ]


def _public_http_url(value: object) -> str:
    text = str(value or "").strip()
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


def _language(draft: ArticleDraft) -> str:
    return "zh" if str(draft.metadata.get("language") or "").casefold() == "zh" else "en"


def _unique_name(name: str, used: set[str]) -> str:
    candidate = name
    counter = 2
    stem = Path(name).stem
    suffix = Path(name).suffix
    while candidate in used:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used.add(candidate)
    return candidate
