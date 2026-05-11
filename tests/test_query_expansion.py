from research_radar.config import TopicConfig
from research_radar.discovery.query_expansion import (
    paper_query_variants,
    query_expansion_metadata,
    topic_for_connector,
)


def test_paper_query_variants_add_research_suffixes() -> None:
    variants = paper_query_variants(["agent memory systems"])

    assert variants == [
        "agent memory systems",
        "agent memory systems paper",
        "agent memory systems benchmark",
        "agent memory systems survey",
        "agent memory systems arxiv",
    ]


def test_topic_for_connector_expands_only_paper_connectors() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems"],
        source_intent="research_brief",
    )

    arxiv_topic = topic_for_connector(topic, "arxiv")
    github_topic = topic_for_connector(topic, "github")

    assert len(arxiv_topic.queries) == 5
    assert github_topic.queries == ["agent memory systems"]


def test_query_expansion_metadata_records_audit_data() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems"],
        source_intent="research_brief",
    )
    expanded = topic_for_connector(topic, "semantic_scholar")

    metadata = query_expansion_metadata(topic, expanded, "semantic_scholar")

    assert metadata == {
        "source_intent": "research_brief",
        "connector": "semantic_scholar",
        "original_queries": ["agent memory systems"],
        "expanded_queries": [
            "agent memory systems",
            "agent memory systems paper",
            "agent memory systems benchmark",
            "agent memory systems survey",
            "agent memory systems arxiv",
        ],
    }
