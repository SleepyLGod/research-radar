from research_radar.analysis.research_plan import (
    build_research_plan,
    planned_topic_for_connector,
)
from research_radar.config import TopicConfig


def test_research_plan_builds_audit_query_packs() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory"],
        paper_queries=["Memory in the LLM Era"],
        web_queries=["agent memory systems paper"],
        exclusion_terms=["translation memory"],
    )

    plan = build_research_plan(
        topic,
        trusted_domains=["arxiv.org", "openreview.net", "github.com"],
    )

    assert plan.topic_id == "agent-memory"
    assert "Memory in the LLM Era" in plan.paper_queries
    assert "agent memory benchmark" in plan.paper_queries
    assert "agent memory systems paper" in plan.web_queries
    assert "site:arxiv.org agent memory" in plan.web_queries
    assert "site:openreview.net agent memory" in plan.web_queries
    assert "site:github.com agent memory" not in plan.web_queries
    assert "translation memory" in plan.explicit_exclusions
    assert plan.unsupported_or_rejected_claims


def test_planned_topic_for_connector_uses_plan_query_packs() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory"])
    plan = build_research_plan(topic, trusted_domains=["arxiv.org"])

    paper_topic = planned_topic_for_connector(topic, "arxiv", plan)
    openalex_topic = planned_topic_for_connector(topic, "openalex", plan)
    web_topic = planned_topic_for_connector(topic, "web_search", plan)
    repo_topic = planned_topic_for_connector(topic, "github", plan)

    assert paper_topic.queries == plan.paper_queries
    assert openalex_topic.queries == plan.paper_queries
    assert web_topic.queries == plan.web_queries
    assert repo_topic.queries == plan.repository_queries
