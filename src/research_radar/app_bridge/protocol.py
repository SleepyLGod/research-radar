"""Strict Task 1 request protocol for the macOS application bridge."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from research_radar.app_bridge import BRIDGE_SCHEMA_VERSION

_REQUEST_FIELDS = {
    "schema_version",
    "request_id",
    "command",
    "created_at",
    "app_support_root",
    "config_path",
    "payload",
}
_PREFLIGHT_FIELDS = {"live_probe"}
_SECRET_VALUE_FIELDS = {
    "api_key",
    "password",
    "secret_value",
    "token",
    "api_key_value",
    "token_value",
    "authorization",
    "cookie",
}


class ProtocolError(ValueError):
    """Raised when an App bridge request violates the versioned contract."""


@dataclass(frozen=True, slots=True)
class PreflightPayloadV1:
    """Local-only Task 1 preflight payload."""

    live_probe: bool


@dataclass(frozen=True, slots=True)
class EngineRequestV1:
    """Validated Task 1 engine request."""

    schema_version: int
    request_id: str
    command: str
    created_at: str
    app_support_root: Path
    config_path: Path | None
    payload: PreflightPayloadV1


def load_request(path: Path, *, job_dir: Path) -> EngineRequestV1:
    """Load and strictly validate one local foundation request."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Request JSON could not be read.") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Request JSON must be an object.")
    _reject_secret_fields(value)
    unknown = set(value) - _REQUEST_FIELDS
    if unknown:
        raise ProtocolError(f"Unknown request field: {sorted(unknown)[0]}")
    missing = _REQUEST_FIELDS - set(value)
    if missing:
        raise ProtocolError(f"Missing request field: {sorted(missing)[0]}")

    schema_version = _require_int(value, "schema_version")
    if schema_version != BRIDGE_SCHEMA_VERSION:
        raise ProtocolError(f"Unsupported schema version: {schema_version}")
    command = _require_str(value, "command")
    if command != "preflight":
        raise ProtocolError(f"Unsupported command: {command}")

    private_job = _resolve_private_directory(job_dir, label="job directory")
    request_id = _require_str(value, "request_id")
    try:
        UUID(request_id)
    except ValueError as exc:
        raise ProtocolError("request_id must be a UUID.") from exc
    if request_id != private_job.name:
        raise ProtocolError("request_id must match the job directory name.")

    app_root = _resolve_private_directory(
        Path(_require_str(value, "app_support_root")), label="app_support_root"
    )
    try:
        private_job.relative_to(app_root)
    except ValueError as exc:
        raise ProtocolError("job directory must stay within app_support_root.") from exc

    config_path = _parse_optional_contained_path(value["config_path"], app_root)
    payload = _parse_preflight_payload(value["payload"])
    return EngineRequestV1(
        schema_version=schema_version,
        request_id=request_id,
        command=command,
        created_at=_require_str(value, "created_at"),
        app_support_root=app_root,
        config_path=config_path,
        payload=payload,
    )


def _parse_preflight_payload(value: Any) -> PreflightPayloadV1:
    if not isinstance(value, dict):
        raise ProtocolError("preflight payload must be an object.")
    unknown = set(value) - _PREFLIGHT_FIELDS
    if unknown:
        raise ProtocolError(f"Unknown preflight field: {sorted(unknown)[0]}")
    if set(value) != _PREFLIGHT_FIELDS:
        raise ProtocolError("preflight payload requires live_probe.")
    live_probe = value["live_probe"]
    if not isinstance(live_probe, bool):
        raise ProtocolError("live_probe must be a boolean.")
    if live_probe:
        raise ProtocolError("Task 1 preflight must not perform a live probe.")
    return PreflightPayloadV1(live_probe=False)


def _parse_optional_contained_path(value: Any, app_root: Path) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError("config_path must be null or an absolute path.")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ProtocolError("config_path must be null or an absolute path.")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(app_root)
    except (OSError, ValueError) as exc:
        raise ProtocolError("config_path must stay within app_support_root.") from exc
    if not resolved.is_file():
        raise ProtocolError("config_path must identify a regular file.")
    return resolved


def _resolve_private_directory(path: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise ProtocolError(f"{label} is unavailable.") from exc
    if not resolved.is_dir():
        raise ProtocolError(f"{label} must be a directory.")
    if metadata.st_uid != os.getuid():
        raise ProtocolError(f"{label} must be owned by the current user.")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ProtocolError(f"{label} must be owner-only.")
    if not os.access(resolved, os.W_OK | os.X_OK):
        raise ProtocolError(f"{label} must be writable by the current user.")
    return resolved


def _reject_secret_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _SECRET_VALUE_FIELDS:
                raise ProtocolError("Secret values are not allowed in App bridge requests.")
            _reject_secret_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_fields(item)


def _require_str(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        raise ProtocolError(f"{key} must be a non-empty string.")
    return item


def _require_int(value: dict[str, Any], key: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ProtocolError(f"{key} must be an integer.")
    return item
