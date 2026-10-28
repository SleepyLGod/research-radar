"""Saved-report projection checks; no model, network or secret backend."""

import json
from pathlib import Path

import pytest

from research_radar.storage.paper_ledger import LedgerReport, build_paper_ledger


def saved_report(
    root: Path,
    name: str,
    date: str,
    *,
    topic: str = "memory",
    version: str = "v1",
    deep: bool = False,
) -> LedgerReport:
    run = root / "runs" / name
    run.mkdir(parents=True)
    source = {
        "title": "Memory evidence",
        "url": f"https://arxiv.org/abs/2601.01234{version}",
        "version": version or None,
        "source_type": "paper",
    }
    entry = {
        "title": source["title"],
        "source": source,
        "claims": [
            {
                "text": "Existing public result",
                "evidence": [
                    {"source_url": source["url"], "quote": "Existing evidence", "location": "p. 2"}
                ],
            }
        ],
    }
    sections = (
        [{"metadata": {"kind": "deep_reads", "deep_reads": [entry]}}]
        if deep
        else [{"metadata": {"kind": "new_updated_sources", "sources": [source]}}]
    )
    draft = {
        "title": "Offline report",
        "topic_id": topic,
        "digest": "",
        "lede": "",
        "sections": sections,
        "claims": [],
        "created_at": date + "T09:00:00+00:00",
    }
    (run / "article_draft.json").write_text(json.dumps(draft), encoding="utf-8")
    (run / "wechat.html").write_text("<p>已有报告 / existing report</p>", encoding="utf-8")
    return LedgerReport(report_id=name, report_date=date, run_dir=run)


def test_two_dates_merge_identity_but_keep_version_and_report_provenance(tmp_path: Path) -> None:
    first = saved_report(tmp_path, "first", "2026-10-26", deep=True)
    second = saved_report(tmp_path, "second", "2026-10-27", version="v2")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    ledger = build_paper_ledger(tmp_path, "memory", [second, first, first])
    assert ledger["topic_id"] == "memory"
    assert len(ledger["papers"]) == 1
    paper = ledger["papers"][0]
    assert len(paper["paper_id"]) == 64
    assert [(o["report_id"], o["version"], o["paper_index"]) for o in paper["occurrences"]] == [
        ("second", "v2", None),
        ("first", "v1", 0),
    ]
    assert paper["occurrences"][0]["source_url"].endswith("v2")
    assert ledger == build_paper_ledger(tmp_path, "memory", [first, second])
    assert all(path.read_bytes() == data for path, data in before.items())


def test_projection_matches_shared_swift_fixture_and_rebuilds_after_restart(tmp_path: Path) -> None:
    fixture = (
        Path(__file__).parents[1]
        / "apps/macos/ResearchRadar/Tests/Fixtures/Protocol/paper-ledger-result.json"
    )
    expected = json.loads(fixture.read_text())["paper_ledger"]
    first = saved_report(tmp_path, expected["report_ids"][0], "2026-10-26", deep=True)
    second = saved_report(tmp_path, expected["report_ids"][1], "2026-10-27", version="v2")
    assert build_paper_ledger(tmp_path, "memory", [first, second]) == expected
    assert build_paper_ledger(tmp_path, "memory", [second, first]) == expected


def test_duplicate_occurrences_prefer_public_reading_without_losing_source(tmp_path: Path) -> None:
    report = saved_report(tmp_path, "first", "2026-10-26", deep=True)
    path = report.run_dir / "article_draft.json"
    draft = json.loads(path.read_text())
    source = draft["sections"][0]["metadata"]["deep_reads"][0]["source"]
    mirror = {**source, "url": "https://arxiv.org/pdf/2601.01234v1"}
    draft["sections"].append({"metadata": {"kind": "references", "sources": [mirror]}})
    path.write_text(json.dumps(draft))
    occurrences = build_paper_ledger(tmp_path, "memory", [report])["papers"][0]["occurrences"]
    assert len(occurrences) == 1 and occurrences[0]["paper_index"] == 0
    assert occurrences[0]["source_url"] == "https://arxiv.org/abs/2601.01234v1"


@pytest.mark.parametrize(
    "url", ["file:///private/offline", "https://user:pass@example.org/paper", "javascript:alert(1)"]
)
def test_unsafe_links_are_not_exposed(tmp_path: Path, url: str) -> None:
    report = saved_report(tmp_path, "first", "2026-10-26")
    path = report.run_dir / "article_draft.json"
    value = json.loads(path.read_text())
    value["sections"][0]["metadata"]["sources"][0]["url"] = url
    path.write_text(json.dumps(value))
    assert not build_paper_ledger(tmp_path, "memory", [report])["papers"]


