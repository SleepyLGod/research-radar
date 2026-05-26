"""Runtime summary helpers for long-running pipeline stages."""

from __future__ import annotations

from typing import Any

SLOW_STAGE_THRESHOLDS = {
    "source_gist": 60.0,
    "reader": 300.0,
    "verifier": 300.0,
    "artifacts": 30.0,
}
TERMINAL_STATUSES = {"completed", "succeeded", "failed"}


def build_runtime_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a compact runtime summary from progress events."""

    stage_events = []
    cache_hit_count = 0
    cache_miss_count = 0
    for event in events:
        cache_hit_count += int(event.get("cache_hit_count", 0) or 0)
        cache_miss_count += int(event.get("cache_miss_count", 0) or 0)
        if event.get("status") not in TERMINAL_STATUSES:
            continue
        stage = str(event.get("stage", ""))
        if stage not in SLOW_STAGE_THRESHOLDS:
            continue
        stage_events.append(_stage_runtime_row(event))
    return {
        "total_elapsed_seconds": _total_elapsed_seconds(events),
        "slow_stage_count": sum(1 for event in stage_events if event.get("slow") is True),
        "cache": {
            "hit_count": cache_hit_count,
            "miss_count": cache_miss_count,
        },
        "stages": stage_events,
    }


def _stage_runtime_row(event: dict[str, Any]) -> dict[str, Any]:
    stage = str(event.get("stage", ""))
    duration = _optional_float(event.get("duration_seconds"))
    row: dict[str, Any] = {
        "stage": stage,
        "status": event.get("status"),
        "duration_seconds": duration,
        "slow": bool(duration is not None and duration >= SLOW_STAGE_THRESHOLDS[stage]),
    }
    for key in (
        "provider",
        "model",
        "source_title",
        "source_url",
        "source_count",
        "claim_count",
        "publishable_claim_count",
        "action_count",
        "cache_hit_count",
        "cache_miss_count",
        "error_type",
    ):
        if key in event:
            row[key] = event[key]
    return row


def _total_elapsed_seconds(events: list[dict[str, Any]]) -> float:
    if not events:
        return 0.0
    return float(events[-1].get("elapsed_seconds", 0.0) or 0.0)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
