"""Append-only source history for daily reports."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_radar.discovery.dedupe import canonicalize_url
from research_radar.models import SourceCandidate, SourceType
from research_radar.storage.files import ensure_dir, read_jsonl

REPORTABLE_HISTORY_STATUSES = {"new", "version_update", "not_tracked"}
OUTCOME_EVENTS = {"daily_outcome", "wechat_draft"}


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
    if append_rows:
        _append_jsonl(path, append_rows)
    report = _history_report(path, annotated, append_rows)
    return annotated, report


def append_source_history_outcomes(
    root: Path,
    topic_id: str,
    candidates: list[SourceCandidate],
    *,
    run_id: str,
    event: str,
    outcome_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Append source outcome rows for successful daily or publish stages."""

    if event not in OUTCOME_EVENTS:
        raise ValueError(f"Unsupported source history outcome event: {event}")
    path = root / "data" / "source_history" / f"{_safe_topic(topic_id)}.jsonl"
    records = _latest_records(path)
    rows = [
        _outcome_row(candidate, records, run_id, event, outcome)
        for candidate in candidates
        if (outcome := outcome_by_url.get(candidate.url)) is not None
    ]
    rows = [row for row in rows if row is not None]
    if rows:
        _append_jsonl(path, rows)
    return {"history_path": str(path), "event": event, "appended_count": len(rows)}


def append_source_history_outcome_records(
    root: Path,
    topic_id: str,
    sources: list[dict[str, Any]],
    *,
    run_id: str,
    event: str,
    outcome_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Append source outcome rows from serialized source candidates."""

    if event not in OUTCOME_EVENTS:
        raise ValueError(f"Unsupported source history outcome event: {event}")
    path = root / "data" / "source_history" / f"{_safe_topic(topic_id)}.jsonl"
    rows = [
        _outcome_record(row, run_id, event, outcome)
        for row in sources
        if (outcome := outcome_by_url.get(str(row.get("url") or ""))) is not None
    ]
    rows = [row for row in rows if row is not None]
    if rows:
        _append_jsonl(path, rows)
    return {"history_path": str(path), "event": event, "appended_count": len(rows)}


def is_reportable_source(source: SourceCandidate) -> bool:
    """Return whether a source should appear in today's report."""

    status = source.metadata.get("source_history", {}).get("status", "not_tracked")
    return str(status) in REPORTABLE_HISTORY_STATUSES


def source_family_key(source: SourceCandidate) -> str | None:
    """Return a stable source family key for history dedupe."""

    return _primary_source_family_key(source)


def source_family_keys(source: SourceCandidate) -> list[str]:
    """Return stable source-family aliases for history dedupe."""

    key = _primary_source_family_key(source)
    if source.source_type != SourceType.PAPER:
        return [key] if key else []

    title_key = _title_family_key(source.title)
    title_family = f"title:{title_key}" if title_key else None
    keys: list[str] = []
    if key and not _weak_paper_family_key(key):
        keys.append(key)
    if title_family:
        keys.append(title_family)
    if key and _weak_paper_family_key(key):
        keys.append(key)
    return keys


def _primary_source_family_key(source: SourceCandidate) -> str | None:
    """Return the strongest single source-family key for compatibility."""

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
    family_keys = source_family_keys(candidate)
    family_key = family_keys[0] if family_keys else None
    version = source_version(candidate)
    if candidate.metadata.get("relevance", {}).get("status") != "relevant":
        return (
            _with_history(candidate, "not_reported", family_key, family_keys, version, None),
            None,
        )
    if family_key is None:
        return _with_history(candidate, "not_tracked", None, [], version, None), None
    previous = _previous_record(records, family_keys)
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
        row = _history_row(
            candidate,
            family_key,
            family_keys,
            version,
            previous_version,
            status,
            run_id,
        )
    elif previous is not None and _should_refresh_alias_row(previous, family_keys, version):
        row = _history_row(
            candidate,
            family_key,
            _merged_family_keys(previous, family_keys),
            version or previous_version,
            previous_version,
            "alias_refresh",
            run_id,
        )
    previous_outcome = previous.get("outcome") if isinstance(previous, dict) else None
    if not isinstance(previous_outcome, dict):
        previous_outcome = None
    return (
        _with_history(
            candidate,
            status,
            family_key,
            family_keys,
            version,
            previous_version,
            previous_outcome=previous_outcome,
        ),
        row,
    )


def _previous_record(
    records: dict[str, dict[str, Any]],
    family_keys: list[str],
) -> dict[str, Any] | None:
    for key in family_keys:
        previous = records.get(key)
        if previous is not None:
            return previous
    return None


def _with_history(
    candidate: SourceCandidate,
    status: str,
    family_key: str | None,
    family_keys: list[str],
    version: str | None,
    previous_version: str | None,
    *,
    previous_outcome: dict[str, Any] | None = None,
) -> SourceCandidate:
    history = {
        "status": status,
        "family_key": family_key,
        "family_keys": family_keys,
        "version": version,
        "previous_version": previous_version,
    }
    if previous_outcome is not None:
        history["previous_outcome"] = previous_outcome
    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "source_history": history,
        },
    )


