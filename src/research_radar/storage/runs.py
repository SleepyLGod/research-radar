"""Run directory management."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from research_radar.models import RunManifest
from research_radar.storage.files import ensure_dir, write_json


def make_run_id(topic_id: str, *, now: datetime | None = None) -> str:
    """Return a unique run-attempt id based on local wall-clock time and topic."""

    timestamp = now or datetime.now().astimezone()
    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "-", topic_id).strip("-")
    attempt_id = timestamp.strftime("%H%M%S%f")
    return f"{timestamp.date().isoformat()}-{attempt_id}-{safe_topic}"


def create_run_dir(base_dir: Path, topic_id: str, mode: str) -> tuple[Path, RunManifest]:
    """Create a run directory and write its initial manifest."""

    timestamp = datetime.now().astimezone()
    run_id = make_run_id(topic_id, now=timestamp)
    run_dir = ensure_dir(base_dir / "runs" / run_id)
    run_dir.chmod(0o700)
    manifest = RunManifest(
        run_id=run_id,
        topic_id=topic_id,
        mode=mode,
        report_date=timestamp.date().isoformat(),
        attempt_id=timestamp.strftime("%H%M%S%f"),
    )
    write_json(run_dir / "manifest.json", manifest)
    return run_dir, manifest


def update_manifest(run_dir: Path, manifest: RunManifest) -> None:
    """Write a run manifest."""

    write_json(run_dir / "manifest.json", manifest)
