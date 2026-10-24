"""Deterministic research results, separate from process completion."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypedDict, cast

ResearchStatus = Literal["ready", "no_new_content", "incomplete"]
RESEARCH_REASONS = frozenset(
    {
        "no_eligible_papers",
        "discovery_failed",
        "full_text_unavailable",
        "reading_failed",
        "evidence_insufficient",
        "verification_no_public_claims",
    }
)


class ResearchOutcome(TypedDict):
    """Public, non-sensitive explanation of a completed research attempt."""

    status: ResearchStatus
    reasons: list[str]


def parse_research_outcome(value: object) -> ResearchOutcome:
    """Validate an artifact outcome without guessing legacy state."""
    if not isinstance(value, dict) or set(value) != {"status", "reasons"}:
        raise ValueError("Invalid research outcome fields.")
    status, reasons = value["status"], value["reasons"]
    if not isinstance(status, str) or status not in {"ready", "no_new_content", "incomplete"}:
        raise ValueError("Invalid research outcome status.")
    if (
        not isinstance(reasons, list)
        or any(not isinstance(reason, str) or reason not in RESEARCH_REASONS for reason in reasons)
        or len(set(reasons)) != len(reasons)
    ):
        raise ValueError("Invalid research outcome reasons.")
    return {"status": cast(ResearchStatus, status), "reasons": list(reasons)}


def assess_research_outcome(
    *,
    eligible_count: int,
    deep_read_count: int,
    publishable_claim_count: int,
    discovery_failed: bool,
    reading_statuses: Iterable[str],
    verifier_reviewed_count: int,
) -> ResearchOutcome:
    """Classify actual attempts; zero claims alone never implies verifier rejection."""
    statuses = set(reading_statuses)
    reasons: list[str] = []
    if discovery_failed:
        reasons.append("discovery_failed")
    if eligible_count == 0:
        reasons.append("no_eligible_papers")
    if statuses.intersection({"ingestion_failed", "insufficient_full_text"}):
        reasons.append("full_text_unavailable")
    if "reading_failed" in statuses:
        reasons.append("reading_failed")
    if deep_read_count > 0 and publishable_claim_count > 0:
        return {"status": "ready", "reasons": reasons}
    if "succeeded" in statuses:
        reasons.append(
            "verification_no_public_claims"
            if verifier_reviewed_count > 0
            else "evidence_insufficient"
        )
    if eligible_count == 0 and not discovery_failed:
        return {"status": "no_new_content", "reasons": reasons}
    return {"status": "incomplete", "reasons": reasons or ["evidence_insufficient"]}
