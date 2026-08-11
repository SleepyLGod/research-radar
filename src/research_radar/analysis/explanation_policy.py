"""Filter reader-facing prose against verified atomic claims."""

from __future__ import annotations

from typing import TypedDict

from research_radar.analysis.paper_reading import ReaderExplanation
from research_radar.models import Claim

EXPLANATION_SECTION_KEYS = (
    "opening_context",
    "core_thesis",
    "problem_walkthrough",
    "solution_walkthrough",
    "experiment_interpretation",
    "related_work_context",
    "limitations_discussion",
    "plain_language_story",
    "reader_takeaway",
)

_CLAIM_PREFIXES = {
    "problem": "Problem:",
    "solution": "Solution:",
    "experiment": "Experiment:",
    "related_work": "Related work:",
    "limitations": "Limitations:",
    "critical_assessment": "Critical assessment:",
    "essence": "Essence:",
}


class ExplanationAudit(TypedDict):
    """Counts produced while filtering public explanation paragraphs."""

    paragraph_count: int
    kept_count: int
    dropped_count: int
    fallback_section_count: int


def public_explanation(
    explanation: ReaderExplanation,
    claims: list[Claim],
    *,
    fallbacks: dict[str, str] | None = None,
) -> tuple[dict[str, str], ExplanationAudit]:
    """Keep only paragraphs fully supported by publishable claims."""

    publishable_claim_ids = {
        claim_id
        for claim in claims
        if claim.is_publishable()
        and (claim_id := _claim_id(claim))
    }
    public: dict[str, str] = {}
    paragraph_count = 0
    kept_count = 0

    for key in EXPLANATION_SECTION_KEYS:
        kept_text: list[str] = []
        for paragraph in getattr(explanation, key):
            paragraph_count += 1
            supporting_ids = set(paragraph.supporting_claim_ids)
            if supporting_ids and supporting_ids <= publishable_claim_ids:
                kept_text.append(paragraph.text)
                kept_count += 1
        public[key] = "\n\n".join(kept_text)

    fallback_section_count = 0
    for key, fallback in (fallbacks or {}).items():
        if key in public and not public[key] and fallback.strip():
            public[key] = fallback.strip()
            fallback_section_count += 1

    return public, {
        "paragraph_count": paragraph_count,
        "kept_count": kept_count,
        "dropped_count": paragraph_count - kept_count,
        "fallback_section_count": fallback_section_count,
    }


def explanation_fallbacks(claims: list[Claim]) -> dict[str, str]:
    """Build section fallbacks exclusively from publishable atomic claims."""

    return {
        "core_thesis": claim_section_text(claims, "essence"),
        "problem_walkthrough": claim_section_text(claims, "problem"),
        "solution_walkthrough": claim_section_text(claims, "solution"),
        "experiment_interpretation": claim_section_text(claims, "experiment"),
        "related_work_context": claim_section_text(claims, "related_work"),
        "limitations_discussion": claim_section_text(claims, "limitations"),
    }


def claim_section_text(claims: list[Claim], section: str) -> str:
    """Return publishable claim text for one paper-reading section."""

    prefix = _CLAIM_PREFIXES[section]
    bodies: list[str] = []
    for claim in claims:
        if not claim.is_publishable():
            continue
        paper_reading = claim.metadata.get("paper_reading", {})
        claim_section = (
            str(paper_reading.get("section") or "")
            if isinstance(paper_reading, dict)
            else ""
        )
        if claim_section != section and not claim.text.startswith(prefix):
            continue
        body = claim.text[len(prefix) :].strip() if claim.text.startswith(prefix) else claim.text
        if body:
            bodies.append(body)
    return "\n\n".join(bodies)


def _claim_id(claim: Claim) -> str:
    paper_reading = claim.metadata.get("paper_reading", {})
    if not isinstance(paper_reading, dict):
        return ""
    return str(paper_reading.get("claim_id") or "").strip()
