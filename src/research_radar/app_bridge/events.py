"""Private, append-only progress events for the macOS application bridge."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_radar.security.redaction import redact_text

_MAX_MESSAGE_CHARS = 500
# Apostrophes can occur inside URLs; never expose the remaining query suffix.
_TITLE_URL = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_EVENT_TYPES = {
    "started",
    "stage_changed",
    "progress",
    "delivery_result",
    "completed",
    "failed",
    "cancelled",
}
_STAGES = {
    "knowledge",
    "preflight",
    "topic_bootstrap",
    "discovery",
    "source_gist",
    "acquisition",
    "deep_reading",
    "anchor_repair",
    "verifier",
    "localization",
    "compose",
    "wechat_draft",
    "wechat_cover",
    "email",
    "complete",
}
_STATUSES = {"running", "succeeded", "failed"}
_PAPER_STATUSES = {
    "acquiring", "acquired", "acquisition_failed", "skipped", "reading", "read", "reading_failed",
}


@dataclass(frozen=True)
class PaperProgressV1:
    """Attempt-local source identity and observed work, never verification acceptance."""

    source_id: str
    title: str
    status: str

    def __post_init__(self) -> None:
        if (not isinstance(self.source_id, str) or len(self.source_id) != 64
                or any(char not in "0123456789abcdef" for char in self.source_id)):
            raise ValueError("Paper progress requires a hashed source identity.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Paper progress requires a title.")
        if not isinstance(self.status, str) or self.status not in _PAPER_STATUSES:
            raise ValueError("Unsupported paper progress status.")

    @property
    def stage(self) -> str:
        """Return the existing wire stage for this observed paper operation."""
        if self.status in {"reading", "read", "reading_failed"}:
            return "deep_reading"
        return "acquisition"


class EventWriter:
    """Append redacted, monotonic JSONL events for one engine request."""

    def __init__(
        self,
        path: Path,
        *,
        request_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.request_id = request_id
        self.sequence = 0
        self.last_stage: str | None = None
        self._clock = clock or (lambda: datetime.now(UTC))
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def write(
        self,
        event_type: str,
        *,
        stage: str | None,
        message: str | None,
        status: str | None = "running",
        completed: int | None = None,
        total: int | None = None,
        delivery_channel: str | None = None,
        run_dir: str | None = None,
        error: dict[str, Any] | None = None,
        paper: PaperProgressV1 | None = None,
    ) -> None:
        """Append and fsync one event before returning."""

        if event_type not in _EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {event_type}")
        if stage is not None and stage not in _STAGES:
            raise ValueError(f"Unsupported event stage: {stage}")
        if status is not None and status not in _STATUSES:
            raise ValueError(f"Unsupported event status: {status}")
        if delivery_channel not in {None, "wechat", "email"}:
            raise ValueError(f"Unsupported delivery channel: {delivery_channel}")
        if event_type == "failed" and error is None:
            raise ValueError("Failed events require a redacted error.")
        if event_type == "delivery_result" and delivery_channel is None:
            raise ValueError("Delivery events require a channel.")
        if paper is not None and (
            event_type != "progress" or status != "running" or stage != paper.stage
        ):
            raise ValueError("Paper progress requires a running progress event at its own stage.")
        if stage is not None and event_type in {"progress", "stage_changed"}:
            self.last_stage = stage
        self.sequence += 1
        event = {
            "schema_version": 1,
            "request_id": self.request_id,
            "sequence": self.sequence,
            "emitted_at": self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "stage": stage,
            "status": status,
            "message": safe_message(message) if message is not None else None,
            "completed": completed,
            "total": total,
            "delivery_channel": delivery_channel,
            "run_dir": safe_message(run_dir) if run_dir is not None else None,
            "error": _safe_value(error) if error is not None else None,
        }
        if paper is not None:
            event["paper"] = {
                "source_id": paper.source_id,
                "title": safe_message(_TITLE_URL.sub("[SOURCE_URL]", paper.title)),
                "status": paper.status,
            }
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.write(descriptor, (json.dumps(event, ensure_ascii=False) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)


def safe_message(value: str) -> str:
    """Redact before truncating to the wire protocol's inclusive message limit."""
    redacted = redact_text(value)
    if len(redacted) <= _MAX_MESSAGE_CHARS:
        return redacted
    suffix = "...[truncated]"
    return redacted[:_MAX_MESSAGE_CHARS - len(suffix)] + suffix


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return safe_message(value)
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:20]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return safe_message(str(value))
