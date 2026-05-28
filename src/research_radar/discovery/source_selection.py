"""Source selection policies for deep reading."""

from __future__ import annotations

import re
from dataclasses import replace

from research_radar.models import SourceCandidate, SourceType
from research_radar.storage.source_history import source_family_key

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

    return _dedupe_ranked_candidates(
        ranked_deep_candidates(candidates, source_intent=source_intent)
    )[:limit]


def ranked_deep_candidates(
    candidates: list[SourceCandidate],
    *,
    source_intent: str = RESEARCH_BRIEF,
) -> list[SourceCandidate]:
    """Return eligible deep-read candidates in canonical ranking order."""

    return sorted(
        _candidate_pool(candidates, source_intent),
        key=lambda candidate: source_selection_key(candidate, source_intent=source_intent),
        reverse=True,
    )


def annotate_deep_selection_dedupe(
    candidates: list[SourceCandidate],
    *,
    source_intent: str = RESEARCH_BRIEF,
) -> list[SourceCandidate]:
    """Annotate eligible candidates with deep-selection paper-family dedupe metadata."""

    dedupe_by_url = _dedupe_metadata_by_url(
        ranked_deep_candidates(candidates, source_intent=source_intent)
    )
    return [
        replace(
            candidate,
            metadata={
                **candidate.metadata,
                "deep_selection_dedupe": dedupe_by_url[candidate.url],
            },
        )
        if candidate.url in dedupe_by_url
        else candidate
        for candidate in candidates
    ]


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


def deep_selection_family_key(candidate: SourceCandidate) -> str | None:
    """Return the paper-family key used to avoid duplicate deep reads."""

    keys = _deep_selection_family_keys(candidate)
    return keys[0] if keys else None


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


def _dedupe_ranked_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    selected: list[SourceCandidate] = []
    seen_families: set[str] = set()
    for candidate in candidates:
        family_keys = _deep_selection_family_keys(candidate)
        if family_keys and any(key in seen_families for key in family_keys):
            continue
        selected.append(candidate)
        seen_families.update(family_keys)
    return selected


def _dedupe_metadata_by_url(
    ranked_candidates: list[SourceCandidate],
) -> dict[str, dict[str, object]]:
    primary_by_family: dict[str, SourceCandidate] = {}
    metadata_by_url: dict[str, dict[str, object]] = {}
    for candidate in ranked_candidates:
        family_keys = _deep_selection_family_keys(candidate)
        family_key = family_keys[0] if family_keys else None
        if not family_keys:
            metadata_by_url[candidate.url] = {
                "status": "unique",
                "family_key": None,
            }
            continue
        primary = next(
            (
                primary_by_family[key]
                for key in family_keys
                if key in primary_by_family
            ),
            None,
        )
        if primary is None:
            for key in family_keys:
                primary_by_family[key] = candidate
            metadata_by_url[candidate.url] = {
                "status": "primary",
                "family_key": family_key,
                "family_keys": family_keys,
            }
            continue
        metadata_by_url[candidate.url] = {
            "status": "duplicate",
            "family_key": family_key,
            "family_keys": family_keys,
            "deduped_as_url": primary.url,
            "deduped_as_title": primary.title,
            "skip_reason": "duplicate paper family already ranked higher for deep reading",
        }
    return metadata_by_url


def _weak_paper_family_key(key: str) -> bool:
    return key.startswith(("url:", "corpusid:", "openalex:"))


def _deep_selection_family_keys(candidate: SourceCandidate) -> list[str]:
    key = source_family_key(candidate)
    if candidate.source_type != SourceType.PAPER:
        return [key] if key else []
    title_key = _title_family_key(candidate.title)
    title_family = f"title:{title_key}" if title_key else None
    keys: list[str] = []
    if key and not _weak_paper_family_key(key):
        keys.append(key)
    if title_family:
        keys.append(title_family)
    if key and _weak_paper_family_key(key):
        keys.append(key)
    return keys


def _title_family_key(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return normalized


def _role(candidate: SourceCandidate) -> str | None:
    role = candidate.metadata.get("source_role", {}).get("role")
    return str(role) if role is not None else None


def _role_rank(candidate: SourceCandidate) -> int:
    return ROLE_RANKS.get(_role(candidate) or "noise", 0)


def _relevance_score(candidate: SourceCandidate) -> float:
    return float(candidate.metadata.get("relevance", {}).get("score", 0.0))


def _deep_read_priority(candidate: SourceCandidate) -> int:
    return int(candidate.metadata.get("source_role", {}).get("deep_read_priority", 0))
