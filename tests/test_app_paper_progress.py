"""Offline checks for typed, attempt-local paper progress forwarding."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_radar.app_bridge.events import EventWriter
from research_radar.app_bridge.handlers import _progress_listener
from research_radar.pipeline.progress import ProgressWriter

SOURCE_URL = "https://example.org/papers/memory"
SOURCE_ID = hashlib.sha256(SOURCE_URL.encode()).hexdigest()
FIXTURE = Path("apps/macos/ResearchRadar/Tests/Fixtures/Protocol/paper-progress-event.json")


@pytest.mark.parametrize(("stage", "status", "expected"), [
    ("ingestion", "started", "acquiring"),
    ("ingestion", "succeeded", "acquired"),
    ("ingestion", "failed", "acquisition_failed"),
    ("paper_text_quality", "passed", "acquired"),
    ("paper_text_quality", "failed", "skipped"),
    ("reader", "started", "reading"),
    ("reader", "succeeded", "read"),
    ("reader", "failed", "reading_failed"),
])
def test_existing_events_forward_paper_state_without_deciding_job_outcome(
    tmp_path: Path, stage: str, status: str, expected: str,
) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    progress = ProgressWriter(tmp_path / "run_progress.jsonl", listener=_progress_listener(writer))
    progress.record(stage, status, source_url=SOURCE_URL, source_title="Memory paper",
                    error="Not a public error message", claim_count=17)
    event = json.loads(path.read_text())
    assert event["paper"] == {"source_id": SOURCE_ID, "title": "Memory paper", "status": expected}
    assert event["type"] == "progress" and event["status"] == "running"
    assert event["completed"] is None and event["total"] is None
    assert event["error"] is None
    assert "Not a public error message" not in path.read_text()
    assert SOURCE_URL not in path.read_text()


def test_paper_progress_matches_the_swift_canonical_fixture(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="0b5f8bc4-f934-4d86-b513-265e950fb44c",
                         clock=lambda: datetime(2026, 10, 27, 9, tzinfo=UTC))
    progress = ProgressWriter(tmp_path / "run_progress.jsonl", listener=_progress_listener(writer))
    progress.record("reader", "started", source_url=SOURCE_URL,
                    source_title="Agent memory / 智能体记忆")
    assert json.loads(path.read_text()) == json.loads(FIXTURE.read_text())


def test_paper_titles_are_redacted_and_bounded_before_entering_the_wire(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    progress = ProgressWriter(tmp_path / "run_progress.jsonl", listener=_progress_listener(writer))
    progress.record("reader", "started", source_url=SOURCE_URL,
                    source_title="token=offline-private-canary\n" + "x" * 1000)
    event = json.loads(path.read_text())
    assert "offline-private-canary" not in path.read_text()
    assert 0 < len(event["paper"]["title"]) <= 500
    assert "[REDACTED]" in event["paper"]["title"]


@pytest.mark.parametrize("metadata", [
    {"source_url": SOURCE_URL}, {"source_title": "No source identity"},
    {"source_url": "", "source_title": "Empty identity"},
    {"source_url": SOURCE_URL, "source_title": {}},
])
def test_incomplete_paper_metadata_does_not_invent_a_row(
    tmp_path: Path, metadata: dict[str, object],
) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    _progress_listener(writer)({"stage": "reader", "status": "started", **metadata})
    assert "paper" not in json.loads(path.read_text())


def test_source_identity_is_computed_before_audit_url_truncation(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    progress = ProgressWriter(tmp_path / "run_progress.jsonl", listener=_progress_listener(writer))
    prefix = "https://example.org/papers/" + "a" * 600
    for suffix in ["one", "two"]:
        progress.record("reader", "started", source_url=prefix + suffix, source_title=suffix)
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(events) == 2
    assert events[0]["paper"]["source_id"] != events[1]["paper"]["source_id"]
    assert events[0]["paper"]["source_id"] == hashlib.sha256((prefix + "one").encode()).hexdigest()


def test_source_identity_is_not_changed_by_secret_redaction(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    progress = ProgressWriter(tmp_path / "run_progress.jsonl", listener=_progress_listener(writer))
    for number in [1, 2]:
        url = f"https://example.org/paper?token=private-canary-{number}"
        progress.record("reader", "started", source_url=url, source_title="Paper")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert events[0]["paper"]["source_id"] != events[1]["paper"]["source_id"]
    assert "private-canary" not in path.read_text()


@pytest.mark.parametrize("url", [
    "https://example.org/paper?session=private-canary",
    "https://example.org/O'Reilly?session=private-canary",
    "https://example.org/paper?label=O'Reilly&session=private-canary",
])
def test_raw_urls_inside_titles_cannot_reach_paper_progress(tmp_path: Path, url: str) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    progress = ProgressWriter(tmp_path / "run_progress.jsonl", listener=_progress_listener(writer))
    progress.record("reader", "started", source_url=SOURCE_URL, source_title=f"Paper {url}")
    text = path.read_text()
    assert "private-canary" not in text and "https://" not in text
    assert json.loads(text)["paper"]["title"] == "Paper [SOURCE_URL]"


def test_real_pipeline_events_reach_bridge_without_changing_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from test_pipeline_fake import (
        FakeConnector,
        SequenceProvider,
        _complete_paper_fixture_text,
        _deep_reading_json,
    )

    from research_radar.config import parse_config
    from research_radar.models import Artifact
    from research_radar.pipeline import daily

    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    monkeypatch.setattr(daily, "ingest_source", lambda source, _: Artifact(
        source=source, text=_complete_paper_fixture_text(),
    ))
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="offline")
    run = daily.run_daily(tmp_path / "data", config, "memory", [FakeConnector()],
                          deep_reader=SequenceProvider([_deep_reading_json()]), deep_limit=1,
                          progress_listener=_progress_listener(writer))
    papers = [e["paper"] for line in path.read_text().splitlines()
              if (e := json.loads(line)).get("paper")]
    assert [p["status"] for p in papers] == ["acquiring", "acquired", "acquired", "reading", "read"]
    assert len({p["source_id"] for p in papers}) == 1
    assert all(p["title"] == "A careful paper" for p in papers)
    # An advisory listener must not alter report content or the evidence policy.
    baseline = daily.run_daily(tmp_path / "baseline", config, "memory", [FakeConnector()],
                               deep_reader=SequenceProvider([_deep_reading_json()]), deep_limit=1)
    observed = json.loads((run / "article_draft.json").read_text())
    original = json.loads((baseline / "article_draft.json").read_text())
    # Separate runs legitimately have different creation timestamps.
    observed.pop("created_at")
    original.pop("created_at")
    assert observed == original
    for artifact in ("wechat.html", "daily.md"):
        assert (run / artifact).read_bytes() == (baseline / artifact).read_bytes()
