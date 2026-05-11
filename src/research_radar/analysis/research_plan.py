"""Deterministic research planning before discovery."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from research_radar.config import TopicConfig
from research_radar.discovery.query_expansion import paper_query_variants
from research_radar.models import dataclass_to_dict

PAPER_CONNECTORS = {"arxiv", "semantic_scholar", "openalex"}
WEB_CONNECTORS = {"web_search"}
REPOSITORY_CONNECTORS = {"github"}
SITE_QUERY_DOMAINS = {
    "arxiv.org",
    "openreview.net",
    "aclanthology.org",
    "paperswithcode.com",
    "proceedings.neurips.cc",
    "dl.acm.org",
}


@dataclass(frozen=True)
class ResearchPlan:
    """Audit-ready plan for one research run."""

    topic_id: str
    neutral_scope: str
    explicit_exclusions: list[str]
    research_questions: list[str]
    source_priorities: list[str]
    paper_queries: list[str]
    web_queries: list[str]
    repository_queries: list[str]
    risk_checks: list[str]
    unsupported_or_rejected_claims: list[str] = field(default_factory=list)


def build_research_plan(topic: TopicConfig, *, trusted_domains: list[str]) -> ResearchPlan:
    """Build a conservative plan from topic config without making factual claims."""

    base_queries = _unique(topic.queries)
    paper_queries = _unique([*topic.paper_queries, *paper_query_variants(base_queries)])
    web_queries = _unique(
        [
            *topic.web_queries,
            *base_queries,
            *[
                f"site:{domain} {query}"
                for domain in _site_query_domains(trusted_domains)
                for query in base_queries
            ],
        ]
    )
    repository_queries = _unique(
        [
            *base_queries,
            *[f"{query} benchmark implementation" for query in base_queries],
        ]
    )
    return ResearchPlan(
        topic_id=topic.id,
        neutral_scope=(
            f"Research brief for `{topic.id}` using configured seed queries; "
            "the run must prefer primary papers and treat repositories or blogs as "
            "supporting implementation/context evidence unless the topic asks otherwise."
        ),
        explicit_exclusions=topic.exclusion_terms,
        research_questions=[
            "What concrete problem is the current work trying to solve?",
            "Which primary papers or benchmark papers are most relevant?",
            "What is the actual mechanism or method, beyond author framing?",
            "How does the work compare with related work and baselines?",
            "Which limitations, weak evaluations, or missing ablations are evidence-backed?",
        ],
        source_priorities=[
            "primary paper",
            "benchmark paper",
            "official project page",
            "implementation repository",
            "primary technical blog",
        ],
        paper_queries=paper_queries,
        web_queries=web_queries,
        repository_queries=repository_queries,
        risk_checks=[
            "Do not publish claims without source anchors.",
            "Do not let generic terms such as system, benchmark, or generation dominate relevance.",
            (
                "Do not deep-read a repository as the primary source for a research brief "
                "when a viable paper exists."
            ),
            "Mark the run degraded when no relevant paper is found for a research-oriented topic.",
            "Keep speculation and rejected critique out of publishable article sections.",
        ],
        unsupported_or_rejected_claims=[
            "The topic is important.",
            "A repository is a research contribution without paper or evaluation evidence.",
            "A paper is novel solely because its abstract says so.",
        ],
    )


def planned_topic_for_connector(
    topic: TopicConfig,
    connector_name: str,
    plan: ResearchPlan,
) -> TopicConfig:
    """Return connector-specific queries from the research plan."""

    if connector_name in PAPER_CONNECTORS:
        return replace(topic, queries=plan.paper_queries)
    if connector_name in WEB_CONNECTORS:
        return replace(topic, queries=plan.web_queries)
    if connector_name in REPOSITORY_CONNECTORS:
        return replace(topic, queries=plan.repository_queries)
    return topic


def research_plan_to_dict(plan: ResearchPlan) -> dict[str, object]:
    """Convert a research plan to a JSON-friendly dictionary."""

    return dataclass_to_dict(plan)


def _site_query_domains(trusted_domains: list[str]) -> list[str]:
    return [domain for domain in trusted_domains if domain in SITE_QUERY_DOMAINS]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result
