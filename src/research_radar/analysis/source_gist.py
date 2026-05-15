"""Source-level gist generation for daily reports."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from research_radar.analysis.providers import LLMProvider, Message
from research_radar.models import SourceCandidate

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def attach_source_gists(
    sources: list[SourceCandidate],
    *,
    provider: LLMProvider | None = None,
    model: str | None = None,
    language: str = "en",
) -> list[SourceCandidate]:
    """Attach conservative source-level gists using only title and summary input."""

    if not sources:
        return []
    model_gists = _model_gists(sources, provider, model, language) if provider and model else {}
    return [
        _with_gist(
            source,
            model_gists.get(index) or deterministic_source_gist(source, language=language),
            method="model" if index in model_gists else "deterministic",
        )
        for index, source in enumerate(sources, start=1)
    ]


def deterministic_source_gist(source: SourceCandidate, *, language: str = "en") -> str:
    """Return a safe fallback gist that does not restate a raw abstract slice."""

    role = str(source.metadata.get("source_role", {}).get("role", source.source_type.value))
    title = _compact(source.title)
    summary = _first_sentence(source.summary or "")
    if language == "zh":
        if summary:
            return _sanitize_gist(
                f"基于标题和摘要，这个 {role} 主要围绕《{title}》；"
                "摘要中的具体主张仍需要在正文中核验。"
            )
        return _sanitize_gist(
            f"基于标题，这个 {role} 似乎围绕《{title}》；目前没有可核验的摘要细节。"
        )
    if summary:
        return _sanitize_gist(
            f"Based on the title and abstract, this {role} is mainly about {title}; "
            "treat the abstract's claims as leads to verify in the paper."
        )
    return _sanitize_gist(
        f"Based on the title, this {role} appears to be about {title}; "
        "no abstract-backed detail is available yet."
    )


def sanitize_source_gist(value: str) -> str:
    """Remove URL-like text and keep the gist compact."""

    return _sanitize_gist(value)


def _model_gists(
    sources: list[SourceCandidate],
    provider: LLMProvider,
    model: str | None,
    language: str,
) -> dict[int, str]:
    response = provider.complete(
        [
            Message(
                role="system",
                content=(
                    "You write conservative one-sentence source digests. "
                    "Use only the supplied title, source type, and abstract. "
                    f"Write the gist in {_language_name(language)}. "
                    "Do not include URLs. Return strict JSON only."
                ),
            ),
            Message(role="user", content=_gist_prompt(sources, language)),
        ],
        model=model or "source-gist",
    )
    try:
        payload = json.loads(response.content)
    except json.JSONDecodeError:
        return {}
    rows = payload.get("gists")
    if not isinstance(rows, list):
        return {}
    gists: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        index = row.get("index")
        gist = row.get("gist")
        if not isinstance(index, int) or not isinstance(gist, str):
            continue
        cleaned = _sanitize_gist(gist)
        if cleaned:
            gists[index] = cleaned
    return gists


def _gist_prompt(sources: list[SourceCandidate], language: str) -> str:
    lines = [
        "For each source, write one plain-language high-level gist.",
        "Rules:",
        "- Use only the provided title, type, and abstract.",
        "- Do not invent results, benchmarks, links, authors, or code availability.",
        f"- Write each gist in {_language_name(language)}.",
        "- Do not include any URL.",
        "- Keep each gist under 35 words.",
        'Return JSON: {"gists":[{"index":1,"gist":"..."}]}',
        "",
        "Sources:",
    ]
    for index, source in enumerate(sources, start=1):
        lines.extend(
            [
                f"INDEX: {index}",
                f"TITLE: {source.title}",
                f"TYPE: {source.source_type.value}",
                f"ABSTRACT: {_compact(source.summary or '')[:900]}",
                "",
            ]
        )
    return "\n".join(lines)


def _with_gist(source: SourceCandidate, gist: str, *, method: str) -> SourceCandidate:
    return replace(
        source,
        metadata={
            **source.metadata,
            "source_gist": {
                "text": _sanitize_gist(gist),
                "method": method,
                "input": "title_summary_only",
            },
        },
    )


def _sanitize_gist(value: str) -> str:
    text = URL_PATTERN.sub("", _compact(value)).strip(" -")
    words = text.split()
    if len(words) > 45:
        text = " ".join(words[:45]).rstrip(".,;:") + "."
    return text


def _first_sentence(value: str) -> str:
    text = _compact(value)
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s+", text)
    return text[: match.start()].strip() if match else text


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _language_name(language: str) -> str:
    return "Simplified Chinese" if language == "zh" else "English"