def _history_row(
    candidate: SourceCandidate,
    family_key: str,
    family_keys: list[str],
    version: str | None,
    previous_version: str | None,
    status: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "event": status,
        "family_key": family_key,
        "family_keys": family_keys,
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


def _outcome_row(
    candidate: SourceCandidate,
    records: dict[str, dict[str, Any]],
    run_id: str,
    event: str,
    outcome: dict[str, Any],
) -> dict[str, Any] | None:
    family_keys = source_family_keys(candidate)
    if not family_keys:
        return None
    previous = _previous_record(records, family_keys)
    previous_version = (
        str(previous.get("latest_version")) if previous and previous.get("latest_version") else None
    )
    version = source_version(candidate) or previous_version
    row = _history_row(
        candidate,
        family_keys[0],
        _merged_family_keys(previous, family_keys) if previous else family_keys,
        version,
        previous_version,
        event,
        run_id,
    )
    row["outcome"] = outcome
    return row


def _outcome_record(
    source: dict[str, Any],
    run_id: str,
    event: str,
    outcome: dict[str, Any],
) -> dict[str, Any] | None:
    metadata = source.get("metadata", {})
    history = metadata.get("source_history", {}) if isinstance(metadata, dict) else {}
    family_keys = _record_family_keys(history)
    if not family_keys:
        return None
    row = {
        "event": event,
        "family_key": family_keys[0],
        "family_keys": family_keys,
        "latest_version": history.get("version"),
        "previous_version": history.get("previous_version"),
        "title": source.get("title"),
        "url": source.get("url"),
        "canonical_id": source.get("canonical_id"),
        "source_type": source.get("source_type"),
        "source_name": source.get("source_name"),
        "published_at": source.get("published_at"),
        "run_id": run_id,
        "seen_at": datetime.now(UTC).isoformat(),
        "outcome": outcome,
    }
    return row


def _record_family_keys(history: object) -> list[str]:
    if not isinstance(history, dict):
        return []
    keys = history.get("family_keys")
    if isinstance(keys, list):
        values = [str(key) for key in keys if isinstance(key, str) and key]
    else:
        values = []
    family_key = history.get("family_key")
    if isinstance(family_key, str) and family_key:
        values.append(family_key)
    return list(dict.fromkeys(values))


def _latest_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        for family_key in _row_family_keys(row):
            records[family_key] = row
    return records


def _row_family_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    row_keys = row.get("family_keys")
    if isinstance(row_keys, list):
        keys.extend(str(key) for key in row_keys if isinstance(key, str) and key)
    family_key = row.get("family_key")
    if isinstance(family_key, str) and family_key:
        keys.append(family_key)
    return list(dict.fromkeys(keys))


def _should_refresh_alias_row(
    previous: dict[str, Any],
    family_keys: list[str],
    version: str | None,
) -> bool:
    previous_keys = set(_row_family_keys(previous))
    if version is not None and not previous.get("latest_version"):
        return True
    return any(key not in previous_keys and not _weak_paper_family_key(key) for key in family_keys)


def _merged_family_keys(previous: dict[str, Any], family_keys: list[str]) -> list[str]:
    return list(dict.fromkeys([*family_keys, *_row_family_keys(previous)]))


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
                    "family_keys": history.get("family_keys", []),
                    "version": history.get("version"),
                    "previous_outcome": history.get("previous_outcome"),
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


def _weak_paper_family_key(key: str) -> bool:
    return key.startswith(("url:", "corpusid:", "openalex:"))


def _title_family_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")


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