def test_mirror_identity_does_not_depend_on_title_or_report_order(tmp_path: Path) -> None:
    first = saved_report(tmp_path, "first", "2026-10-26")
    second = saved_report(tmp_path, "second", "2026-10-27")
    path = second.run_dir / "article_draft.json"
    value = json.loads(path.read_text())
    source = value["sections"][0]["metadata"]["sources"][0]
    source.update(title="An alternative display title", url="https://arxiv.org/pdf/2601.01234v1")
    path.write_text(json.dumps(value))
    ledger = build_paper_ledger(tmp_path, "memory", [first, second])
    assert len(ledger["papers"]) == 1
    assert (
        ledger["papers"][0]["paper_id"]
        == build_paper_ledger(tmp_path, "memory", [first])["papers"][0]["paper_id"]
    )
    source.update(url="https://arxiv.org/abs/2601.99999v1", title="Memory evidence")
    path.write_text(json.dumps(value))
    assert len(build_paper_ledger(tmp_path, "memory", [first, second])["papers"]) == 2


def test_unknown_version_and_non_paper_sources_are_not_guessed(tmp_path: Path) -> None:
    report = saved_report(tmp_path, "legacy", "2026-10-26", version="")
    path = report.run_dir / "article_draft.json"
    draft = json.loads(path.read_text())
    draft["sections"][0]["metadata"]["sources"].append(
        {
            "title": "Implementation",
            "url": "https://github.com/example/project",
            "source_type": "repository",
        }
    )
    path.write_text(json.dumps(draft))
    ledger = build_paper_ledger(tmp_path, "memory", [report])
    assert len(ledger["papers"]) == 1
    assert ledger["papers"][0]["occurrences"][0]["version"] is None


def test_query_identified_papers_are_distinct_and_references_are_included(tmp_path: Path) -> None:
    report = saved_report(tmp_path, "first", "2026-10-26")
    path = report.run_dir / "article_draft.json"
    value = json.loads(path.read_text())
    urls = [
        "https://openreview.net/forum?id=A",
        "https://openreview.net/forum?id=B",
        "https://example.org/paper?id=A&id=B",
        "https://example.org/paper?id=B&id=A",
        "https://example.org/paper?id=A+B",
        "https://example.org/paper?id=A%20B",
    ]
    value["sections"] = [
        {
            "metadata": {
                "kind": "references",
                "sources": [
                    {"title": "Query-identified paper", "url": url, "source_type": "paper"}
                    for url in urls
                ],
            }
        }
    ]
    path.write_text(json.dumps(value))
    ledger = build_paper_ledger(tmp_path, "memory", [report])
    assert len(ledger["papers"]) == 6
    assert all(paper["occurrences"][0]["paper_index"] is None for paper in ledger["papers"])


def test_seen_occurrences_reuse_recorded_paper_type_across_reports(tmp_path: Path) -> None:
    first = saved_report(tmp_path, "first", "2026-10-26")
    second = saved_report(tmp_path, "second", "2026-10-27")
    for report, kind in [(first, "references"), (second, "seen_before")]:
        source = {"title": "ACL paper", "url": "https://aclanthology.org/2026.acl-long.1/"}
        if kind == "references":
            source["source_type"] = "paper"
        path = report.run_dir / "article_draft.json"
        value = json.loads(path.read_text())
        value["sections"] = [{"metadata": {"kind": kind, "sources": [source]}}]
        path.write_text(json.dumps(value))
    ledger = build_paper_ledger(tmp_path, "memory", [second, first])
    assert len(ledger["papers"]) == 1
    assert [item["report_date"] for item in ledger["papers"][0]["occurrences"]] == [
        "2026-10-27",
        "2026-10-26",
    ]


def test_unreadable_and_other_topic_reports_do_not_erase_valid_records(tmp_path: Path) -> None:
    valid = saved_report(tmp_path, "valid", "2026-10-26")
    other = saved_report(tmp_path, "other", "2026-10-27", topic="different")
    missing = LedgerReport("missing", "2026-10-28", tmp_path / "runs/missing")
    ledger = build_paper_ledger(tmp_path, "memory", [valid, other, missing])
    assert len(ledger["papers"]) == 1
    assert ledger["unavailable_reports"] == ["missing", "other"]


@pytest.mark.parametrize("kind", ["outside", "symlink"])
def test_report_paths_cannot_escape_the_workspace(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = saved_report(tmp_path / "outside", "private", "2026-10-26")
    reference = outside
    if kind == "symlink":
        link = workspace / "linked"
        link.symlink_to(outside.run_dir, target_is_directory=True)
        reference = LedgerReport("private", "2026-10-26", link)
    ledger = build_paper_ledger(workspace, "memory", [reference])
    assert ledger["papers"] == []
    assert ledger["unavailable_reports"] == ["private"]
