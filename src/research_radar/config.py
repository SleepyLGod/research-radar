"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_radar.exceptions import ConfigError


@dataclass(frozen=True)
class TopicConfig:
    """Research topic configuration."""

    id: str
    queries: list[str]
    paper_queries: list[str] = field(default_factory=list)
    priority_sources: list[str] = field(default_factory=list)
    source_intent: str = "research_brief"


@dataclass(frozen=True)
class ProjectConfig:
    """Project display configuration."""

    name: str = "ResearchRadar"


@dataclass(frozen=True)
class CadenceConfig:
    """Schedule configuration."""

    daily_monitor: str = "09:00"
    weekly_deep_dive: str = "Sunday 10:00"


@dataclass(frozen=True)
class ModelConfig:
    """Model selection configuration."""

    scout: str = "deepseek-v4-flash"
    analyst: str = "deepseek-v4-pro"
    verifier: str = "codex_or_openai_high_reasoning"


@dataclass(frozen=True)
class PublishingConfig:
    """Publishing configuration."""

    channel: str = "wechat_draft"
    auto_publish: bool = False


@dataclass(frozen=True)
class SecurityConfig:
    """Security configuration."""

    secret_backend: str = "keychain"
    encrypt_storage: bool = True


@dataclass(frozen=True)
class AppConfig:
    """Complete ResearchRadar configuration."""

    project: ProjectConfig
    topics: list[TopicConfig]
    cadence: CadenceConfig = field(default_factory=CadenceConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    publishing: PublishingConfig = field(default_factory=PublishingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def topic(self, topic_id: str) -> TopicConfig:
        """Return a topic by id."""

        for topic in self.topics:
            if topic.id == topic_id:
                return topic
        raise ConfigError(f"Unknown topic: {topic_id}")


def load_config(path: Path) -> AppConfig:
    """Load YAML configuration from disk."""

    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError("PyYAML is required to load config files.") from exc

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("Config file must contain a YAML mapping.")
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> AppConfig:
    """Parse an already-loaded configuration mapping."""

    project_data = _mapping(data.get("project", {}), "project")
    topics_data = data.get("topics")
    if not isinstance(topics_data, list) or not topics_data:
        raise ConfigError("Config must contain at least one topic.")

    topics = []
    for item in topics_data:
        item_map = _mapping(item, "topic")
        topic_id = _required_string(item_map, "id")
        queries = _string_list(item_map.get("queries"), f"topic {topic_id} queries")
        topics.append(
            TopicConfig(
                id=topic_id,
                queries=queries,
                paper_queries=_string_list(
                    item_map.get("paper_queries", []),
                    f"topic {topic_id} paper_queries",
                    allow_empty=True,
                ),
                priority_sources=_string_list(
                    item_map.get("priority_sources", []),
                    f"topic {topic_id} priority_sources",
                    allow_empty=True,
                ),
                source_intent=_source_intent(item_map.get("source_intent", "research_brief")),
            )
        )

    publishing = _mapping(data.get("publishing", {}), "publishing")
    if bool(publishing.get("auto_publish", False)):
        raise ConfigError("auto_publish=true is not allowed before the planned v1 boundary.")

    return AppConfig(
        project=ProjectConfig(name=str(project_data.get("name", "ResearchRadar"))),
        topics=topics,
        cadence=CadenceConfig(**_mapping(data.get("cadence", {}), "cadence")),
        models=ModelConfig(**_mapping(data.get("models", {}), "models")),
        publishing=PublishingConfig(**publishing),
        security=SecurityConfig(**_mapping(data.get("security", {}), "security")),
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping.")
    return value


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing required string: {key}")
    return value


def _string_list(value: Any, name: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list.")
    result = [item for item in value if isinstance(item, str) and item.strip()]
    if not allow_empty and not result:
        raise ConfigError(f"{name} must contain at least one string.")
    if len(result) != len(value):
        raise ConfigError(f"{name} must contain only strings.")
    return result


def _source_intent(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("source_intent must be a string.")
    if value not in {"research_brief", "implementation_scan"}:
        raise ConfigError("source_intent must be research_brief or implementation_scan.")
    return value
