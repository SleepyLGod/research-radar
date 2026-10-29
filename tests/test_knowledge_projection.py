"""Read-only native classification projection; no new model or report mutation."""

from __future__ import annotations

import json
from pathlib import Path

from research_radar.analysis.knowledge_inputs import fingerprint
from research_radar.app_bridge.handlers import _knowledge_projection


def test_snapshot_projects_classification_and_exact_source_material() -> None:
    fixture = Path(__file__).parents[1] / (
        "apps/macos/ResearchRadar/Tests/Fixtures/Protocol/topic-knowledge-graph-result.json"
    )
    expected = json.loads(fixture.read_text())["knowledge"]
    current, graph = expected["current"], expected["graph"]
    snapshot = {
        **current,
        "research_question": graph["research_question"],
        "inputs": {
            "reports": [{"report_id": current["report_ids"][0], "report_date": "2026-10-24"}],
            "papers": [
                {key: p[key] for key in ("paper_key", "paper_id", "version", "title")}
                for p in graph["papers"]
            ],
            "references": [
                {key: value for key, value in r.items() if key != "report_date"}
                for r in graph["references"]
            ],
        },
        "organization": {
            "facets": graph["facets"],
            "groups": [
                {key: value for key, value in g.items() if key != "id"} for g in graph["groups"]
            ],
            "papers": [
                {key: p[key] for key in ("paper_key", "keywords", "features")}
                for p in graph["papers"]
            ],
            "relations": [],
        },
    }
    before = json.dumps(snapshot, sort_keys=True)
    result = _knowledge_projection("memory", snapshot)
    assert result == {**expected, "graph": {**graph, "relations": []}}
    assert json.dumps(snapshot, sort_keys=True) == before
    assert len(result["graph"]["papers"]) == 2  # Multi-label memberships do not duplicate papers.
    assert "run_dir" not in json.dumps(result) and "snapshot_path" not in json.dumps(result)


def test_missing_snapshot_keeps_legacy_empty_response() -> None:
    assert _knowledge_projection("memory", None) == {"topic_id": "memory", "current": None}


def test_saved_relations_keep_both_sources_and_stable_undirected_identity() -> None:
    snapshot = _relation_snapshot()
    before = json.dumps(snapshot, sort_keys=True)
    relation = snapshot["organization"]["relations"][0]
    expected_id = fingerprint(
        [
            "knowledge-relation:1",
            *sorted([relation["source"], relation["target"]]),
            relation["kind"],
        ]
    )
    projected = _knowledge_projection("memory", snapshot)
    assert projected["graph"].get("relations") == [{"id": expected_id, **relation}]
    assert projected["current"]["relation_count"] == 1
    assert json.dumps(snapshot, sort_keys=True) == before
    references = {r["ref_id"]: r for r in projected["graph"]["references"]}
    assert {references[ref]["paper_key"] for ref in relation["ref_ids"]} == {
        relation["source"], relation["target"]
    }
    relation["source"], relation["target"] = relation["target"], relation["source"]
    reversed_projection = _knowledge_projection("memory", snapshot)
    assert reversed_projection["graph"]["relations"][0]["id"] == expected_id


def test_empty_saved_relations_are_explicit_not_reconstructed_from_groups() -> None:
    snapshot = _relation_snapshot()
    snapshot["organization"]["relations"] = []
    result = _knowledge_projection("memory", snapshot)
    assert result["graph"].get("relations") == []
    assert result["graph"]["groups"]


def _relation_snapshot() -> dict:
    fixture = Path(__file__).parents[1] / (
        "apps/macos/ResearchRadar/Tests/Fixtures/Protocol/topic-knowledge-graph-result.json"
    )
    value = json.loads(fixture.read_text())["knowledge"]
    graph = value["graph"]
    first, second = graph["papers"]
    return {
        **value["current"],
        "research_question": graph["research_question"],
        "inputs": {
            "reports": [
                {"report_id": value["current"]["report_ids"][0], "report_date": "2026-10-24"}
            ],
            "papers": graph["papers"],
            "references": graph["references"],
        },
        "organization": {
            "facets": graph["facets"],
            "groups": [{k: v for k, v in group.items() if k != "id"} for group in graph["groups"]],
            "papers": graph["papers"],
            "relations": [{
                "source": first["paper_key"], "target": second["paper_key"],
                "kind": "shared_problem", "basis": "synthesis",
                "reason": "Offline relation fixture; not a research conclusion.",
                "ref_ids": [ref["ref_id"] for ref in graph["references"]],
            }],
        },
    }
