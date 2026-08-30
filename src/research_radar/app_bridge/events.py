"""Private, append-only progress events for the macOS application bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from research_radar.security.redaction import redact_text

_MAX_MESSAGE_CHARS = 500
_RESERVED_EVENT_KEYS = frozenset(
    {"schema_version", "request_id", "sequence", "kind", "stage", "message"}
)


class EventWriter:
    """Append redacted, monotonic JSONL events for one engine request."""

    def __init__(self, path: Path, *, request_id: str) -> None:
        self.path = path
        self.request_id = request_id
        self.sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def write(self, kind: str, *, stage: str, message: str, **metadata: Any) -> None:
        """Append and fsync one event before returning."""

        reserved = _RESERVED_EVENT_KEYS.intersection(metadata)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"Event metadata cannot override reserved fields: {names}")
        self.sequence += 1
        event = {
            "schema_version": 1,
            "request_id": self.request_id,
            "sequence": self.sequence,
            "kind": kind,
            "stage": stage,
            "message": _safe_text(message),
            **{key: _safe_value(value) for key, value in metadata.items()},
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
