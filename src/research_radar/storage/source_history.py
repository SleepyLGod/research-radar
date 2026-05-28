"""Append-only source history for daily reports."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_radar.discovery.dedupe import canonicalize_url
from research_radar.models import SourceCandidate
from research_radar.storage.files import ensure_dir, read_jsonl

REPORTABLE_HISTORY_STATUSES = {"new", "version_update", "not_tracked"}


def annotate_source_history(
    root: Path,
    topic_id: str,
    candidates: list[SourceCandidate],
    *,
    run_id: str,
) -> tuple[list[SourceCandidate], dict[str, Any]]:
    """Annotate sources with local history status and append new/update events."""

    path = root / "data" / "source_history" / f"{_safe_topic(topic_id)}.jsonl"
    records = _latest_records(path)
    annotated: list[SourceCandidate] = []
    append_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        annotated_candidate, row = _annotate_candidate(candidate, records, run_id)
        annotated.append(annotated_candidate)
        if row is not None:
            append_rows.append(row)
            records[row["family_key"]] = row
    if append_rows:
        _append_jsonl(path, append_rows)
    report = _history_report(path, annotated, append_rows)
    return annotated, report


def is_reportable_source(source: SourceCandidate) -> bool:
    """Return whether a source should appear in today's report."""

    status = source.metadata.get("source_history", {}).get("status", "not_tracked")
    return str(status) in REPORTABLE_HISTORY_STATUSES


def source_family_key(source: SourceCandidate) -> str | None:
    """Return a stable source family key for history dedupe."""

    canonical_id = source.canonical_id or ""
    arxiv_id = _arxiv_id(canonical_id) or _arxiv_id(source.url)
    if arxiv_id:
        return f"arxiv:{_arxiv_family(arxiv_id)}"
    doi = _doi(canonical_id) or _doi(source.url)
    if doi:
        return f"doi:{doi.casefold()}"
    if canonical_id:
        return canonical_id.casefold()
    github = _github_repo(source.url)
    if github:
        return f"github:{github}"
    if source.url:
        return f"url:{canonicalize_url(source.url)}"
    return None


def source_version(source: SourceCandidate) -> str | None:
    """Return a source version string when one is detectable."""

    arxiv_id = _arxiv_id(source.canonical_id or "") or _arxiv_id(source.url)
    if not arxiv_id:
        return None
    match = re.search(r"v(\d+)$", arxiv_id, re.IGNORECASE)
    return f"v{match.group(1)}" if match else None


def _annotate_candidate(
    candidate: SourceCandidate,
    records: dict[str, dict[str, Any]],
    run_id: str,
) -> tuple[SourceCandidate, dict[str, Any] | None]:
    if candidate.metadata.get("relevance", {}).get("status") != "relevant":
        version = source_version(candidate)
        return (
            _with_history(candidate, "not_reported", source_family_key(candidate), version, None),
            None,
        )
    family_key = source_family_key(candidate)
    version = source_version(candidate)
    if family_key is None:
        return _with_history(candidate, "not_tracked", None, version, None), None
    previous = records.get(family_key)
    previous_version = (
        str(previous.get("latest_version")) if previous and previous.get("latest_version") else None
    )
    if previous is None:
        status = "new"
    elif _is_newer_version(version, previous_version):
        status = "version_update"
    else:
        status = "seen"
    row = None
    if status in {"new", "version_update"}:
        row = _history_row(candidate, family_key, version, previous_version, status, run_id)
    return _with_history(candidate, status, family_key, version, previous_version), row


def _with_history(
    candidate: SourceCandidate,
    status: str,
    family_key: str | None,
    version: str | None,
    previous_version: str | None,
) -> SourceCandidate:
    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "source_history": {
                "status": status,
                "family_key": family_key,
                "version": version,
                "previous_version": previous_version,
            },
        },
    )


def _history_row(
    candidate: SourceCandidate,
    family_key: str,
    version: str | None,
    previous_version: str | None,
    status: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "event": status,
        "family_key": family_key,
        "latest_version": version,
        "previous_version": previous_version,
        "title": candidate.title,
        "url": candidate.url,
        "canonical_id": candidate.canonical_id,
        "source_type": candidate.source_type.value,
        "source_name": candidate.source_name,
        "published_at": candidate.published_at,
        "run_id": run_id,
        "seen_at": datetime.now(UTC).isoformat(),
    }


def _latest_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        family_key = row.get("family_key")
        if isinstance(family_key, str) and family_key:
            records[family_key] = row
    return records


def _history_report(
    path: Path,
    candidates: list[SourceCandidate],
    appended: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    omitted_seen_sources = []
    for candidate in candidates:
        history = candidate.metadata.get("source_history", {})
        status = str(history.get("status", "not_tracked"))
        counts[status] = counts.get(status, 0) + 1
        if status == "seen":
            omitted_seen_sources.append(
                {
                    "title": candidate.title,
                    "url": candidate.url,
                    "family_key": history.get("family_key"),
                    "version": history.get("version"),
                }
            )
    return {
        "history_path": str(path),
        "counts": counts,
        "appended_count": len(appended),
        "omitted_seen_sources": omitted_seen_sources,
    }


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _is_newer_version(version: str | None, previous_version: str | None) -> bool:
    if version is None or previous_version is None or version == previous_version:
        return False
    current = _version_number(version)
    previous = _version_number(previous_version)
    if current is None or previous is None:
        return version != previous_version
    return current > previous


def _version_number(version: str) -> int | None:
    match = re.fullmatch(r"v(\d+)", version, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _arxiv_id(value: str) -> str | None:
    match = re.search(
        r"(?:arxiv[:./\s]|10\.48550/arxiv\.|arxiv\.org/(?:abs|pdf|html)/)"
        r"(\d{4}\.\d{4,5}(?:v\d+)?)",
        value,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _arxiv_family(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)


def _doi(value: str) -> str | None:
    raw = value.removeprefix("DOI:").removeprefix("doi:")
    raw = raw.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    if raw.startswith("10."):
        return raw
    return None


def _github_repo(url: str) -> str | None:
    match = re.search(r"github\.com/([^/\s]+)/([^/\s?#]+)", url, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).casefold()}/{match.group(2).casefold()}"


def _safe_topic(topic_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", topic_id).strip("-") or "topic"
