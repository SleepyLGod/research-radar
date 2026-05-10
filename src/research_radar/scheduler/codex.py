"""Codex automation prompt generation."""

from __future__ import annotations


def automation_prompt(topic_id: str, mode: str) -> str:
    """Return a self-contained Codex automation prompt."""

    return (
        f"Run ResearchRadar {mode} for topic `{topic_id}`. "
        "Use local config, do not print secrets, write run artifacts, "
        "and stop before publishing unless the task explicitly requests draft creation."
    )
