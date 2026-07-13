"""Static public archive export orchestration."""

from __future__ import annotations

import posixpath
import shutil
from dataclasses import dataclass
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

from research_radar.compose.archive_figures import (
    figure_source,
    is_pdf_page_fallback_figure,
)
from research_radar.compose.archive_html import (
    render_archive_article,
    render_archive_index,
)
from research_radar.compose.draft_io import load_article_draft
from research_radar.models import ArticleDraft
from research_radar.storage.files import ensure_dir, read_json, write_json, write_text

ARCHIVE_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ArchiveExportResult:
    """Paths written by an archive export."""

    report_path: Path
    index_path: Path
    feed_path: Path
    metadata_path: Path


def export_archive_run(
    run_dir: Path,
    output_dir: Path,
    *,
    base_url: str,
    site_language: str | None = None,
) -> ArchiveExportResult:
    """Export one run's article draft into a static archive directory."""

    draft = load_article_draft(run_dir / "article_draft.json")
    run_id = run_dir.name
    normalized_base_url = _normalized_base_url(base_url)
    archive_language = _bind_archive_identity(
        output_dir,
        normalized_base_url,
        site_language=site_language,
        draft_language=str(draft.metadata.get("language") or ""),
    )
    report_dir = output_dir / "reports" / run_id
    report_path = report_dir / "index.html"
    metadata_path = report_dir / "metadata.json"
    previous_metadata = read_json(metadata_path) if metadata_path.exists() else {}
    previous_assets = _metadata_assets(previous_metadata)
    asset_map, current_assets = _copy_archive_assets(draft, run_dir, output_dir, run_id)
    report_url = _report_url(normalized_base_url, run_id)
    metadata = _public_metadata(draft, run_id, report_url, assets=current_assets)

    write_text(
        report_path,
        render_archive_article(
            draft,
            run_id=run_id,
            base_url=normalized_base_url,
            site_language=archive_language,
            asset_map=asset_map,
        ),
    )
    write_json(metadata_path, metadata)
    _retire_stale_assets(
        output_dir,
        run_id,
        previous_assets=previous_assets,
        current_assets=current_assets,
    )
    entries = _archive_entries(output_dir)
    write_text(
        output_dir / "index.html",
        render_archive_index(
            entries,
            base_url=normalized_base_url,
            site_language=archive_language,
        ),
    )
    write_text(
        output_dir / "feed.xml",
        render_archive_feed(
            entries,
            base_url=normalized_base_url,
            site_language=archive_language,
        ),
    )
    return ArchiveExportResult(
        report_path=report_path,
        index_path=output_dir / "index.html",
        feed_path=output_dir / "feed.xml",
        metadata_path=metadata_path,
    )


def render_archive_feed(
    entries: list[dict[str, Any]],
    *,
    base_url: str,
    site_language: str = "en",
) -> str:
    """Render an RSS feed for archive entries."""

    feed_title = "ResearchRadar 研究归档" if site_language == "zh" else "ResearchRadar Archive"
    feed_description = (
        "经过证据核验的每日研究报告。"
        if site_language == "zh"
        else "Evidence-gated daily research reports."
    )
    items = []
    for entry in entries[:50]:
        link = _report_url(base_url, str(entry["run_id"]))
        title = str(entry.get("title") or "Untitled report")
        digest = str(entry.get("digest") or "")
        created_at = _parse_datetime(str(entry.get("created_at") or ""))
        pub_date = format_datetime(created_at) if created_at else ""
        items.append(
            "<item>"
            f"<title>{xml_escape(title)}</title>"
            f"<link>{xml_escape(link)}</link>"
            f"<guid>{xml_escape(link)}</guid>"
            f"<description>{xml_escape(digest)}</description>"
            f"{'<pubDate>' + xml_escape(pub_date) + '</pubDate>' if pub_date else ''}"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{feed_title}</title>"
        f"<link>{xml_escape(base_url)}</link>"
        f"<description>{feed_description}</description>"
        f"{''.join(items)}"
        "</channel></rss>\n"
    )


def _copy_archive_assets(
    draft: ArticleDraft,
    run_dir: Path,
    output_dir: Path,
    run_id: str,
) -> tuple[dict[str, str], list[str]]:
    asset_map: dict[str, str] = {}
    public_assets: list[str] = []
    for figure in _draft_figures(draft):
        raw_src = figure_source(figure)
        if not raw_src or raw_src in asset_map or is_pdf_page_fallback_figure(figure):
            continue
        source_path = _safe_run_asset_path(run_dir, raw_src)
        if source_path is None or not _is_public_image(source_path):
            continue
        relative_source = source_path.relative_to(run_dir.resolve(strict=True)).as_posix()
        target = output_dir / "assets" / run_id / relative_source
        ensure_dir(target.parent)
        shutil.copy2(source_path, target)
        archive_src = posixpath.relpath(
            f"assets/{run_id}/{relative_source}",
            start=f"reports/{run_id}",
        )
        public_path = f"assets/{run_id}/{relative_source}"
        asset_map[raw_src] = archive_src
        asset_map[relative_source] = archive_src
        public_assets.append(public_path)
    return asset_map, list(dict.fromkeys(public_assets))


