"""Manual Zhihu article export from a verified ArticleDraft."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from research_radar.compose.archive_figures import (
    figure_source,
    is_pdf_page_fallback_figure,
)
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.public_assets import is_public_image, safe_run_asset_path
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, ArticleSection
from research_radar.storage.files import ensure_dir, write_json, write_text

ZHIHU_EXPORT_SCHEMA_VERSION = 2

_DISPLAY_EXPLANATION_PREFIXES = (
    "针对本验证点的可视化上下文：",
    "针对本验证点的可视化上下文:",
    "Visual context for this verified point:",
)
_CLAIM_PREFIX = re.compile(
    r"^(?:Problem|Solution|Experiment|Related work|Limitations|"
    r"Critical assessment|Essence):\s*",
    flags=re.IGNORECASE,
)
_SOURCE_KIND_PREFIX = re.compile(r"^\[(?:PDF|HTML)\]\s*", flags=re.IGNORECASE)


@dataclass(frozen=True)
class ZhihuExportResult:
    """Paths written by a Zhihu manual export."""

    markdown_path: Path
    metadata_path: Path
    asset_dir: Path


def export_zhihu_run(
    run_dir: Path,
    *,
    asset_base_url: str | None = None,
) -> ZhihuExportResult:
    """Export one run as a Zhihu-ready Markdown body and local image assets."""

    draft = load_article_draft(run_dir / "article_draft.json")
    language = _language(draft)
    normalized_asset_base_url = _normalized_asset_base_url(asset_base_url)
    asset_dir = ensure_dir(run_dir / "zhihu-assets")
    asset_map, assets = _copy_zhihu_assets(
        draft,
        run_dir,
        asset_dir,
        asset_base_url=normalized_asset_base_url,
        language=language,
    )
    markdown_path = run_dir / "zhihu.md"
    metadata_path = run_dir / "zhihu_export.json"
    write_text(markdown_path, render_zhihu_markdown(draft, asset_map=asset_map))
    write_json(
        metadata_path,
        {
            "schema_version": ZHIHU_EXPORT_SCHEMA_VERSION,
            "run_id": run_dir.name,
            "topic_id": draft.topic_id,
            "title": draft.title,
            "digest": draft.digest,
            "language": language,
            "body_path": markdown_path.name,
            "image_mode": "remote" if normalized_asset_base_url else "local",
            "assets": assets,
        },
    )
    return ZhihuExportResult(
        markdown_path=markdown_path,
        metadata_path=metadata_path,
        asset_dir=asset_dir,
    )


def render_zhihu_markdown(
    draft: ArticleDraft,
    *,
    asset_map: Mapping[str, str] | None = None,
) -> str:
    """Render a draft as a title-free Zhihu Markdown article body."""

    language = _language(draft)
    labels = _labels(language)
    lines: list[str] = []

    _append_summary(lines, draft, labels)

    deep_reads = _deep_reads(draft)
    for index, entry in enumerate(deep_reads, start=1):
        _append_deep_read(
            lines,
            entry,
            index=index,
            labels=labels,
            asset_map=asset_map or {},
            language=language,
        )

    _append_public_sources(lines, draft, labels)
    _append_seen_sources(lines, draft, labels)
    _append_references(lines, deep_reads, labels)
    return "\n".join(lines).strip() + "\n"


def _copy_zhihu_assets(
    draft: ArticleDraft,
    run_dir: Path,
    asset_dir: Path,
    *,
    asset_base_url: str,
    language: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    asset_map: dict[str, str] = {}
    assets: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    run_root = run_dir.resolve(strict=True)
    for figures in _draft_figure_groups(draft):
        emitted_count = 0
        for figure in figures:
            if emitted_count >= 3:
                break
            raw_src = figure_source(figure)
            if (
                not raw_src
                or raw_src in seen_sources
                or is_pdf_page_fallback_figure(figure)
                or figure.get("renderable") is False
            ):
                continue
            source_path = safe_run_asset_path(run_dir, raw_src)
            if source_path is None or not is_public_image(source_path):
                continue
            seen_sources.add(raw_src)
            relative_source = source_path.relative_to(run_root)
            target = asset_dir / relative_source
            ensure_dir(target.parent)
            shutil.copy2(source_path, target)
            local_path = (Path("zhihu-assets") / relative_source).as_posix()
            public_url = (
                urljoin(asset_base_url, quote(relative_source.as_posix(), safe="/-._~"))
                if asset_base_url
                else None
            )
            display_path = _markdown_destination(public_url or local_path)
            asset_map[raw_src] = display_path
            asset_map[relative_source.as_posix()] = display_path
            assets.append(
                {
                    "path": local_path,
                    "public_url": public_url,
                    "caption": _figure_caption(figure, language=language),
                }
            )
            emitted_count += 1
    return asset_map, assets


def _append_summary(lines: list[str], draft: ArticleDraft, labels: Mapping[str, str]) -> None:
    summary_lines: list[str] = []
    if draft.lede.strip():
        summary_lines.append(draft.lede.strip())
    section = _section(draft, "today_summary")
    if section is not None:
        for raw_line in section.body.splitlines():
            text = raw_line.strip()
            if text and _normalized_text(text) not in {
                _normalized_text(item) for item in summary_lines
            }:
                summary_lines.append(text)
    if summary_lines:
        lines.extend([f"## {labels['summary']}", "", *summary_lines, ""])


def _append_deep_read(
    lines: list[str],
    entry: dict[str, Any],
    *,
    index: int,
    labels: Mapping[str, str],
    asset_map: Mapping[str, str],
    language: str,
) -> None:
    title = _clean_title(entry.get("title"), labels["untitled"])
    lines.extend([f"## {index}. {title}", ""])
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    source_url = _public_http_url(source.get("url"))
    if source_url:
        lines.extend(
            [f"[{labels['paper_link']}]({_markdown_destination(source_url)})", ""]
        )

    for label, text in _deep_read_sections(entry, labels):
        lines.extend([f"### {label}", "", text, ""])

    _append_figures(
        lines,
        entry.get("figures"),
        labels=labels,
        asset_map=asset_map,
        language=language,
    )


def _deep_read_sections(
    entry: Mapping[str, object],
    labels: Mapping[str, str],
) -> list[tuple[str, str]]:
    explanation = entry.get("reader_explanation")
    if isinstance(explanation, dict):
        fields = (
            ("opening_context", "opening_context"),
            ("core_thesis", "core_thesis"),
            ("problem_walkthrough", "problem"),
            ("solution_walkthrough", "solution"),
            ("experiment_interpretation", "experiments"),
            ("related_work_context", "related_work"),
            ("limitations_discussion", "limitations"),
            ("plain_language_story", "plain_example"),
            ("reader_takeaway", "reader_takeaway"),
        )
        sections = [
            (labels[label_key], text)
            for value_key, label_key in fields
            if (text := str(explanation.get(value_key) or "").strip())
        ]
        if sections:
            return sections

    fallback_fields = (
        ("essence", "core_thesis", ()),
        ("problem", "problem", ("core", "why_it_matters")),
        ("solution", "solution", ("core", "mechanism")),
        ("experiments", "experiments", ("summary",)),
        ("related_work", "related_work", ("novelty", "prior_work")),
        (
            "limitations",
            "limitations",
            ("explicit_limitations", "inferred_weaknesses", "future_work"),
        ),
        ("plain_language_example", "plain_example", ()),
    )
    sections: list[tuple[str, str]] = []
    for value_key, label_key, nested_keys in fallback_fields:
        text = _display_value(entry.get(value_key), nested_keys)
        if text:
            sections.append((labels[label_key], text))
    return sections


def _append_figures(
    lines: list[str],
    raw_figures: object,
    *,
    labels: Mapping[str, str],
    asset_map: Mapping[str, str],
    language: str,
) -> None:
    if not isinstance(raw_figures, list):
        return
    figure_lines: list[str] = []
    seen_explanations: set[str] = set()
    figure_number = 0
    for figure in raw_figures:
        if not isinstance(figure, dict):
            continue
        raw_path = figure_source(figure)
        image_path = asset_map.get(raw_path, "")
        if not image_path:
            continue
        if figure_number >= 3:
            break
        figure_number += 1
        caption = _figure_caption(figure, language=language)
        figure_lines.extend(
            [
                f"![{_escape_markdown_text(caption)}]({image_path})",
                "",
                f"*{labels['figure']} {figure_number}｜{caption}*",
            ]
        )
        explanation = _clean_figure_explanation(
            str(figure.get("explanation") or ""),
            caption=caption,
        )
        explanation_key = _normalized_text(explanation)
        if explanation and explanation_key not in seen_explanations:
            seen_explanations.add(explanation_key)
            figure_lines.extend(["", f"{labels['figure_note']}：{explanation}"])
        figure_lines.append("")
    if figure_lines:
        lines.extend([f"### {labels['figures']}", "", *figure_lines])


def _append_public_sources(
    lines: list[str],
    draft: ArticleDraft,
    labels: Mapping[str, str],
) -> None:
    section = _section(draft, "new_updated_sources")
    if section is None:
        return
    raw_sources = section.metadata.get("sources")
    if not isinstance(raw_sources, list):
        return
    groups = [(group, items) for group, items in group_source_entries(raw_sources) if items]
    if not groups:
        return
    lines.extend([f"## {labels['further_reading']}", ""])
    language = "zh" if labels["paper_link"] == "查看论文原文" else "en"
    for group, items in groups:
        lines.extend([f"### {source_group_label(group, language=language)}", ""])
        for item in items:
            title = _clean_title(item.get("title"), labels["untitled_source"])
            url = _public_http_url(item.get("url"))
            linked_title = f"[{title}]({_markdown_destination(url)})" if url else title
            gist = str(item.get("gist") or "").strip()
            separator = "：" if language == "zh" else ": "
            lines.append(f"- {linked_title}{separator}{gist}" if gist else f"- {linked_title}")
        lines.append("")


def _append_seen_sources(
    lines: list[str],
    draft: ArticleDraft,
    labels: Mapping[str, str],
) -> None:
    section = _section(draft, "seen_before")
    if section is None:
        return
    raw_sources = section.metadata.get("sources")
    if not isinstance(raw_sources, list):
        return
    source_lines: list[str] = []
    for item in raw_sources[:12]:
        if not isinstance(item, dict):
            continue
        title = _clean_title(item.get("title"), labels["untitled_source"])
        url = _public_http_url(item.get("url"))
        source_lines.append(
            f"- [{title}]({_markdown_destination(url)})" if url else f"- {title}"
        )
    if source_lines:
        lines.extend([f"## {labels['seen_sources']}", "", *source_lines, ""])


def _append_references(
    lines: list[str],
    deep_reads: list[dict[str, Any]],
    labels: Mapping[str, str],
) -> None:
    references: list[str] = []
    seen_urls: set[str] = set()
    for entry in deep_reads:
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        url = _public_http_url(source.get("url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = _clean_title(source.get("title") or entry.get("title"), labels["untitled"])
        references.append(f"- [{title}]({_markdown_destination(url)})")
    if references:
        lines.extend([f"## {labels['references']}", "", *references, ""])


def _deep_reads(draft: ArticleDraft) -> list[dict[str, Any]]:
    section = _section(draft, "deep_reads")
    if section is None:
        return []
    raw_deep_reads = section.metadata.get("deep_reads")
    if not isinstance(raw_deep_reads, list):
        return []
    return [entry for entry in raw_deep_reads if isinstance(entry, dict)]


def _section(draft: ArticleDraft, kind: str) -> ArticleSection | None:
    for section in draft.sections:
        if str(section.metadata.get("kind") or "") == kind:
            return section
    return None


def _display_value(value: object, nested_keys: tuple[str, ...]) -> str:
    if nested_keys and isinstance(value, dict):
        parts: list[str] = []
        for key in nested_keys:
            raw = value.get(key)
            if isinstance(raw, list):
                parts.extend(str(item).strip() for item in raw if str(item).strip())
            elif str(raw or "").strip():
                parts.append(str(raw).strip())
        return "\n\n".join(parts)
    return str(value or "").strip()


def _clean_figure_explanation(value: str, *, caption: str) -> str:
    text = value.strip()
    for prefix in _DISPLAY_EXPLANATION_PREFIXES:
        if text.startswith(prefix):
            text = text.removeprefix(prefix).strip()
            break
    text = _CLAIM_PREFIX.sub("", text).strip()
    if not text:
        return ""
    normalized_caption = _normalized_text(caption)
    normalized_explanation = _normalized_text(text)
    if normalized_caption == normalized_explanation:
        return ""
    if min(len(normalized_caption), len(normalized_explanation)) >= 20 and (
        normalized_explanation in normalized_caption
        or normalized_caption in normalized_explanation
    ):
        return ""
    return text


def _normalized_asset_base_url(value: str | None) -> str:
    if value is None:
        return ""
    text = value.strip()
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ValueError("Invalid Zhihu asset base URL") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid Zhihu asset base URL")
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc,
            parsed.path.rstrip("/") + "/",
            "",
            "",
        )
    )


def _public_http_url(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    scheme = parsed.scheme.casefold()
    if scheme == "http" and parsed.hostname.casefold() == "arxiv.org":
        scheme = "https"
    return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def _clean_title(value: object, fallback: str) -> str:
    text = _SOURCE_KIND_PREFIX.sub("", str(value or "").strip()) or fallback
    return _escape_markdown_text(text)


def _escape_markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _markdown_destination(value: str) -> str:
    return quote(value, safe=":/?&=#%+-._~")


def _normalized_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "summary": "今日摘要",
            "paper_link": "查看论文原文",
            "untitled": "未命名论文",
            "untitled_source": "未命名来源",
            "opening_context": "背景知识速读",
            "core_thesis": "核心判断",
            "problem": "问题与动机",
            "solution": "方法与机制",
            "experiments": "实验与评估",
            "related_work": "相关工作",
            "limitations": "局限与未来工作",
            "plain_example": "通俗例子",
            "reader_takeaway": "读完可以记住什么",
            "figures": "论文图解",
            "figure": "图",
            "figure_note": "图中可以这样看",
            "further_reading": "延伸阅读",
            "seen_sources": "历史相关来源",
            "references": "参考资料",
        }
    return {
        "summary": "Today at a Glance",
        "paper_link": "Read the paper",
        "untitled": "Untitled paper",
        "untitled_source": "Untitled source",
        "opening_context": "Opening Context",
        "core_thesis": "Core Thesis",
        "problem": "Problem and Motivation",
        "solution": "Method and Mechanism",
        "experiments": "Experiments and Evaluation",
        "related_work": "Related Work",
        "limitations": "Limitations and Future Work",
        "plain_example": "Plain-language Example",
        "reader_takeaway": "What to Remember",
        "figures": "Paper Figures",
        "figure": "Figure",
        "figure_note": "How to read it",
        "further_reading": "Further Reading",
        "seen_sources": "Related Sources Seen Before",
        "references": "References",
    }


def _draft_figure_groups(draft: ArticleDraft) -> list[list[dict[str, Any]]]:
    figure_groups: list[list[dict[str, Any]]] = []
    for section in draft.sections:
        deep_reads = section.metadata.get("deep_reads")
        if isinstance(deep_reads, list):
            for entry in deep_reads:
                if isinstance(entry, dict) and isinstance(entry.get("figures"), list):
                    figure_groups.append(
                        [item for item in entry["figures"] if isinstance(item, dict)]
                    )
    return figure_groups


def _figure_caption(figure: Mapping[str, object], *, language: str) -> str:
    return str(
        figure.get("localized_caption")
        or figure.get("caption")
        or ("论文图" if language == "zh" else "Paper figure")
    ).strip()


def _language(draft: ArticleDraft) -> str:
    return "zh" if str(draft.metadata.get("language", "en")) == "zh" else "en"
