"""Local scheduler helpers."""

from __future__ import annotations


def cron_line(command: str, *, minute: int, hour: int) -> str:
    """Return a cron line for a daily command."""

    return f"{minute} {hour} * * * {command}"


def launchd_label(topic_id: str, mode: str) -> str:
    """Return a stable launchd label."""

    safe_topic = topic_id.replace("_", "-").replace(" ", "-")
    return f"ai.researchpress.{mode}.{safe_topic}"
