"""Read-only material coverage for the last committed topic knowledge snapshot."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from research_radar.analysis.knowledge_inputs import (
    KnowledgeError,
    KnowledgeInput,
    build_knowledge_input,
    fingerprint,
)
from research_radar.storage.paper_ledger import LedgerReport


def knowledge_coverage(
    workspace: Path,
    topic_id: str,
    reports: list[LedgerReport],
    snapshot: dict[str, Any] | None,
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Compare admitted versioned papers and exact references, without changing either input."""
    try:
        materials = build_knowledge_input(workspace, topic_id, reports, cancelled=cancelled)
    except KnowledgeError:
        return {"status": "unknown", "papers": []}
    previous = KnowledgeInput(**snapshot["inputs"]) if snapshot is not None else None
    current = _papers(materials)
    old = _papers(previous) if previous else {}
    families = {paper["paper_id"] for paper, _ in old.values()}
    rows = []
    for key in sorted(current.keys() | old.keys()):
        paper, refs = current.get(key, old.get(key))
        if key not in current:
            status = "removed"
        elif key not in old:
            status = "new_version" if paper["paper_id"] in families else "new_paper"
        elif fingerprint(current[key]) != fingerprint(old[key]):
            status = "updated"
        else:
            status = "included"
        rows.append({
            "paper_key": key, "paper_id": paper["paper_id"], "version": paper["version"],
            "title": paper["title"], "status": status,
            "report_ids": sorted({ref["report_id"] for ref in refs}),
        })
    status = "unorganized" if snapshot is None else (
        "changes" if any(row["status"] != "included" for row in rows) else "current"
    )
    return {"status": status, "papers": rows}


def _papers(materials: KnowledgeInput) -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    references = {ref["ref_id"]: ref for ref in materials.references}
    return {
        paper["paper_key"]: (
            {**paper, "source_urls": sorted(paper["source_urls"]),
             "ref_ids": sorted(paper["ref_ids"])},
            sorted((references[ref] for ref in paper["ref_ids"]), key=lambda ref: ref["ref_id"]),
        )
        for paper in materials.papers
    }
