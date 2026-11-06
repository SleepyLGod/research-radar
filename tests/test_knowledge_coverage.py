"""Material coverage is a local comparison, not another model judgment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_radar.application.knowledge_coverage import knowledge_coverage
from research_radar.exceptions import OperationCancelled
from research_radar.storage.paper_ledger import LedgerReport
from tests.test_topic_knowledge import change_entry, report, run


def coverage(root: Path, reports: list[LedgerReport], snapshot=None, **kwargs):
    return knowledge_coverage(root, "memory", reports, snapshot, **kwargs)


def test_coverage_keeps_versions_occurrences_and_originals(tmp_path: Path) -> None:
    first = report(tmp_path, "one")
    snapshot = run(tmp_path, [first]).snapshot
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert coverage(tmp_path, [first], snapshot)["status"] == "current"
    second = report(tmp_path, "two", version="v2")
    value = coverage(tmp_path, [first, second], snapshot)
    assert value["status"] == "changes"
    assert {p["version"]: p["status"] for p in value["papers"]} == {
        "v1": "included", "v2": "new_version",
    }
    assert next(p for p in value["papers"] if p["version"] == "v2")["report_ids"] == ["two"]
    assert str(tmp_path) not in json.dumps(value)
    assert all(p.read_bytes() == data for p, data in before.items())
    refreshed = run(tmp_path, [first, second]).snapshot
    assert coverage(tmp_path, [second, first], refreshed)["status"] == "current"


def test_new_paper_and_new_occurrence_are_different(tmp_path: Path) -> None:
    first = report(tmp_path, "one")
    snapshot = run(tmp_path, [first]).snapshot
    repeat = report(tmp_path, "repeat")
    value = coverage(tmp_path, [repeat, first], snapshot)
    assert len(value["papers"]) == 1
    assert value["papers"][0]["status"] == "updated"
    assert set(value["papers"][0]["report_ids"]) == {"one", "repeat"}
    other = report(tmp_path, "other")
    path = other.run_dir / "article_draft.json"
    path.write_text(path.read_text().replace("2601.01234", "2601.99999"))
    value = coverage(tmp_path, [first, other], snapshot)
    assert sorted(p["status"] for p in value["papers"]) == ["included", "new_paper"]


def test_source_only_report_does_not_make_graph_stale(tmp_path: Path) -> None:
    first = report(tmp_path, "one")
    snapshot = run(tmp_path, [first]).snapshot
    source_only = report(tmp_path, "links")
    change_entry(source_only, {"claims": []})
    assert coverage(tmp_path, [first, source_only], snapshot)["status"] == "current"
    empty = coverage(tmp_path, [source_only])
    assert empty == {"status": "unorganized", "papers": []}


def test_changed_evidence_or_missing_material_is_not_current(tmp_path: Path) -> None:
    first = report(tmp_path, "one")
    snapshot = run(tmp_path, [first]).snapshot
    change_entry(first, {"title": "Corrected public title"})
    assert coverage(tmp_path, [first], snapshot)["papers"][0]["status"] == "updated"
    missing = LedgerReport("missing", "2026-11-07", tmp_path / "missing")
    assert coverage(tmp_path, [first, missing], snapshot) == {"status": "unknown", "papers": []}
    wrong = report(tmp_path, "wrong", topic="other")
    assert coverage(tmp_path, [wrong], snapshot)["status"] == "unknown"


def test_removed_scope_and_no_snapshot_are_explicit(tmp_path: Path) -> None:
    first = report(tmp_path, "one")
    assert coverage(tmp_path, [first])["status"] == "unorganized"
    snapshot = run(tmp_path, [first]).snapshot
    value = coverage(tmp_path, [], snapshot)
    assert value["status"] == "changes"
    assert value["papers"][0]["status"] == "removed"


def test_cancel_is_not_a_successful_unknown_read(tmp_path: Path) -> None:
    with pytest.raises(OperationCancelled):
        coverage(tmp_path, [report(tmp_path, "one")], cancelled=lambda: True)
