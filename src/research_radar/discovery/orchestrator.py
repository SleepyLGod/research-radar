"""Staged discovery orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import urlparse

from research_radar.analysis.research_plan import (
    ResearchPlan,
    planned_topic_for_connector,
)
from research_radar.config import TopicConfig
from research_radar.discovery.base import DiscoveryConnector, DiscoveryContext
from research_radar.discovery.dedupe import dedupe_candidates
from research_radar.discovery.query_expansion import (
    query_expansion_metadata,
    topic_for_connector,
)
from research_radar.exceptions import DiscoveryError
from research_radar.models import ReviewFinding, SourceCandidate

PRIMARY_SOURCE_CONNECTORS = {"arxiv", "semantic_scholar", "openalex"}
WEB_SEARCH_CONNECTORS = {"web_search"}
REPOSITORY_CONNECTORS = {"github"}
CONTEXT_SOURCE_CONNECTORS = {"rss"}

PRIMARY_SOURCES_STAGE = "primary_sources"
WEB_SEARCH_STAGE = "web_search"
REPOSITORIES_STAGE = "repositories"
CONTEXT_SOURCES_STAGE = "context_sources"
OTHER_STAGE = "other"

STAGE_ORDER = (
    PRIMARY_SOURCES_STAGE,
    WEB_SEARCH_STAGE,
    REPOSITORIES_STAGE,
    CONTEXT_SOURCES_STAGE,
    OTHER_STAGE,
)
STAGE_RANK = {stage: index for index, stage in enumerate(STAGE_ORDER)}


@dataclass(frozen=True)
class DiscoveryResult:
    """Output from staged discovery."""

    candidates: list[SourceCandidate]
    findings: list[ReviewFinding]
    query_expansions: dict[str, object]
    stage_counts: dict[str, int]
    provider_counts: dict[str, int]
    duplicate_count: int = 0


class DiscoveryOrchestrator:
    """Run discovery connectors in a provenance-preserving staged order."""

    def __init__(self, connectors: list[DiscoveryConnector]) -> None:
        self._connectors = connectors

    def discover(
        self,
        topic: TopicConfig,
        *,
        limit: int,
        trusted_domains: list[str] | None = None,
        research_plan: ResearchPlan | None = None,
    ) -> DiscoveryResult:
        """Discover candidates across staged connectors."""

        all_candidates: list[SourceCandidate] = []
        findings: list[ReviewFinding] = []
        query_expansions: dict[str, object] = {}
        stage_counts: dict[str, int] = {stage: 0 for stage in STAGE_ORDER}
        provider_counts: dict[str, int] = {}
        configured_trusted_domains = trusted_domains or []

        for connector, stage in self._ordered_connectors():
            connector_topic = topic_for_connector(topic, connector.name)
            if research_plan is not None:
                connector_topic = planned_topic_for_connector(
                    connector_topic,
                    connector.name,
                    research_plan,
                )
            expansion = query_expansion_metadata(topic, connector_topic, connector.name)
            if expansion is not None:
                query_expansions[connector.name] = {
                    **expansion,
                    "discovery_stage": stage,
                }
            context = DiscoveryContext(
                topic=connector_topic,
                limit=limit,
                metadata={"discovery_stage": stage},
            )
            try:
                raw_candidates = connector.discover(context)
            except DiscoveryError as exc:
                findings.append(_discovery_failure(connector.name, stage, exc))
                continue
            candidates = [
                _annotate_candidate(
                    candidate,
                    connector_name=connector.name,
                    stage=stage,
                    topic=connector_topic,
                    trusted_domains=configured_trusted_domains,
                )
                for candidate in raw_candidates
            ]
            all_candidates.extend(candidates)
            stage_counts[stage] += len(candidates)
            provider_counts[connector.name] = provider_counts.get(connector.name, 0) + len(
                candidates
            )

        candidates = dedupe_candidates(all_candidates)
        return DiscoveryResult(
            candidates=candidates,
            findings=findings,
            query_expansions=query_expansions,
            stage_counts=stage_counts,
            provider_counts=provider_counts,
            duplicate_count=max(0, len(all_candidates) - len(candidates)),
        )

    def _ordered_connectors(self) -> list[tuple[DiscoveryConnector, str]]:
        indexed = [
            (index, connector, discovery_stage_for_connector(connector.name))
            for index, connector in enumerate(self._connectors)
        ]
        return [
            (connector, stage)
            for _, connector, stage in sorted(
                indexed,
                key=lambda item: (STAGE_RANK[item[2]], item[0]),
            )
        ]


def discovery_stage_for_connector(connector_name: str) -> str:
    """Return the orchestration stage for a connector name."""

    if connector_name in PRIMARY_SOURCE_CONNECTORS:
        return PRIMARY_SOURCES_STAGE
    if connector_name in WEB_SEARCH_CONNECTORS:
        return WEB_SEARCH_STAGE
    if connector_name in REPOSITORY_CONNECTORS:
        return REPOSITORIES_STAGE
    if connector_name in CONTEXT_SOURCE_CONNECTORS:
        return CONTEXT_SOURCES_STAGE
    return OTHER_STAGE


def _annotate_candidate(
    candidate: SourceCandidate,
    *,
    connector_name: str,
    stage: str,
    topic: TopicConfig,
    trusted_domains: list[str],
) -> SourceCandidate:
    matched_domain = _trusted_domain_match(
        candidate.url,
        [*trusted_domains, *topic.priority_sources],
    )
    metadata = {
        **candidate.metadata,
        "discovery_stage": stage,
        "discovery_provider": connector_name,
        "matched_query": _matched_query(candidate, topic.queries),
        "trusted_domain_match": matched_domain,
        "selection_rationale": (
            f"Discovered by {connector_name} during {stage}; "
            f"trusted_domain={matched_domain or 'none'}."
        ),
    }
    return replace(candidate, metadata=metadata)


def _trusted_domain_match(url: str, trusted_domains: list[str]) -> str | None:
    host = urlparse(url).netloc.casefold()
    for domain in trusted_domains:
        normalized = domain.casefold()
        if host == normalized or host.endswith("." + normalized):
            return domain
    return None


def _matched_query(candidate: SourceCandidate, queries: list[str]) -> str | None:
    if not queries:
        return None
    text = _normalize(" ".join([candidate.title, candidate.summary or "", candidate.url]))
    for query in queries:
        if _normalize(query) in text:
            return query
    for query in queries:
        query_terms = [token for token in _tokens(_normalize(query)) if len(token) > 2]
        if query_terms and all(term in text for term in query_terms[:2]):
            return query
    return queries[0]


def _discovery_failure(
    connector_name: str,
    stage: str,
    exc: DiscoveryError,
) -> ReviewFinding:
    return ReviewFinding(
        severity="warning",
        message=f"{connector_name} discovery failed: {exc}",
        metadata={
            "kind": "discovery_failed",
            "discovery_provider": connector_name,
            "discovery_stage": stage,
        },
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("-", " ")).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)
