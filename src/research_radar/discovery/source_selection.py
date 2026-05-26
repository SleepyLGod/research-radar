"""Source selection policies for deep reading."""

from __future__ import annotations

from research_radar.models import SourceCandidate

RESEARCH_BRIEF = "research_brief"
IMPLEMENTATION_SCAN = "implementation_scan"
PAPER_ROLES = {"primary_paper", "benchmark_paper"}
RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR = 0.6
RESEARCH_BRIEF_CENTRALITY_BONUS_MAX = 0.22
RESEARCH_BRIEF_LOW_CENTRALITY_PENALTY = 0.12
RESEARCH_BRIEF_LOW_CENTRALITY_FLOOR = 0.55

ROLE_RANKS = {
    "primary_paper": 50,
    "benchmark_paper": 40,
    "implementation_repo": 30,
    "blog_or_web": 20,
    "survey_or_list": 10,
    "noise": 0,
}


def source_centrality_score(candidate: SourceCandidate) -> float:
    """Return the deterministic centrality score attached to a source."""

    return float(candidate.metadata.get("source_centrality", {}).get("score", 0.0))


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
        key=lambda candidate: source_selection_key(candidate, source_intent=source_intent),
        reverse=True,
    )[:limit]


def source_selection_score(candidate: SourceCandidate, *, source_intent: str) -> float:
    """Return a numeric score used for audit display."""

    role_rank = _role_rank(candidate)
    relevance_score = _relevance_score(candidate)
    centrality_score = source_centrality_score(candidate)
    source_score = float(candidate.score)
    if source_intent == RESEARCH_BRIEF:
        centrality_bonus = min(
            RESEARCH_BRIEF_CENTRALITY_BONUS_MAX,
            centrality_score * 0.30,
        )
        has_centrality_penalty_signal = bool(
            candidate.metadata.get("source_centrality", {}).get("negative_signals", [])
        )
        centrality_penalty = (
            RESEARCH_BRIEF_LOW_CENTRALITY_PENALTY
            if (
                has_centrality_penalty_signal
                and centrality_score < RESEARCH_BRIEF_LOW_CENTRALITY_FLOOR
            )
            else 0.0
        )
        return (
            relevance_score
            + centrality_bonus
            - centrality_penalty
            + (role_rank / 1000)
            + (source_score / 10000)
        )
    return relevance_score + (_deep_read_priority(candidate) / 1000) + (source_score / 10000)


def source_selection_key(
    candidate: SourceCandidate,
    *,
    source_intent: str,
) -> tuple[float, ...]:
    """Return the canonical sort key for source selection and audit reports."""

    if source_intent == RESEARCH_BRIEF:
        return (
            source_selection_score(candidate, source_intent=source_intent),
            float(_role_rank(candidate)),
            source_centrality_score(candidate),
            _relevance_score(candidate),
            float(candidate.score),
        )
    return (
        _relevance_score(candidate),
        float(_deep_read_priority(candidate)),
        float(candidate.score),
        0.0,
    )


def _candidate_pool(
    candidates: list[SourceCandidate],
    source_intent: str,
) -> list[SourceCandidate]:
    non_list_candidates = [
        candidate for candidate in candidates if _role(candidate) != "survey_or_list"
    ]
    if source_intent == RESEARCH_BRIEF:
        return [
            candidate
            for candidate in candidates
            if _role(candidate) in PAPER_ROLES
            and _relevance_score(candidate) >= RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR
        ]
    if source_intent == IMPLEMENTATION_SCAN:
        return non_list_candidates or candidates
    return non_list_candidates or candidates


def _role(candidate: SourceCandidate) -> str | None:
    role = candidate.metadata.get("source_role", {}).get("role")
    return str(role) if role is not None else None


def _role_rank(candidate: SourceCandidate) -> int:
    return ROLE_RANKS.get(_role(candidate) or "noise", 0)


def _relevance_score(candidate: SourceCandidate) -> float:
    return float(candidate.metadata.get("relevance", {}).get("score", 0.0))


def _deep_read_priority(candidate: SourceCandidate) -> int:
    return int(candidate.metadata.get("source_role", {}).get("deep_read_priority", 0))
