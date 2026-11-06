"""Read-only wire projection of a validated knowledge snapshot, without local paths."""

from __future__ import annotations

from typing import Any

from research_radar.analysis.knowledge_inputs import fingerprint


def knowledge_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Keep the existing small summary contract for saved and completed operations."""
    result = snapshot["organization"]
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "created_at": snapshot["created_at"],
        "input_fingerprint": snapshot["input_fingerprint"],
        "report_ids": [report["report_id"] for report in snapshot["inputs"]["reports"]],
        "provider": snapshot["provider"],
        "model": snapshot["model"],
        "paper_count": len(result["papers"]),
        "feature_count": sum(len(p["features"]) for p in result["papers"]),
        "group_count": len(result["groups"]),
        "relation_count": len(result["relations"]),
    }


def project_knowledge(topic_id: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Project stored classifications and immutable references; never interpret evidence."""
    if snapshot is None:
        return {"topic_id": topic_id, "current": None}
    inputs, organization = snapshot["inputs"], snapshot["organization"]
    identities = {paper["paper_key"]: paper for paper in inputs["papers"]}
    reports = {report["report_id"]: report for report in inputs["reports"]}
    return {
        "topic_id": topic_id,
        "current": knowledge_summary(snapshot),
        "graph": {
            "snapshot_id": snapshot["snapshot_id"],
            "research_question": snapshot["research_question"],
            "facets": organization["facets"],
            "groups": [
                {
                    "id": fingerprint(["knowledge-group:1", group["facet_id"], group["label"]]),
                    **group,
                }
                for group in organization["groups"]
            ],
            "papers": [
                {
                    **{
                        key: identities[paper["paper_key"]][key]
                        for key in ("paper_key", "paper_id", "version", "title")
                    },
                    "keywords": paper["keywords"],
                    "features": paper["features"],
                }
                for paper in organization["papers"]
            ],
            "relations": [
                {
                    "id": fingerprint(
                        [
                            "knowledge-relation:1",
                            *sorted([relation["source"], relation["target"]]),
                            relation["kind"],
                        ]
                    ),
                    **relation,
                }
                for relation in organization["relations"]
            ],
            "references": [
                {
                    **{
                        key: ref[key]
                        for key in (
                            "ref_id",
                            "paper_key",
                            "report_id",
                            "report_sha256",
                            "json_pointer",
                            "text",
                            "evidence",
                        )
                    },
                    "report_date": reports[ref["report_id"]]["report_date"],
                }
                for ref in inputs["references"]
            ],
        },
    }
