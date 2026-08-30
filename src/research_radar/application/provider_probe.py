"""Typed provider connectivity checks shared by CLI and App entry points."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from research_radar.analysis.providers import Message
from research_radar.analysis.routing import TaskModelRoute
from research_radar.exceptions import ResearchRadarError
from research_radar.security.redaction import redact_text

ProbeKind = Literal["small", "json", "long"]


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    """Successful, redacted provider probe result."""

    provider: str
    model: str
    probe: ProbeKind
    duration_seconds: float
    response_char_count: int
    response_excerpt: str
    json_valid: bool | None


def probe_provider(
    route: TaskModelRoute,
    *,
    probe: ProbeKind = "small",
    timer: Callable[[], float] = time.perf_counter,
) -> ProviderProbeResult:
    """Call one resolved provider without creating research artifacts."""

    if route.provider is None or route.model is None:
        raise ResearchRadarError("Provider probe requires a non-local model provider.")
    started = timer()
    response = route.provider.complete(
        [Message(role="user", content=provider_probe_prompt(probe))],
        model=route.model,
    )
    duration = timer() - started
    json_valid: bool | None = None
    if probe == "json":
        try:
            load_probe_json(response.content)
        except json.JSONDecodeError as exc:
            raise ResearchRadarError(
                "Provider probe failed: JSON response was not parseable."
            ) from exc
        json_valid = True
    return ProviderProbeResult(
        provider=route.provider_name,
        model=route.model,
        probe=probe,
        duration_seconds=round(duration, 3),
        response_char_count=len(response.content),
        response_excerpt=probe_excerpt(response.content),
        json_valid=json_valid,
    )


def provider_probe_prompt(probe: ProbeKind) -> str:
    """Return the fixed, non-sensitive prompt for one probe kind."""

    if probe == "small":
        return "Reply with exactly this text: ResearchRadar provider probe ok."
    if probe == "json":
        return (
            "Return only valid JSON, with no Markdown fences and no extra text. "
            'Use exactly this shape: {"status":"ok","provider_test":true,'
            '"items":["alpha","beta"],"count":2}.'
        )
    if probe == "long":
        return (
            "Write a structured LLM API transport stress-test response of about 1800 "
            "English words. Use short paragraphs, include numbered sections, and do not "
            "use Markdown tables."
        )
    raise ResearchRadarError(f"Unsupported provider probe: {probe}")


def probe_excerpt(value: str, *, limit: int = 500) -> str:
    """Return a bounded, redacted single-line response excerpt."""

    text = redact_text(value).replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def load_probe_json(value: str) -> dict[str, object]:
    """Extract and parse one JSON object from a provider response."""

    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()
    payload = json.loads(_extract_json_object_text(text))
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("JSON payload must be an object", text, 0)
    return payload


def _extract_json_object_text(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]
