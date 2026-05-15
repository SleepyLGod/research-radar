"""Deterministic source relevance gate."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime

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
    "arxiv",
    "benchmark",
    "benchmarks",
    "eval",
    "evaluation",
    "generation",
    "paper",
    "papers",
    "survey",
    "surveys",
    "system",
    "systems",
}

BENCHMARK_ANCHOR_ALIASES = {"locomo", "longmemeval"}

PHRASE_BOOSTS = {
    "agent memory": 0.45,
    "memory system for agents": 0.45,
    "memory systems for ai agents": 0.45,
    "memory systems for agents": 0.45,
    "llm memory": 0.40,
    "memory benchmark": 0.35,
    "persistent recall": 0.35,
    "context management": 0.25,
    "llm reasoning": 0.35,
    "reasoning benchmark": 0.40,
    "reasoning evaluation": 0.40,
    "test time scaling": 0.40,
    "rag benchmark": 0.40,
    "rag evaluation": 0.40,
    "retrieval augmented generation": 0.45,
    "retrieval augmented generation evaluation": 0.50,
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
    configured_phrases = _topic_phrases(topic)
    topic_primary_terms = {_singular(token) for token in (_topic_terms(topic) - GENERIC_TERMS)}
    matched_phrases = sorted(
        {
            phrase
            for phrase in [*PHRASE_BOOSTS, *configured_phrases]
            if phrase in text and _phrase_matches_topic(phrase, topic_primary_terms)
        }
    )
    required_phrase_matches = _configured_phrase_matches(topic.required_phrases, text)
    negative_phrase_matches = _configured_phrase_matches(
        [*topic.exclusion_terms, *topic.negative_phrases],
        text,
    )
    concept_gate = _concept_gate(topic, text)
    strict_topic_policy = _strict_topic_policy_applies(candidate, topic)
    concept_policy = bool(topic.concept_groups and strict_topic_policy)
    required_phrase_policy = bool(
        not concept_policy
        and topic.required_phrases
        and strict_topic_policy
    )

    score = 0.0
    score += min(0.54, len(matched_primary) * 0.18)
    score += min(0.16, len(matched_generic) * 0.08)
    score += sum(PHRASE_BOOSTS.get(phrase, 0.30) for phrase in matched_phrases)
    if concept_gate["passed"]:
        score += 0.35
    score += min(0.08, priority_score(candidate.url, topic.priority_sources) * 0.08)
    score += 0.03
    if (
        candidate.source_type.value == "paper"
        and not matched_phrases
        and len(matched_primary) < 2
        and not concept_gate["passed"]
    ):
        score = min(score, NEEDS_REVIEW_THRESHOLD)
    if required_phrase_policy and not required_phrase_matches:
        score = min(score, NEEDS_REVIEW_THRESHOLD)
    if concept_policy and not concept_gate["passed"]:
        score = min(score, NEEDS_REVIEW_THRESHOLD)
    if negative_phrase_matches:
        score = min(score, NEEDS_REVIEW_THRESHOLD)
    if concept_gate["matched_negative_aliases"]:
        score = min(score, NEEDS_REVIEW_THRESHOLD)
    score = min(score, 1.0)
    future_publication = _future_publication(candidate.published_at)
    if future_publication is not None:
        score = min(score, NEEDS_REVIEW_THRESHOLD)

    if score >= RELEVANT_THRESHOLD:
        status = "relevant"
    elif score >= NEEDS_REVIEW_THRESHOLD:
        status = "needs_review"
    else:
        status = "irrelevant"

    reason = _reason(matched_primary, matched_generic, matched_phrases)
    policy_reasons = _policy_reasons(
        _required_phrase_policy_reason(candidate, topic) if required_phrase_policy else None,
        required_phrase_matches,
        negative_phrase_matches,
        concept_gate if concept_policy else None,
    )
    if policy_reasons:
        reason = f"{reason}; {'; '.join(policy_reasons)}"
    if future_publication is not None:
        reason = f"{reason}; publication date is in the future ({future_publication})"
    metadata = {
        **candidate.metadata,
        "relevance": {
            "score": round(score, 3),
            "status": status,
            "reason": reason,
            "matched_terms": [*matched_primary, *matched_generic],
            "matched_phrases": matched_phrases,
            "required_phrase_matches": required_phrase_matches,
            "negative_phrase_matches": negative_phrase_matches,
            "concept_gate": concept_gate,
            "future_publication": future_publication,
        },
    }
    return replace(candidate, metadata=metadata)


def _strict_topic_policy_applies(candidate: SourceCandidate, topic: TopicConfig) -> bool:
    if candidate.source_type.value == "paper":
        return True
    return candidate.source_type.value == "repository" and topic.source_intent == "research_brief"


def _concept_gate(topic: TopicConfig, text: str) -> dict[str, object]:
    if not topic.concept_groups:
        return {
            "configured": False,
            "passed": False,
            "decision_rule": None,
            "reason": None,
            "matched_groups": [],
            "matched_aliases": {},
            "matched_negative_groups": [],
            "matched_negative_aliases": [],
        }
    matched_aliases: dict[str, list[str]] = {}
    negative_aliases: list[str] = []
    for group, aliases in topic.concept_groups.items():
        matches = _configured_phrase_matches(aliases, text)
        if not matches:
            continue
        matched_aliases[group] = matches
        if _is_negative_concept_group(group):
            negative_aliases.extend(matches)

    matched_groups = sorted(
        group for group in matched_aliases if not _is_negative_concept_group(group)
    )
    matched_negative_groups = sorted(
        group for group in matched_aliases if _is_negative_concept_group(group)
    )
    benchmark_anchor = any(
        _normalize(alias) in BENCHMARK_ANCHOR_ALIASES
        for aliases in matched_aliases.values()
        for alias in aliases
    )
    has_agent_context = "agent_context" in matched_groups
    has_memory_mechanism = "memory_mechanism" in matched_groups
    has_evaluation_signal = "evaluation_signal" in matched_groups
    passed = benchmark_anchor or (
        has_agent_context and (has_memory_mechanism or has_evaluation_signal)
    )
    if benchmark_anchor:
        decision_rule = "benchmark_anchor"
    elif has_agent_context and has_memory_mechanism:
        decision_rule = "agent_context+memory_mechanism"
    elif has_agent_context and has_evaluation_signal:
        decision_rule = "agent_context+evaluation_signal"
    else:
        decision_rule = "missing_required_concept_combination"
    return {
        "configured": True,
        "passed": passed,
        "decision_rule": decision_rule,
        "reason": None if passed else "concept gate missing required concept combination",
        "matched_groups": matched_groups,
        "matched_aliases": {
            group: matched_aliases[group]
            for group in sorted(matched_aliases)
            if not _is_negative_concept_group(group)
        },
        "matched_negative_groups": matched_negative_groups,
        "matched_negative_aliases": sorted(negative_aliases),
    }


def _topic_terms(topic: TopicConfig) -> set[str]:
    text = _normalize(" ".join([topic.id, *topic.queries, *topic.paper_queries]))
    return {token for token in _tokens(text) if token not in STOPWORDS}


def _topic_phrases(topic: TopicConfig) -> set[str]:
    phrases = set()
    for raw in [topic.id, *topic.queries, *topic.paper_queries]:
        phrase = _query_phrase(raw)
        if len(_tokens(phrase)) >= 2:
            phrases.add(phrase)
    return phrases


def _query_phrase(query: str) -> str:
    tokens = [
        token
        for token in _tokens(_normalize(query))
        if token not in STOPWORDS and token not in GENERIC_TERMS
    ]
    return " ".join(tokens)


def _configured_phrase_matches(phrases: list[str], text: str) -> list[str]:
    matches = []
    for raw in phrases:
        phrase = _normalize(raw)
        if phrase and phrase in text:
            matches.append(raw)
    return matches


def _is_negative_concept_group(group: str) -> bool:
    return group.startswith("negative")


def _policy_reasons(
    required_phrase_policy_reason: str | None,
    required_matches: list[str],
    negative_matches: list[str],
    concept_gate: dict[str, object] | None,
) -> list[str]:
    reasons = []
    if required_phrase_policy_reason and not required_matches:
        reasons.append(required_phrase_policy_reason)
    if concept_gate and concept_gate.get("reason"):
        reasons.append(str(concept_gate["reason"]))
    if negative_matches:
        reasons.append("configured negative phrase matched")
    if concept_gate and concept_gate.get("matched_negative_aliases"):
        reasons.append("negative concept matched")
    return reasons


def _required_phrase_policy_reason(candidate: SourceCandidate, topic: TopicConfig) -> str | None:
    if not topic.required_phrases:
        return None
    if candidate.source_type.value == "paper":
        return "no configured required phrase matched"
    if candidate.source_type.value == "repository" and topic.source_intent == "research_brief":
        return "research brief repo missing configured required phrase"
    return None


def _phrase_matches_topic(phrase: str, topic_primary_terms: set[str]) -> bool:
    phrase_terms = {_singular(token) for token in _tokens(phrase)} - GENERIC_TERMS
    return len(phrase_terms & topic_primary_terms) >= 2


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _future_publication(published_at: str | None) -> str | None:
    if not published_at:
        return None
    raw = published_at.strip()
    if not raw:
        return None
    try:
        if re.fullmatch(r"\d{4}", raw):
            published = date(int(raw), 1, 1)
        else:
            published = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    today = datetime.now(UTC).date()
    if published > today:
        return published.isoformat()
    return None


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
    severity = "warning" if relevance.get("future_publication") else "info"
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
