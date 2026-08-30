import json
from pathlib import Path

import pytest

from research_radar.app_bridge.events import EventWriter


def test_event_writer_appends_monotonic_redacted_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="40a34269-4b4e-4093-9f31-4130ad8780de")

    writer.write("started", stage="preflight", message="token=abcdefghijklmnop")
    writer.write("progress", stage="preflight", message="Checking dependencies")

    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in events] == [1, 2]
    assert [event["kind"] for event in events] == ["started", "progress"]
    assert "abcdefghijklmnop" not in path.read_text(encoding="utf-8")
    assert "[REDACTED]" in events[0]["message"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_event_writer_fsyncs_started_before_returning(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr("research_radar.app_bridge.events.os.fsync", calls.append)
    writer = EventWriter(tmp_path / "events.jsonl", request_id="request")

    writer.write("started", stage="preflight", message="Ready")

    assert calls


def test_event_writer_rejects_metadata_that_overrides_canonical_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path, request_id="request")

    with pytest.raises(ValueError, match="request_id, sequence"):
        writer.write(
            "started",
            stage="preflight",
            message="Ready",
            request_id="attacker",
            sequence=99,
        )

    assert writer.sequence == 0
    assert not path.exists()
