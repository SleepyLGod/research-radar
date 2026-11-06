"""Build public reading sections from approved claims, not unverified reader prose."""

from __future__ import annotations

from collections import Counter
from typing import TypedDict

from research_radar.analysis.paper_reading import ReaderExplanation
from research_radar.analysis.reading_review import paragraph_is_public
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

_SECTION_CLAIMS = {
    "core_thesis": "essence", "problem_walkthrough": "problem",
    "solution_walkthrough": "solution", "experiment_interpretation": "experiment",
    "related_work_context": "related_work", "limitations_discussion": "limitations",
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
    source_url: str = "",
) -> tuple[dict[str, str], ExplanationAudit]:
    """Publish explicitly reviewed prose, otherwise retain verified-claim fallbacks."""

    if source_url:
        claims = [c for c in claims if {a.source_url for a in c.evidence} == {source_url}]
    counts = Counter(c.metadata.get("paper_reading", {}).get("claim_id") for c in claims)
    # Approved IDs establish reference eligibility, not that the paragraph follows from them.
    fallbacks = explanation_fallbacks(claims)
    public = {}
    kept_count = 0
    fallback_count = 0
    covered = {claim_id for key in EXPLANATION_SECTION_KEYS
               for p in getattr(explanation, key)
               if paragraph_is_public(p, claims, source_url=source_url)
               for claim_id in p.supporting_claim_ids}
    for key in EXPLANATION_SECTION_KEYS:
        kept = [p.text for p in getattr(explanation, key)
                if paragraph_is_public(p, claims, source_url=source_url)]
        public[key] = "\n\n".join(kept) or fallbacks.get(key, "")
        # Preserve independently reviewed facts lost with rejected prose, once only.
        # Never salvage a sentence from that prose or inherit its approval.
        if kept:
            lost_ids = {claim_id for p in getattr(explanation, key)
                        if not paragraph_is_public(p, claims, source_url=source_url)
                        for claim_id in p.supporting_claim_ids} - covered
            retained = [c for c in claims
                        if c.metadata.get("paper_reading", {}).get("claim_id") in lost_ids
                        and counts[c.metadata["paper_reading"]["claim_id"]] == 1
                        and {a.source_url for a in c.evidence} == {source_url}
                        and c.is_publishable()
                        and c.metadata.get("model_review", {}).get("status") == "supported"
                        and c.metadata.get("model_review", {}).get("requested_status")
                        == "supported"
                        and c.metadata.get("model_review", {}).get("reviewed_text") == c.text]
            if retained:
                section = _SECTION_CLAIMS.get(key)
                if section and (supplement := claim_section_text(retained, section)):
                    public[key] += "\n\n" + supplement
                    covered.update(c.metadata["paper_reading"]["claim_id"] for c in retained)
        kept_count += len(kept)
        fallback_count += bool(not kept and public[key])
    paragraph_count = sum(len(getattr(explanation, key)) for key in EXPLANATION_SECTION_KEYS)

    return public, {
        "paragraph_count": paragraph_count,
        "kept_count": kept_count,
        "dropped_count": paragraph_count - kept_count,
        "fallback_section_count": fallback_count,
    }


def explanation_fallbacks(claims: list[Claim]) -> dict[str, str]:
    """Build section fallbacks exclusively from publishable atomic claims."""

    return {key: claim_section_text(claims, section) for key, section in _SECTION_CLAIMS.items()}


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