def _draft_figures(draft: ArticleDraft) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for section in draft.sections:
        if isinstance(section.metadata.get("figures"), list):
            figures.extend(item for item in section.metadata["figures"] if isinstance(item, dict))
        deep_reads = section.metadata.get("deep_reads")
        if isinstance(deep_reads, list):
            for entry in deep_reads:
                if isinstance(entry, dict) and isinstance(entry.get("figures"), list):
                    figures.extend(item for item in entry["figures"] if isinstance(item, dict))
    return figures


def _safe_run_asset_path(run_dir: Path, raw_src: str) -> Path | None:
    source = Path(raw_src)
    if source.is_absolute():
        candidate = source
    else:
        normalized = PurePosixPath(raw_src.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            return None
        candidate = run_dir / Path(*normalized.parts)
    try:
        run_root = run_dir.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(run_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _is_public_image(path: Path) -> bool:
    return path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _public_metadata(
    draft: ArticleDraft,
    run_id: str,
    report_url: str,
    *,
    assets: list[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "topic_id": draft.topic_id,
        "title": draft.title,
        "digest": draft.digest,
        "created_at": draft.created_at.isoformat(),
        "link": report_url,
        "language": _report_language(draft),
        "claim_count": len(draft.publishable_claims()),
        "deep_read_count": _metadata_count(draft, "deep_read_count"),
        "source_count": _metadata_count(draft, "source_count"),
        "assets": assets,
        "lead_asset": assets[0] if assets else "",
    }


def _archive_entries(output_dir: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted((output_dir / "reports").glob("*/metadata.json")):
        data = read_json(path)
        if isinstance(data, dict) and data.get("run_id"):
            entries.append(data)
    return sorted(entries, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _report_url(base_url: str, run_id: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", f"reports/{run_id}/")


def _normalized_base_url(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("base_url must not be empty")
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ValueError("base_url must be a valid http(s) URL") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in text)
    ):
        raise ValueError(
            "base_url must be an absolute http(s) URL without credentials, query, or fragment"
        )
    return text.rstrip("/")


def _bind_archive_identity(
    output_dir: Path,
    base_url: str,
    *,
    site_language: str | None,
    draft_language: str,
) -> str:
    state_path = output_dir / "archive.json"
    requested_language = _normalized_site_language(site_language) if site_language else None
    if state_path.exists():
        state = read_json(state_path)
        schema_version = state.get("schema_version") if isinstance(state, dict) else None
        if schema_version != ARCHIVE_SCHEMA_VERSION:
            raise ValueError(
                "archive schema is incompatible; rebuild the output directory for schema v2"
            )
        existing = str(state.get("base_url") or "") if isinstance(state, dict) else ""
        if existing != base_url:
            raise ValueError(
                f"archive output is already bound to base_url {existing or '<unknown>'}"
            )
        existing_language = str(state.get("site_language") or "")
        if existing_language not in {"en", "zh"}:
            raise ValueError("archive site_language is missing or invalid")
        if requested_language and requested_language != existing_language:
            raise ValueError(
                f"archive output is already bound to site_language {existing_language}"
            )
        return existing_language
    resolved_language = requested_language or _fallback_site_language(draft_language)
    write_json(
        state_path,
        {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "base_url": base_url,
            "site_language": resolved_language,
        },
    )
    return resolved_language


def _normalized_site_language(value: str) -> str:
    language = value.strip().casefold()
    if language not in {"en", "zh"}:
        raise ValueError("site_language must be en or zh")
    return language


def _report_language(draft: ArticleDraft) -> str:
    return _fallback_site_language(str(draft.metadata.get("language") or ""))


def _fallback_site_language(value: str) -> str:
    language = value.strip().casefold()
    return language if language in {"en", "zh"} else "en"


def _metadata_count(draft: ArticleDraft, key: str) -> int:
    value = draft.metadata.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _metadata_assets(metadata: object) -> list[str]:
    if not isinstance(metadata, dict) or not isinstance(metadata.get("assets"), list):
        return []
    return [str(item) for item in metadata["assets"] if isinstance(item, str)]


def _retire_stale_assets(
    output_dir: Path,
    run_id: str,
    *,
    previous_assets: list[str],
    current_assets: list[str],
) -> None:
    stale_assets = sorted(set(previous_assets) - set(current_assets))
    if not stale_assets:
        return
    retirement_root = (
        output_dir.parent
        / f".{output_dir.name}-retired-assets"
        / run_id
        / uuid4().hex
    )
    output_root = output_dir.resolve()
    expected_prefix = PurePosixPath("assets") / run_id
    for relative_path in stale_assets:
        normalized = PurePosixPath(relative_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            continue
        if normalized.parts[:2] != expected_prefix.parts:
            continue
        source = output_dir / Path(*normalized.parts)
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(output_root)
        except (OSError, RuntimeError, ValueError):
            continue
        target = retirement_root / Path(*normalized.parts[2:])
        ensure_dir(target.parent)
        resolved.replace(target)


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
