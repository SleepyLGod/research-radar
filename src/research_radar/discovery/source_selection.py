"""Source selection policies for deep reading."""

from __future__ import annotations

from research_radar.discovery.source_role import IMPLEMENTATION_REPO_PRIORITY
from research_radar.models import SourceCandidate

RESEARCH_BRIEF = "research_brief"
IMPLEMENTATION_SCAN = "implementation_scan"
PAPER_ROLES = {"primary_paper", "benchmark_paper"}
RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR = 0.6

ROLE_RANKS = {
    "primary_paper": 50,
    "benchmark_paper": 40,
    "implementation_repo": 30,
    "blog_or_web": 20,
    "survey_or_list": 10,
    "noise": 0,
}


def select_deep_candidates(
    candidates: list[SourceCandidate],
    limit: int,
    *,
    source_intent: str = RESEARCH_BRIEF,
) -> list[SourceCandidate]:
    """Select sources for deep reading according to topic intent."""

    candidate_pool = _candidate_pool(candidates, source_intent)
    return sorted(
        candidate_pool,
        key=lambda candidate: _selection_key(candidate, source_intent),
        reverse=True,
    )[:limit]


def source_selection_score(candidate: SourceCandidate, *, source_intent: str) -> float:
    """Return a numeric score used for audit display."""

    role_rank = _role_rank(candidate)
    relevance_score = _relevance_score(candidate)
    source_score = float(candidate.score)
    if source_intent == RESEARCH_BRIEF:
        return role_rank + relevance_score + (source_score / 1000)
    return relevance_score + (_deep_read_priority(candidate) / 1000) + (source_score / 10000)


def _candidate_pool(
    candidates: list[SourceCandidate],
    source_intent: str,
) -> list[SourceCandidate]:
    non_list_candidates = [
        candidate for candidate in candidates if _role(candidate) != "survey_or_list"
    ]
    if source_intent == RESEARCH_BRIEF:
        papers = [
            candidate
            for candidate in candidates
            if _role(candidate) in PAPER_ROLES
            and _relevance_score(candidate) >= RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR
        ]
        if papers:
            return papers
        serious_repositories = [
            candidate
            for candidate in candidates
            if _role(candidate) == "implementation_repo"
            and _deep_read_priority(candidate) >= IMPLEMENTATION_REPO_PRIORITY
        ]
        if serious_repositories:
            return serious_repositories
        blogs = [candidate for candidate in candidates if _role(candidate) == "blog_or_web"]
        if blogs:
            return blogs
        return non_list_candidates or candidates
    if source_intent == IMPLEMENTATION_SCAN:
        return non_list_candidates or candidates
    return non_list_candidates or candidates


def _selection_key(
    candidate: SourceCandidate,
    source_intent: str,
) -> tuple[float, float, float]:
    if source_intent == RESEARCH_BRIEF:
        return (
            float(_role_rank(candidate)),
            _relevance_score(candidate),
            float(candidate.score),
        )
    return (
        _relevance_score(candidate),
        float(_deep_read_priority(candidate)),
        float(candidate.score),
    )


def _role(candidate: SourceCandidate) -> str | None:
    role = candidate.metadata.get("source_role", {}).get("role")
    return str(role) if role is not None else None


def _role_rank(candidate: SourceCandidate) -> int:
    return ROLE_RANKS.get(_role(candidate) or "noise", 0)


def _relevance_score(candidate: SourceCandidate) -> float:
    return float(candidate.metadata.get("relevance", {}).get("score", 0.0))


def _deep_read_priority(candidate: SourceCandidate) -> int:
    return int(candidate.metadata.get("source_role", {}).get("deep_read_priority", 0))
