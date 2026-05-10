"""Run directory management."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from research_radar.models import RunManifest
from research_radar.storage.files import ensure_dir, write_json


def make_run_id(topic_id: str, *, now: datetime | None = None) -> str:
    """Return a stable run id based on date and topic."""

    timestamp = now or datetime.now(UTC)
    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "-", topic_id).strip("-")
    return f"{timestamp.date().isoformat()}-{safe_topic}"


def create_run_dir(base_dir: Path, topic_id: str, mode: str) -> tuple[Path, RunManifest]:
    """Create a run directory and write its initial manifest."""

    run_id = make_run_id(topic_id)
    run_dir = ensure_dir(base_dir / "runs" / run_id)
    manifest = RunManifest(run_id=run_id, topic_id=topic_id, mode=mode)
    write_json(run_dir / "manifest.json", manifest)
    return run_dir, manifest


def update_manifest(run_dir: Path, manifest: RunManifest) -> None:
    """Write a run manifest."""

    write_json(run_dir / "manifest.json", manifest)
