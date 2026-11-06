"""Version-scoped, source-addressable knowledge inputs from saved public deep reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_radar.exceptions import AnalysisError, OperationCancelled
from research_radar.models import SourceCandidate, SourceType
from research_radar.storage.paper_ledger import (
    LedgerReport,
    paper_id_for_url,
    read_saved_draft,
)
from research_radar.storage.source_history import source_version


class KnowledgeError(AnalysisError):
    """Saved knowledge materials, model result or storage violated its contract."""


def fingerprint(value: object) -> str:
    """Hash a deterministic JSON representation, independent of mapping insertion order."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class KnowledgeInput:
    """Public organization scope; private input paths never enter the model payload."""

    topic_id: str
    papers: list[dict[str, Any]]
    references: list[dict[str, Any]]
    reports: list[dict[str, str]]
    coverage: dict[str, int]

    def to_payload(self) -> dict[str, Any]:
        """Return the exact material set available for organization and later source lookup."""
        return {
            "topic_id": self.topic_id,
            "papers": self.papers,
            "references": self.references,
            "reports": self.reports,
            "coverage": self.coverage,
        }

    @property
    def fingerprint(self) -> str:
        """Identify all material dependencies, including coverage and report dates."""
        return fingerprint(self.to_payload())


def build_knowledge_input(
    workspace: Path,
    topic_id: str,
    reports: list[LedgerReport],
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> KnowledgeInput:
    """Adapt admitted public claims; never promote raw reader prose or title-only papers."""
    if not isinstance(topic_id, str) or not topic_id.strip():
        raise KnowledgeError("Knowledge topic must be non-empty.")
    selected: dict[str, LedgerReport] = {}
    for report in reports:
        if report.report_id in selected and selected[report.report_id] != report:
            raise KnowledgeError("Conflicting knowledge report references.")
        selected[report.report_id] = report
    papers: dict[str, dict[str, Any]] = {}
    references: list[dict[str, Any]] = []
    manifests: list[dict[str, str]] = []
    coverage = {
        "reports": len(selected),
        "deep_reads": 0,
        "excluded_claims": 0,
        "readings_without_public_claims": 0,
    }
    try:
        root = workspace.resolve(strict=True)
        for report in sorted(selected.values(), key=lambda r: (r.report_date, r.report_id)):
            if cancelled():
                raise OperationCancelled("Knowledge input read cancelled.")
            draft, digest = read_saved_draft(root, report.run_dir)
            if draft.get("topic_id") != topic_id or not isinstance(draft.get("sections"), list):
                raise KnowledgeError("Knowledge report topic or sections do not match.")
            manifests.append(
                {"report_id": report.report_id, "report_date": report.report_date, "sha256": digest}
            )
            for si, section in enumerate(draft["sections"]):
                metadata = section.get("metadata") if isinstance(section, dict) else None
                if not isinstance(metadata, dict) or metadata.get("kind") != "deep_reads":
                    continue
                entries = metadata.get("deep_reads")
                if not isinstance(entries, list):
                    raise KnowledgeError("Knowledge deep reads must be a list.")
                for ei, entry in enumerate(entries):
                    coverage["deep_reads"] += 1
                    _include_entry(entry, si, ei, report, digest, papers, references, coverage)
    except (OSError, ValueError, UnicodeError) as exc:
        raise KnowledgeError("Could not read a safe knowledge report.") from exc
    return KnowledgeInput(
        topic_id,
        sorted(papers.values(), key=lambda p: p["paper_key"]),
        references,
        manifests,
        coverage,
    )


def _source_identity(source: dict[str, Any]) -> tuple[str, str | None, str]:
    url = source.get("url")
    if not isinstance(url, str):
        raise KnowledgeError("Knowledge paper must have a public source URL.")
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise KnowledgeError("Knowledge paper must have a safe public source URL.")
    candidate = SourceCandidate(
        url=url, title="", source_name="saved_report", source_type=SourceType.PAPER
    )
    explicit = source.get("version")
    if explicit is not None and (not isinstance(explicit, str) or not explicit.strip()):
        raise KnowledgeError("Knowledge paper version must be a non-empty string or null.")
    inferred = source_version(candidate)
    if explicit and inferred and explicit != inferred:
        raise KnowledgeError("Knowledge paper version conflicts with its URL.")
    return paper_id_for_url(url), explicit or inferred, url


def _include_entry(
    entry: object,
    section: int,
    index: int,
    report: LedgerReport,
    digest: str,
    papers: dict[str, dict[str, Any]],
    references: list[dict[str, Any]],
    coverage: dict[str, int],
) -> None:
    if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
        raise KnowledgeError("Knowledge reading must identify its paper.")
    family, version, url = _source_identity(entry["source"])
    title = entry.get("title") or entry["source"].get("title")
    if not isinstance(title, str) or not title.strip():
        raise KnowledgeError("Knowledge paper title is missing.")
    claims = entry.get("claims")
    if not isinstance(claims, list):
        raise KnowledgeError("Knowledge public claims must be a list.")
    key = fingerprint(["paper-version:1", family, version])
    ids = []
    for ci, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise KnowledgeError("Knowledge public claim must be an object.")
        if claim.get("status", "supported") != "supported":
            coverage["excluded_claims"] += 1
            continue
        text, evidence = claim.get("text"), claim.get("evidence")
        if not isinstance(text, str) or not text.strip() or not evidence:
            coverage["excluded_claims"] += 1
            continue
        if not isinstance(evidence, list):
            raise KnowledgeError("Knowledge evidence must be a list.")
        public_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                raise KnowledgeError("Knowledge evidence must be an object.")
            efamily, eversion, _ = _source_identity({"url": item.get("source_url")})
            quote, location = item.get("quote"), item.get("location")
            if (
                efamily != family
                or (version and eversion and version != eversion)
                or not isinstance(quote, str)
                or not quote.strip()
                or not isinstance(location, str)
                or not location.strip()
            ):
                raise KnowledgeError("Knowledge evidence must belong to the paper and be anchored.")
            public_evidence.append(
                {"source_url": item["source_url"], "quote": quote, "location": location}
            )
        pointer = f"/sections/{section}/metadata/deep_reads/{index}/claims/{ci}"
        ref_id = fingerprint([report.report_id, digest, pointer])
        references.append(
            {
                "ref_id": ref_id,
                "paper_key": key,
                "report_id": report.report_id,
                "report_sha256": digest,
                "json_pointer": pointer,
                "text": text,
                "admission": "saved_public_claim",
                "evidence": public_evidence,
            }
        )
        ids.append(ref_id)
    if not ids:
        coverage["readings_without_public_claims"] += 1
        return
    paper = papers.setdefault(
        key,
        {
            "paper_key": key,
            "paper_id": family,
            "version": version,
            "title": title,
            "source_urls": [],
            "ref_ids": [],
        },
    )
    if url not in paper["source_urls"]:
        paper["source_urls"].append(url)
    paper["ref_ids"].extend(ids)
