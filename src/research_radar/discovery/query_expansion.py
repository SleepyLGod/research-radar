"""Deterministic query expansion for research discovery."""

from __future__ import annotations

from dataclasses import replace

from research_radar.config import TopicConfig
from research_radar.discovery.source_selection import RESEARCH_BRIEF

PAPER_CONNECTOR_NAMES = {"arxiv", "semantic_scholar", "openalex"}
PAPER_QUERY_SUFFIXES = ("paper", "benchmark", "survey", "arxiv")


def paper_query_variants(queries: list[str]) -> list[str]:
    """Return deterministic paper-focused query variants."""

    variants: list[str] = []
    seen: set[str] = set()
    for query in queries:
        stripped = query.strip()
        if not stripped:
            continue
        for variant in _variants_for_query(stripped):
            key = variant.casefold()
            if key in seen:
                continue
            seen.add(key)
            variants.append(variant)
    return variants


def topic_for_connector(topic: TopicConfig, connector_name: str) -> TopicConfig:
    """Return connector-specific topic settings."""

    if topic.source_intent != RESEARCH_BRIEF:
        return topic
    if connector_name not in PAPER_CONNECTOR_NAMES:
        return topic
    expanded_queries = _paper_connector_queries(topic)
    if expanded_queries == topic.queries:
        return topic
    return replace(topic, queries=expanded_queries)


def query_expansion_metadata(
    original_topic: TopicConfig,
    connector_topic: TopicConfig,
    connector_name: str,
) -> dict[str, object] | None:
    """Return audit metadata for connector-specific query expansion."""

    if connector_topic.queries == original_topic.queries:
        return None
    return {
        "source_intent": original_topic.source_intent,
        "connector": connector_name,
        "original_queries": original_topic.queries,
        "paper_queries": original_topic.paper_queries,
        "web_queries": original_topic.web_queries,
        "exclusion_terms": original_topic.exclusion_terms,
        "expanded_queries": connector_topic.queries,
    }


def _paper_connector_queries(topic: TopicConfig) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for query in [*topic.paper_queries, *paper_query_variants(topic.queries)]:
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries


def _variants_for_query(query: str) -> list[str]:
    variants = [query]
    normalized_words = set(query.casefold().split())
    for suffix in PAPER_QUERY_SUFFIXES:
        if suffix in normalized_words:
            continue
        variants.append(f"{query} {suffix}")
    return variants
