"""Deterministic source relevance gate."""

from __future__ import annotations

import re
from dataclasses import replace

from research_radar.config import TopicConfig
from research_radar.discovery.dedupe import priority_score
from research_radar.models import ReviewFinding, SourceCandidate

RELEVANT_THRESHOLD = 0.45
NEEDS_REVIEW_THRESHOLD = 0.20

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

GENERIC_TERMS = {
    "benchmark",
    "benchmarks",
    "system",
    "systems",
}

PHRASE_BOOSTS = {
    "agent memory": 0.45,
    "memory system for agents": 0.45,
    "memory systems for ai agents": 0.45,
    "memory systems for agents": 0.45,
    "llm memory": 0.40,
    "memory benchmark": 0.35,
    "persistent recall": 0.35,
    "context management": 0.25,
}


def gate_relevant_sources(
    candidates: list[SourceCandidate],
    topic: TopicConfig,
) -> tuple[list[SourceCandidate], list[SourceCandidate], list[ReviewFinding]]:
    """Score sources for topic relevance and return all scored plus publishable candidates."""

    scored_candidates = [score_source(candidate, topic) for candidate in candidates]
    selected = [
        candidate
        for candidate in scored_candidates
        if candidate.metadata.get("relevance", {}).get("status") == "relevant"
    ]
    findings = [
        _finding(candidate)
        for candidate in scored_candidates
        if candidate.metadata.get("relevance", {}).get("status") != "relevant"
    ]
    return scored_candidates, selected, findings


def score_source(candidate: SourceCandidate, topic: TopicConfig) -> SourceCandidate:
    """Attach deterministic relevance metadata to a source candidate."""

    text = _normalize(
        " ".join(
            [
                candidate.title,
                candidate.summary or "",
                candidate.source_name,
                candidate.source_type.value,
            ]
        )
    )
    text_terms = set(_tokens(text))
    topic_terms = _topic_terms(topic)
    primary_terms = topic_terms - GENERIC_TERMS
    generic_terms = topic_terms & GENERIC_TERMS

    matched_primary = sorted(primary_terms & text_terms)
    matched_generic = sorted(generic_terms & text_terms)
    matched_phrases = sorted(phrase for phrase in PHRASE_BOOSTS if phrase in text)

    score = 0.0
    score += min(0.54, len(matched_primary) * 0.18)
    score += min(0.16, len(matched_generic) * 0.08)
    score += sum(PHRASE_BOOSTS[phrase] for phrase in matched_phrases)
    score += min(0.08, priority_score(candidate.url, topic.priority_sources) * 0.08)
    score += 0.03
    score = min(score, 1.0)

    if score >= RELEVANT_THRESHOLD:
        status = "relevant"
    elif score >= NEEDS_REVIEW_THRESHOLD:
        status = "needs_review"
    else:
        status = "irrelevant"

    reason = _reason(matched_primary, matched_generic, matched_phrases)
    metadata = {
        **candidate.metadata,
        "relevance": {
            "score": round(score, 3),
            "status": status,
            "reason": reason,
            "matched_terms": [*matched_primary, *matched_generic],
            "matched_phrases": matched_phrases,
        },
    }
    return replace(candidate, metadata=metadata)


def _topic_terms(topic: TopicConfig) -> set[str]:
    text = _normalize(" ".join([topic.id, *topic.queries]))
    return {token for token in _tokens(text) if token not in STOPWORDS}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _reason(
    matched_primary: list[str],
    matched_generic: list[str],
    matched_phrases: list[str],
) -> str:
    if matched_phrases:
        return "matched topic phrase(s): " + ", ".join(matched_phrases)
    if matched_primary or matched_generic:
        return "matched topic term(s): " + ", ".join([*matched_primary, *matched_generic])
    return "no strong topic match"


def _finding(candidate: SourceCandidate) -> ReviewFinding:
    relevance = candidate.metadata.get("relevance", {})
    status = str(relevance.get("status", "needs_review"))
    severity = "warning" if status == "needs_review" else "info"
    return ReviewFinding(
        severity=severity,
        message=f"Source relevance gate marked candidate as {status}: {relevance.get('reason')}",
        claim_text=candidate.title,
        metadata={
            "kind": "source_relevance",
            "source_url": candidate.url,
            "source_status": status,
            "score": relevance.get("score"),
        },
    )
