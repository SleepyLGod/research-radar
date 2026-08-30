"""Private, append-only progress events for the macOS application bridge."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_radar.security.redaction import redact_text

_MAX_MESSAGE_CHARS = 500
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
    "email",
    "complete",
}
_STATUSES = {"running", "succeeded", "failed"}


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
        self.sequence += 1
        event = {
            "schema_version": 1,
            "request_id": self.request_id,
            "sequence": self.sequence,
            "emitted_at": self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "stage": stage,
            "status": status,
            "message": _safe_text(message) if message is not None else None,
            "completed": completed,
            "total": total,
            "delivery_channel": delivery_channel,
            "run_dir": _safe_text(run_dir) if run_dir is not None else None,
            "error": _safe_value(error) if error is not None else None,
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.write(descriptor, (json.dumps(event, ensure_ascii=False) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)


def _safe_text(value: str) -> str:
    redacted = redact_text(value)
    if len(redacted) <= _MAX_MESSAGE_CHARS:
        return redacted
    return f"{redacted[:_MAX_MESSAGE_CHARS]}...[truncated]"


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:20]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe_text(str(value))
