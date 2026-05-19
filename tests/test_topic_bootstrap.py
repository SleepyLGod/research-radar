from pathlib import Path

import pytest
import yaml

from research_radar.analysis.providers import StaticProvider
from research_radar.config import parse_config
from research_radar.exceptions import ResearchRadarError
from research_radar.topic_bootstrap import (
    bootstrap_topic_draft,
    default_topic_draft_path,
    render_topic_draft_yaml,
    write_topic_draft,
)


def test_bootstrap_topic_creates_stable_safe_id() -> None:
    topic = bootstrap_topic_draft("diffusion world models for embodied agents")

    assert topic.id == "diffusion-world-models-embodied-agents"
    assert topic.source_intent == "research_brief"
    assert topic.report_language == "en"


def test_bootstrap_topic_includes_search_queries_and_concepts() -> None:
    topic = bootstrap_topic_draft("diffusion world models for embodied agents")

    assert topic.queries
    assert topic.paper_queries
    assert "diffusion world models embodied agents benchmark" in topic.paper_queries
    assert set(topic.concept_groups) == {
        "agent_context",
        "memory_mechanism",
        "evaluation_signal",
        "negative_compute_or_training",
    }
    assert "world model" in topic.concept_groups["memory_mechanism"]
    assert "diffusion model" in topic.concept_groups["memory_mechanism"]
    assert "embodied agent" in topic.concept_groups["memory_mechanism"]


def test_topic_draft_yaml_parses_as_config_topic() -> None:
    topic = bootstrap_topic_draft("diffusion world models for embodied agents")
    snippet = render_topic_draft_yaml(topic)
    parsed_topics = yaml.safe_load(snippet)

    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": parsed_topics,
        }
    )

    assert config.topic("diffusion-world-models-embodied-agents").paper_queries
    assert "&id" not in snippet
    assert "*id" not in snippet


def test_empty_topic_text_is_rejected() -> None:
    with pytest.raises(ResearchRadarError, match="Topic text cannot be empty"):
        bootstrap_topic_draft("   ")


def test_default_topic_draft_path_uses_topic_drafts_dir(tmp_path: Path) -> None:
    path = default_topic_draft_path(tmp_path, "diffusion-world-models")

    assert path == tmp_path / "topic_drafts" / "diffusion-world-models.yaml"


def test_write_topic_draft_supports_default_and_custom_paths(tmp_path: Path) -> None:
    topic = bootstrap_topic_draft("diffusion world models")
    default_path = write_topic_draft(tmp_path, topic)
    custom_path = write_topic_draft(
        tmp_path,
        topic,
        output=tmp_path / "custom-topic.yaml",
    )

    assert default_path == (tmp_path / "topic_drafts" / "diffusion-world-models.yaml").resolve()
    assert custom_path == (tmp_path / "custom-topic.yaml").resolve()
    assert "Draft topic profile" in default_path.read_text(encoding="utf-8")
    assert "diffusion-world-models" in custom_path.read_text(encoding="utf-8")


def test_bootstrap_topic_uses_provider_structured_output() -> None:
    provider = StaticProvider(
        """
        {
          "id": "diffusion-world-models",
          "queries": ["diffusion world models"],
          "paper_queries": ["diffusion world models benchmark"],
          "web_queries": ["diffusion world models github"],
          "negative_phrases": ["text-to-image only"],
          "concept_groups": {
            "agent_context": ["world model"],
            "memory_mechanism": ["diffusion model"],
            "evaluation_signal": ["planning benchmark"],
            "negative_compute_or_training": ["text-to-image only"]
          },
          "priority_sources": ["arxiv.org", "github.com"]
        }
        """
    )

    topic = bootstrap_topic_draft(
        "diffusion world models",
        language="zh",
        provider=provider,
        model="fake-bootstrap",
    )

    assert topic.id == "diffusion-world-models"
    assert topic.report_language == "zh"
    assert topic.paper_queries == ["diffusion world models benchmark"]
    assert topic.priority_sources == ["arxiv.org", "github.com"]


def test_gitignore_covers_topic_drafts() -> None:
    ignore_text = Path(".gitignore").read_text(encoding="utf-8")

    assert "topic_drafts/" in ignore_text
