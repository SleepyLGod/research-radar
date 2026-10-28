"""Rebuildable, topic-scoped paper provenance from immutable public reports."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_radar.exceptions import OperationCancelled
from research_radar.models import SourceCandidate, SourceType
from research_radar.security.redaction import redact_text
from research_radar.storage.source_history import source_family_key, source_version


@dataclass(frozen=True)
class LedgerReport:
    """One saved report reference; dates describe inclusion, not publication."""

    report_id: str
    report_date: str
    run_dir: Path

    def __post_init__(self) -> None:
        if (
            not self.report_id
            or date.fromisoformat(self.report_date).isoformat() != self.report_date
        ):
            raise ValueError("Invalid ledger report reference.")


def build_paper_ledger(
    workspace: Path,
    topic_id: str,
    reports: list[LedgerReport],
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Read only saved public drafts; never resolve secrets or infer paper relations."""
    root = workspace.resolve(strict=True)
    references: dict[str, LedgerReport] = {}
    for report in reports:
        previous = references.get(report.report_id)
        if previous is not None and previous != report:
            raise ValueError("Conflicting ledger report references.")
        references[report.report_id] = report
    papers: dict[str, dict[str, Any]] = {}
    source_records: list[tuple[LedgerReport, dict[str, Any]]] = []
    unavailable: list[str] = []
    for report in sorted(references.values(), key=lambda r: (r.report_date, r.report_id)):
        if cancelled():
            raise OperationCancelled("Paper ledger read cancelled.")
        try:
            draft = _read_draft(root, report.run_dir)
            if draft.get("topic_id") != topic_id or not isinstance(draft.get("sections"), list):
                raise ValueError("Report topic or sections do not match.")
        except (OSError, ValueError, UnicodeError):
            unavailable.append(report.report_id)
            continue
        reading_index = 0
        for section in draft["sections"]:
            metadata = section.get("metadata") if isinstance(section, dict) else None
            if not isinstance(metadata, dict):
                continue
            kind = metadata.get("kind")
            if kind == "deep_reads":
                entries = metadata.get("deep_reads", [])
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    index = reading_index
                    reading_index += 1
                    if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
                        continue
                    claims = entry.get("claims")
                    public = (
                        isinstance(claims, list)
                        and bool(claims)
                        and all(
                            isinstance(claim, dict)
                            and isinstance(claim.get("text"), str)
                            and bool(claim["text"].strip())
                            for claim in claims
                        )
                    )
                    _include(
                        papers,
                        report,
                        entry["source"],
                        index if public else None,
                        title=entry.get("title"),
                    )
            elif kind in {"new_updated_sources", "seen_before", "references"}:
                sources = metadata.get("sources", [])
                if isinstance(sources, list):
                    for source in sources:
                        if isinstance(source, dict):
                            source_records.append((report, source))
    # Legacy seen entries omit source_type; reuse explicit paper identity from any report.
    known_papers = set(papers)
    for _, source in source_records:
        if _is_paper(source) and (url := _safe_url(source.get("url"))):
            known_papers.add(_paper_id(url))
    for report, source in source_records:
        if (url := _safe_url(source.get("url"))) and _paper_id(url) in known_papers:
            _include(papers, report, source, None)
    result = []
    for paper in papers.values():
        occurrences = sorted(
            paper["occurrences"].values(),
            key=lambda o: (o["report_date"], o["report_id"], o["occurrence_id"]),
            reverse=True,
        )
        result.append(
            {
                "paper_id": paper["paper_id"],
                "title": occurrences[0]["title"],
                "occurrences": occurrences,
            }
        )
    result.sort(key=lambda p: (p["occurrences"][0]["report_date"], p["paper_id"]), reverse=True)
    return {
        "schema_version": 1,
        "topic_id": topic_id,
        "report_ids": sorted(references),
        "papers": result,
        "unavailable_reports": sorted(unavailable),
    }


def _read_draft(root: Path, run: Path) -> dict[str, Any]:
    resolved = run.resolve(strict=True)
    resolved.relative_to(root)
    parent = run.absolute()
    while parent.resolve() != root:
        if parent.is_symlink() or parent.parent == parent:
            raise ValueError("Ledger run must not traverse a symlink.")
        parent = parent.parent
    path = resolved / "article_draft.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Ledger draft must be a regular file.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Ledger draft must be an object.")
    return value


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme.lower() not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
        ):
            return None
    except ValueError:
        return None
    return value


def _is_paper(source: dict[str, Any]) -> bool:
    if source.get("source_type") == "paper" or source.get("source_group") == "research_papers":
        return True
    url = _safe_url(source.get("url"))
    if url is None:
        return False
    key = source_family_key(
        SourceCandidate(
            url=url,
            title="",
            source_name="saved_report",
            source_type=SourceType.PAPER,
        )
    )
    return bool(key and key.startswith(("arxiv:", "doi:")))


def _include(
    papers: dict[str, dict[str, Any]],
    report: LedgerReport,
    source: dict[str, Any],
    paper_index: int | None,
    *,
    title: object = None,
) -> None:
    url = _safe_url(source.get("url"))
    raw_title = title or source.get("title")
    if url is None or not isinstance(raw_title, str) or not raw_title.strip():
        return
    candidate = SourceCandidate(
        url=url,
        title=raw_title,
        source_name="saved_report",
        source_type=SourceType.PAPER,
    )
    paper_id = _paper_id(url)
    explicit = source.get("version")
    version = (
        explicit if isinstance(explicit, str) and explicit.strip() else source_version(candidate)
    )
    title_text = redact_text(re.sub(r"https?://[^\s<>\"]+", "[SOURCE_URL]", raw_title))[
        :500
    ].strip()
    occurrence_id = hashlib.sha256(
        json.dumps([report.report_id, paper_id, version]).encode()
    ).hexdigest()
    paper = papers.setdefault(paper_id, {"paper_id": paper_id, "occurrences": {}})
    occurrence = {
        "occurrence_id": occurrence_id,
        "report_id": report.report_id,
        "report_date": report.report_date,
        "version": version,
        "source_url": url,
        "title": title_text,
        "paper_index": paper_index,
    }
    previous = paper["occurrences"].get(occurrence_id)
    if previous is None or (previous["paper_index"] is None and paper_index is not None):
        paper["occurrences"][occurrence_id] = occurrence


def _paper_id(url: str) -> str:
    candidate = SourceCandidate(
        url=url,
        title="",
        source_name="saved_report",
        source_type=SourceType.PAPER,
    )
    key = source_family_key(candidate)
    # Generic URL normalization drops all queries, but OpenReview's paper ID lives there.
    # Preserve query identity conservatively rather than merging unrelated papers.
    query = urlsplit(url).query
    if key and key.startswith("url:") and query:
        key += "?" + query
    return hashlib.sha256(f"paper-ledger:1:{key}".encode()).hexdigest()
