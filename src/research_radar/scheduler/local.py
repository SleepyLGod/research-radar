"""Local scheduler helpers."""

from __future__ import annotations

import re


def cron_line(command: str, *, minute: int, hour: int) -> str:
    """Return a cron line for a daily command."""

    return f"{minute} {hour} * * * {command}"


def launchd_label(topic_id: str, mode: str) -> str:
    """Return a stable launchd label."""

    return f"ai.research-radar.{_slug(mode)}.{_slug(topic_id)}"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", value.strip()).strip("-").lower()
