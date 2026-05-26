"""Deterministic source centrality scoring for research briefs."""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from research_radar.config import TopicConfig
from research_radar.models import SourceCandidate, SourceType

RESEARCH_TERMS = {
    "architecture",
    "benchmark",
    "benchmarks",
    "dataset",
    "datasets",
    "evaluation",
    "framework",
    "method",
    "metric",
    "metrics",
    "pipeline",
    "system",
    "systems",
}

DOMAIN_NARROWING_TERMS = {
    "biomedical",
    "clinical",
    "commerce",
    "e-commerce",
    "ecommerce",
    "eating",
    "finance",
    "financial",
    "food",
    "geospatial",
    "healthcare",
    "khmer",
    "law",
    "legal",
    "medical",
    "news",
    "nutrition",
    "optical",
    "retail",
    "russian",
    "social",
}

DOMAIN_EQUIVALENTS = {
    "clinical": {"clinical", "healthcare", "medical"},
    "commerce": {"commerce", "ecommerce", "e-commerce", "retail"},
    "e-commerce": {"commerce", "ecommerce", "e-commerce", "retail"},
    "ecommerce": {"commerce", "ecommerce", "e-commerce", "retail"},
    "finance": {"finance", "financial"},
    "financial": {"finance", "financial"},
    "healthcare": {"clinical", "healthcare", "medical"},
    "law": {"law", "legal"},
    "legal": {"law", "legal"},
    "medical": {"clinical", "healthcare", "medical"},
    "retail": {"commerce", "ecommerce", "e-commerce", "retail"},
}

CANONICAL_PAPER_DOMAINS = {
    "aclanthology.org",
    "arxiv.org",
    "openreview.net",
    "semanticscholar.org",
}


def score_source_centrality(candidate: SourceCandidate, topic: TopicConfig) -> SourceCandidate:
    """Attach deterministic centrality metadata for paper selection."""

    if candidate.source_type != SourceType.PAPER:
        return replace(
            candidate,
            metadata={
                **candidate.metadata,
                "source_centrality": {
                    "score": 0.0,
                    "positive_signals": [],
                    "negative_signals": ["not a paper source"],
                    "reason": "centrality scoring applies to paper sources only",
                },
            },
        )

    text = _normalized_source_text(candidate)
    topic_text = _normalized_topic_text(topic)
    positive: list[str] = []
    negative: list[str] = []
    score = 0.20

    query_matches = _matched_phrases([*topic.queries, *topic.paper_queries], text)
    if query_matches:
        score += min(0.22, 0.08 * len(query_matches))
        positive.append(f"topic_query={', '.join(query_matches[:3])}")

    concept_matches = _matched_concept_aliases(topic, text)
    if concept_matches:
        score += min(0.28, 0.06 * len(concept_matches))
        positive.append(f"concept_alias={', '.join(concept_matches[:4])}")

    research_matches = sorted(RESEARCH_TERMS & set(_tokens(text)))
    if research_matches:
        score += min(0.16, 0.04 * len(research_matches))
        positive.append(f"research_terms={', '.join(research_matches[:4])}")

    source_name = candidate.source_name.lower()
    canonical_domain = _canonical_paper_domain(candidate.url)
    if canonical_domain or source_name in {"arxiv", "openreview", "semantic_scholar"}:
        score += 0.08
        positive.append(f"canonical_paper_source={canonical_domain or source_name}")

    domain_matches = sorted(DOMAIN_NARROWING_TERMS & set(_tokens(text)))
    topic_domain_matches = sorted(DOMAIN_NARROWING_TERMS & set(_tokens(topic_text)))
    requested_domains = _expand_domain_terms(topic_domain_matches)
    unrequested_domains = [
        term for term in domain_matches if term not in requested_domains
    ]
    if unrequested_domains:
        score -= min(0.35, 0.18 + 0.06 * len(unrequested_domains))
        negative.append(f"domain_specific={', '.join(unrequested_domains[:4])}")

    score = round(max(0.0, min(score, 1.0)), 3)
    if not positive:
        positive.append("paper source baseline")
    reason = "; ".join([*positive, *negative])
    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "source_centrality": {
                "score": score,
                "positive_signals": positive,
                "negative_signals": negative,
                "reason": reason,
            },
        },
    )


def _normalized_source_text(candidate: SourceCandidate) -> str:
    return _normalize(
        " ".join(
            [
                candidate.title,
                candidate.summary or "",
                candidate.source_name,
                candidate.source_type.value,
            ]
        )
    )


def _normalized_topic_text(topic: TopicConfig) -> str:
    aliases = [
        alias
        for group, group_aliases in topic.concept_groups.items()
        if not group.startswith("negative")
        for alias in group_aliases
    ]
    return _normalize(
        " ".join(
            [
                *topic.queries,
                *topic.paper_queries,
                *topic.required_phrases,
                *aliases,
            ]
        )
    )


def _matched_concept_aliases(topic: TopicConfig, text: str) -> list[str]:
    aliases = [
        alias
        for group, group_aliases in topic.concept_groups.items()
        if not group.startswith("negative")
        for alias in group_aliases
    ]
    return _matched_phrases(aliases, text)


def _matched_phrases(phrases: list[str], text: str) -> list[str]:
    matches = []
    for phrase in phrases:
        normalized = _normalize(phrase)
        if normalized and normalized in text:
            matches.append(phrase)
    return matches


def _canonical_paper_domain(url: str) -> str | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domain in CANONICAL_PAPER_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return None


def _expand_domain_terms(terms: list[str]) -> set[str]:
    expanded = set(terms)
    for term in terms:
        expanded.update(DOMAIN_EQUIVALENTS.get(term, {term}))
    return expanded


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("-", " "))
