"""Append-only progress audit events for long-running pipeline runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from research_radar.security.redaction import redact_text
from research_radar.storage.files import ensure_dir

MAX_PROGRESS_TEXT_CHARS = 500
MAX_PROGRESS_LIST_ITEMS = 20


class ProgressWriter:
    """Write redacted progress events to a JSONL artifact."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._started_at = time.monotonic()
        self._active_stages: dict[str, float] = {}
        self.events: list[dict[str, Any]] = []
        ensure_dir(path.parent)

    def record(self, stage: str, status: str, **metadata: Any) -> None:
        """Append one redacted progress event without interrupting the pipeline."""

        now = time.monotonic()
        duration = None
        if status in {"started", "created"}:
            self._active_stages[stage] = now
        elif stage in self._active_stages:
            duration = round(now - self._active_stages.pop(stage), 3)
        try:
            event = {
                **_redact_metadata(metadata),
                "stage": stage,
                "status": status,
                "elapsed_seconds": round(now - self._started_at, 3),
            }
            if duration is not None:
                event["duration_seconds"] = duration
            self.events.append(event)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError, RuntimeError):
            return


def _redact_metadata(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate(redact_text(value))
    if isinstance(value, dict):
        return {str(key): _redact_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_redact_metadata(item) for item in value[:MAX_PROGRESS_LIST_ITEMS]]
        if len(value) > MAX_PROGRESS_LIST_ITEMS:
            items.append(f"...[{len(value) - MAX_PROGRESS_LIST_ITEMS} more]")
        return items
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _truncate(redact_text(str(value)))


def _truncate(value: str) -> str:
    if len(value) <= MAX_PROGRESS_TEXT_CHARS:
        return value
    return f"{value[:MAX_PROGRESS_TEXT_CHARS]}...[truncated]"
