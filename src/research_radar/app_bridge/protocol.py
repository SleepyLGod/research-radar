"""Strict Task 1 request protocol for the macOS application bridge."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
_PAYLOAD_FIELDS = {
    "preflight": {"live_probe"},
    "bootstrap_topic": {"description", "language"},
    "run_daily": {
        "topic_id",
        "report_date",
        "limit",
        "deep_limit",
        "language",
        "model_cache",
        "model_cache_limit_bytes",
    },
    "retry_delivery": {
        "run_dir",
        "channel",
        "allow_resend",
        "acknowledge_unknown_outcome",
    },
}
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


class EngineCommand(StrEnum):
    """Commands frozen in the App bridge schema v1."""

    PREFLIGHT = "preflight"
    BOOTSTRAP_TOPIC = "bootstrap_topic"
    RUN_DAILY = "run_daily"
    RETRY_DELIVERY = "retry_delivery"


@dataclass(frozen=True, slots=True)
class PreflightPayloadV1:
    """Local or live provider preflight payload."""

    live_probe: bool


@dataclass(frozen=True, slots=True)
class BootstrapTopicPayloadV1:
    """Natural-language topic bootstrap request."""

    description: str
    language: str


@dataclass(frozen=True, slots=True)
class RunDailyPayloadV1:
    """One evidence-gated daily report request."""

    topic_id: str
    report_date: str
    limit: int
    deep_limit: int
    language: str
    model_cache: bool
    model_cache_limit_bytes: int | None


@dataclass(frozen=True, slots=True)
class RetryDeliveryPayloadV1:
    """One channel-only delivery retry request."""

    run_dir: Path
    channel: str
    allow_resend: bool
    acknowledge_unknown_outcome: bool


EnginePayloadV1 = (
    PreflightPayloadV1
    | BootstrapTopicPayloadV1
    | RunDailyPayloadV1
    | RetryDeliveryPayloadV1
)


@dataclass(frozen=True, slots=True)
class EngineRequestV1:
    """Validated schema-v1 engine request."""

    schema_version: int
    request_id: str
    command: EngineCommand
    created_at: str
    app_support_root: Path
    config_path: Path | None
    payload: EnginePayloadV1


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
    command_value = _require_str(value, "command")
    try:
        command = EngineCommand(command_value)
    except ValueError as exc:
        raise ProtocolError(f"Unsupported command: {command_value}") from exc

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

    created_at = _require_str(value, "created_at")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("created_at must be an ISO-8601 timestamp.") from exc
    config_path = _parse_optional_contained_path(value["config_path"], app_root)
    payload = _parse_payload(command, value["payload"], app_root)
    if config_path is None and not (
        command is EngineCommand.PREFLIGHT
        and isinstance(payload, PreflightPayloadV1)
        and not payload.live_probe
    ):
        raise ProtocolError("config_path is required for production commands.")
    return EngineRequestV1(
        schema_version=schema_version,
        request_id=request_id,
        command=command,
        created_at=created_at,
        app_support_root=app_root,
        config_path=config_path,
        payload=payload,
    )


def _parse_payload(
    command: EngineCommand,
    value: Any,
    app_root: Path,
) -> EnginePayloadV1:
    if not isinstance(value, dict):
        raise ProtocolError(f"{command.value} payload must be an object.")
    expected = _PAYLOAD_FIELDS[command.value]
    if set(value) != expected:
        known_payload = any(set(value) == fields for fields in _PAYLOAD_FIELDS.values())
        if known_payload:
            raise ProtocolError("Command and payload do not match.")
        unknown = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        detail = f"unknown field {unknown[0]}" if unknown else f"missing field {missing[0]}"
        raise ProtocolError(f"Invalid {command.value} payload: {detail}.")
    if command is EngineCommand.PREFLIGHT:
        return PreflightPayloadV1(live_probe=_require_bool(value, "live_probe"))
    if command is EngineCommand.BOOTSTRAP_TOPIC:
        return BootstrapTopicPayloadV1(
            description=_require_str(value, "description"),
            language=_require_language(value, "language"),
        )
    if command is EngineCommand.RUN_DAILY:
        limit = _require_int(value, "limit")
        deep_limit = _require_int(value, "deep_limit")
        cache_limit = value["model_cache_limit_bytes"]
        if limit < 1:
            raise ProtocolError("limit must be at least 1.")
        if deep_limit < 0:
            raise ProtocolError("deep_limit cannot be negative.")
        if cache_limit is not None:
            invalid_cache_limit = (
                isinstance(cache_limit, bool)
                or not isinstance(cache_limit, int)
                or cache_limit <= 0
            )
            if invalid_cache_limit:
                raise ProtocolError("model_cache_limit_bytes must be positive or null.")
        report_date = _require_str(value, "report_date")
        try:
            datetime.strptime(report_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ProtocolError("report_date must use YYYY-MM-DD.") from exc
        return RunDailyPayloadV1(
            topic_id=_require_str(value, "topic_id"),
            report_date=report_date,
            limit=limit,
            deep_limit=deep_limit,
            language=_require_language(value, "language"),
            model_cache=_require_bool(value, "model_cache"),
            model_cache_limit_bytes=cache_limit,
        )
    return RetryDeliveryPayloadV1(
        run_dir=_parse_contained_directory(value["run_dir"], app_root, "run_dir"),
        channel=_require_choice(value, "channel", {"wechat", "email"}),
        allow_resend=_require_bool(value, "allow_resend"),
        acknowledge_unknown_outcome=_require_bool(value, "acknowledge_unknown_outcome"),
    )


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


def _parse_contained_directory(value: Any, app_root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ProtocolError(f"{label} must be an absolute path.")
    try:
        resolved = Path(value).resolve(strict=True)
        resolved.relative_to(app_root)
    except (OSError, ValueError) as exc:
        raise ProtocolError(f"{label} must stay within app_support_root.") from exc
    if not resolved.is_dir():
        raise ProtocolError(f"{label} must identify a directory.")
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


def _require_bool(value: dict[str, Any], key: str) -> bool:
    item = value[key]
    if not isinstance(item, bool):
        raise ProtocolError(f"{key} must be a boolean.")
    return item


def _require_choice(value: dict[str, Any], key: str, choices: set[str]) -> str:
    item = _require_str(value, key)
    if item not in choices:
        raise ProtocolError(f"{key} must be one of: {', '.join(sorted(choices))}.")
    return item


def _require_language(value: dict[str, Any], key: str) -> str:
    return _require_choice(value, key, {"en", "zh"})
