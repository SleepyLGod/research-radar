"""Deterministic checks for whether an artifact is full-paper enough to read."""

from __future__ import annotations

import re

from research_radar.models import Artifact

RESEARCH_BRIEF_TEXT_CHAR_FLOOR = 8_000
_FIGURE_CAPTION = re.compile(r"(?im)\bfigure\s+\d+\s*[:.]")
_TABLE_CAPTION = re.compile(r"(?im)\btable\s+\d+\s*[:.]")


def paper_text_quality(artifact: Artifact) -> dict[str, object]:
    """Return deterministic full-paper completeness diagnostics for an artifact."""

    text = artifact.text or ""
    lower = text.casefold()
    section_hits = {
        "abstract": _has_heading(lower, "abstract"),
        "introduction": _has_heading(lower, "introduction"),
        "method": _has_any_heading_or_keyword(
            lower,
            headings=(
                "method",
                "methods",
                "approach",
                "architecture",
                "design",
                "system design",
                "framework",
            ),
            keywords=("algorithm", "scheduler", "pipeline", "implementation"),
        ),
        "experiments_results": _has_any_heading_or_keyword(
            lower,
            headings=(
                "experiment",
                "experiments",
                "evaluation",
                "results",
                "analysis",
            ),
            keywords=("benchmark", "baseline", "ablation", "throughput", "latency"),
        ),
        "limitations_conclusion": _has_any_heading_or_keyword(
            lower,
            headings=("limitation", "limitations", "discussion", "conclusion"),
            keywords=("future work",),
        ),
        "references": bool(re.search(r"(?im)^\s*(references|bibliography)\s*$", text)),
    }
    figure_caption_count = len(_FIGURE_CAPTION.findall(text))
    table_caption_count = len(_TABLE_CAPTION.findall(text))
    text_chars = len(text)
    page_count = _page_count(artifact)
    content_type = artifact.content_type or "unknown"
    acquisition_kind = _acquisition_kind(artifact)
    passed, reason = _quality_decision(
        content_type=content_type,
        text_chars=text_chars,
        page_count=page_count,
        section_hits=section_hits,
    )
    return {
        "status": "pass" if passed else "fail",
        "reason": reason,
        "acquisition_kind": acquisition_kind,
        "content_type": content_type,
        "text_chars": text_chars,
        "page_count": page_count,
        "section_hits": section_hits,
        "figure_caption_count": figure_caption_count,
        "table_caption_count": table_caption_count,
    }


def passes_research_brief_text_quality(artifact: Artifact) -> bool:
    """Return whether an artifact is complete enough for research-brief deep reading."""

    return paper_text_quality(artifact)["status"] == "pass"


def _quality_decision(
    *,
    content_type: str,
    text_chars: int,
    page_count: int | None,
    section_hits: dict[str, bool],
) -> tuple[bool, str]:
    if content_type not in {"application/pdf", "text/html", "text/x-tex"}:
        return True, "artifact type is not subject to full-paper completeness gating"
    if text_chars < RESEARCH_BRIEF_TEXT_CHAR_FLOOR:
        return False, "artifact text is too short for full-paper deep reading"
    has_front = section_hits["abstract"] or section_hits["introduction"]
    if not has_front:
        return False, "missing abstract or introduction signal"
    if not section_hits["method"]:
        return False, "missing method/design signal"
    if not section_hits["experiments_results"]:
        return False, "missing experiments/results signal"
    if content_type == "text/html" and page_count is None and text_chars < 12_000:
        return False, "html artifact looks like a landing page or abstract page"
    return True, "artifact has full-paper text signals"


def _has_heading(text: str, heading: str) -> bool:
    escaped = re.escape(heading)
    return bool(re.search(rf"(?m)^\s*(?:\d+(?:\.\d+)*\s+)?{escaped}\b", text))


def _has_any_heading_or_keyword(
    text: str,
    *,
    headings: tuple[str, ...],
    keywords: tuple[str, ...],
) -> bool:
    return any(_has_heading(text, heading) for heading in headings) or any(
        keyword in text for keyword in keywords
    )


def _page_count(artifact: Artifact) -> int | None:
    value = artifact.metadata.get("page_count")
    return value if isinstance(value, int) else None


def _acquisition_kind(artifact: Artifact) -> str:
    value = artifact.metadata.get("acquisition_kind")
    if isinstance(value, str) and value:
        return value
    if artifact.content_type == "application/pdf":
        return "pdf"
    if artifact.content_type == "text/html":
        return "html"
    return "unknown"
