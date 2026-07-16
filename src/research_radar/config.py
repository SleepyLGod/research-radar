"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from research_radar.exceptions import ConfigError


@dataclass(frozen=True)
class TopicConfig:
    """Research topic configuration."""

    id: str
    queries: list[str]
    paper_queries: list[str] = field(default_factory=list)
    web_queries: list[str] = field(default_factory=list)
    exclusion_terms: list[str] = field(default_factory=list)
    required_phrases: list[str] = field(default_factory=list)
    negative_phrases: list[str] = field(default_factory=list)
    concept_groups: dict[str, list[str]] = field(default_factory=dict)
    priority_sources: list[str] = field(default_factory=list)
    source_intent: str = "research_brief"
    report_language: str = "en"


@dataclass(frozen=True)
class WebSearchConfig:
    """Optional generic web-search connector configuration."""

    provider: str | None = None
    endpoint: str | None = None
    header_secret_name: str | None = None
    max_results: int = 5
    search_depth: str = "basic"
    timeout_seconds: int = 30


@dataclass(frozen=True)
class DiscoveryConfig:
    """Discovery orchestration configuration."""

    trusted_domains: list[str] = field(default_factory=list)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)


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
class ModelProviderConfig:
    """One named model provider instance."""

    kind: str
    base_url: str | None = None
    api_key_secret: str | None = None
    command: str | None = None
    timeout_seconds: int = 120
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class TaskRouteConfig:
    """Model route for one ResearchRadar task."""

    provider: str
    model: str


@dataclass(frozen=True)
class ModelConfig:
    """Model selection configuration."""

    scout: str = "deepseek-v4-flash"
    analyst: str = "deepseek-v4-pro"
    verifier: str = "codex_or_openai_high_reasoning"
    task_routes: dict[str, TaskRouteConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishingConfig:
    """Publishing configuration."""

    channel: str = "wechat_draft"
    auto_publish: bool = False


@dataclass(frozen=True)
class ArchivePublishConfig:
    """Optional settings for publishing a static archive through Git."""

    checkout: Path | None = None
    output_subdir: str = "archive"
    base_url: str | None = None
    site_language: str | None = None
    remote: str = "origin"
    branch: str = "gh-pages"


@dataclass(frozen=True)
class EmailPublishConfig:
    """Optional private SMTP email delivery settings."""

    smtp_host: str | None = None
    smtp_port: int = 465
    security: str = "tls"
    username: str | None = None
    password_secret: str = "email.smtp_password"
    from_address: str | None = None
    to_address: str | None = None
    timeout_seconds: int = 30


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
    model_providers: dict[str, ModelProviderConfig] = field(default_factory=dict)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    cadence: CadenceConfig = field(default_factory=CadenceConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    publishing: PublishingConfig = field(default_factory=PublishingConfig)
    archive: ArchivePublishConfig = field(default_factory=ArchivePublishConfig)
    email: EmailPublishConfig = field(default_factory=EmailPublishConfig)
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
                web_queries=_string_list(
                    item_map.get("web_queries", []),
                    f"topic {topic_id} web_queries",
                    allow_empty=True,
                ),
                exclusion_terms=_string_list(
                    item_map.get("exclusion_terms", []),
                    f"topic {topic_id} exclusion_terms",
                    allow_empty=True,
                ),
                required_phrases=_string_list(
                    item_map.get("required_phrases", []),
                    f"topic {topic_id} required_phrases",
                    allow_empty=True,
                ),
                negative_phrases=_string_list(
                    item_map.get("negative_phrases", []),
                    f"topic {topic_id} negative_phrases",
                    allow_empty=True,
                ),
                concept_groups=_concept_groups(
                    item_map.get("concept_groups", {}),
                    f"topic {topic_id} concept_groups",
                ),
                priority_sources=_string_list(
                    item_map.get("priority_sources", []),
                    f"topic {topic_id} priority_sources",
                    allow_empty=True,
                ),
                source_intent=_source_intent(item_map.get("source_intent", "research_brief")),
                report_language=_report_language(item_map.get("report_language", "en")),
            )
        )

    publishing = _mapping(data.get("publishing", {}), "publishing")
    if bool(publishing.get("auto_publish", False)):
        raise ConfigError("auto_publish=true is not allowed before the planned v1 boundary.")

    return AppConfig(
        project=ProjectConfig(name=str(project_data.get("name", "ResearchRadar"))),
        topics=topics,
        model_providers=_model_provider_configs(
            _mapping(data.get("model_providers", {}), "model_providers")
        ),
        discovery=_discovery_config(_mapping(data.get("discovery", {}), "discovery")),
        cadence=CadenceConfig(**_mapping(data.get("cadence", {}), "cadence")),
        models=_model_config(_mapping(data.get("models", {}), "models")),
        publishing=PublishingConfig(**publishing),
        archive=_archive_publish_config(_mapping(data.get("archive", {}), "archive")),
        email=_email_publish_config(_mapping(data.get("email", {}), "email")),
        security=SecurityConfig(**_mapping(data.get("security", {}), "security")),
    )


def _archive_publish_config(data: dict[str, Any]) -> ArchivePublishConfig:
    allowed = {
        "checkout",
        "output_subdir",
        "base_url",
        "site_language",
        "remote",
        "branch",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"Unknown archive keys: {', '.join(unknown)}")
    checkout = _optional_string(data.get("checkout"), "archive.checkout")
    output_subdir = str(data.get("output_subdir", "archive")).strip()
    normalized_output = PurePosixPath(output_subdir.replace("\\", "/"))
    windows_output = PureWindowsPath(output_subdir)
    if (
        not output_subdir
        or normalized_output.is_absolute()
        or bool(windows_output.drive)
        or normalized_output == PurePosixPath(".")
        or ".." in normalized_output.parts
    ):
        raise ConfigError("archive.output_subdir must be a non-empty relative path")
    site_language = _optional_string(data.get("site_language"), "archive.site_language")
    if site_language is not None and site_language not in {"en", "zh"}:
        raise ConfigError("archive.site_language must be en or zh")
    return ArchivePublishConfig(
        checkout=Path(checkout).expanduser() if checkout else None,
        output_subdir=normalized_output.as_posix(),
        base_url=_optional_string(data.get("base_url"), "archive.base_url"),
        site_language=site_language,
        remote=str(data.get("remote", "origin")).strip() or "origin",
        branch=str(data.get("branch", "gh-pages")).strip() or "gh-pages",
    )


def _email_publish_config(data: dict[str, Any]) -> EmailPublishConfig:
    allowed = {
        "smtp_host",
        "smtp_port",
        "security",
        "username",
        "password_secret",
        "from_address",
        "to_address",
        "timeout_seconds",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"Unknown email keys: {', '.join(unknown)}")
    security = str(data.get("security", "tls")).strip().casefold()
    if security not in {"tls", "starttls"}:
        raise ConfigError("email.security must be tls or starttls")
    return EmailPublishConfig(
        smtp_host=_optional_string(data.get("smtp_host"), "email.smtp_host"),
        smtp_port=_positive_int(data.get("smtp_port", 465), "email.smtp_port"),
        security=security,
        username=_optional_string(data.get("username"), "email.username"),
        password_secret=(
            _optional_string(data.get("password_secret"), "email.password_secret")
            or "email.smtp_password"
        ),
        from_address=_optional_string(data.get("from_address"), "email.from_address"),
        to_address=_optional_string(data.get("to_address"), "email.to_address"),
        timeout_seconds=_positive_int(
            data.get("timeout_seconds", 30),
            "email.timeout_seconds",
        ),
    )


def _discovery_config(data: dict[str, Any]) -> DiscoveryConfig:
    web_search = _mapping(data.get("web_search", {}), "discovery.web_search")
    return DiscoveryConfig(
        trusted_domains=_string_list(
            data.get("trusted_domains", []),
            "discovery trusted_domains",
            allow_empty=True,
        ),
        web_search=WebSearchConfig(
            provider=_web_search_provider(
                web_search.get("provider"),
                "discovery.web_search.provider",
            ),
            endpoint=_optional_string(
                web_search.get("endpoint"),
                "discovery.web_search.endpoint",
            ),
            header_secret_name=_optional_string(
                web_search.get("header_secret_name"),
                "discovery.web_search.header_secret_name",
            ),
            max_results=_positive_int(
                web_search.get("max_results", 5),
                "discovery.web_search.max_results",
            ),
            search_depth=_web_search_depth(
                web_search.get("search_depth", "basic"),
                "discovery.web_search.search_depth",
            ),
            timeout_seconds=_positive_int(
                web_search.get("timeout_seconds", 30),
                "discovery.web_search.timeout_seconds",
            ),
        ),
    )


def _model_config(data: dict[str, Any]) -> ModelConfig:
    routes = _task_route_configs(_mapping(data.get("task_routes", {}), "models.task_routes"))
    allowed = {"scout", "analyst", "verifier", "task_routes"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"Unknown models keys: {', '.join(unknown)}")
    return ModelConfig(
        scout=str(data.get("scout", "deepseek-v4-flash")),
        analyst=str(data.get("analyst", "deepseek-v4-pro")),
        verifier=str(data.get("verifier", "codex_or_openai_high_reasoning")),
        task_routes=routes,
    )


def _model_provider_configs(data: dict[str, Any]) -> dict[str, ModelProviderConfig]:
    configs = _default_model_providers()
    for name, raw in data.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("model_providers keys must be non-empty strings.")
        item = _mapping(raw, f"model_providers.{name}")
        kind = _provider_kind(item.get("kind"), f"model_providers.{name}.kind")
        timeout_seconds = _positive_int(
            item.get("timeout_seconds", 120),
            f"model_providers.{name}.timeout_seconds",
        )
        reasoning_effort = _reasoning_effort(
            item.get("reasoning_effort", "high" if kind == "codex_cli" else None),
            f"model_providers.{name}.reasoning_effort",
        )
        if reasoning_effort is not None and kind != "codex_cli":
            raise ConfigError(
                f"model_providers.{name}.reasoning_effort is only valid for codex_cli."
            )
        configs[name.strip()] = ModelProviderConfig(
            kind=kind,
            base_url=_optional_string(item.get("base_url"), f"model_providers.{name}.base_url"),
            api_key_secret=_optional_string(
                item.get("api_key_secret"),
                f"model_providers.{name}.api_key_secret",
            ),
            command=_optional_string(item.get("command"), f"model_providers.{name}.command"),
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
        )
    return configs


def _default_model_providers() -> dict[str, ModelProviderConfig]:
    return {
        "local": ModelProviderConfig(kind="local"),
        "deepseek": ModelProviderConfig(
            kind="openai_compatible",
            base_url="https://api.deepseek.com/chat/completions",
            api_key_secret="deepseek.api_key",
        ),
        "xiaomi": ModelProviderConfig(
            kind="openai_compatible",
            base_url="https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
            api_key_secret="xiaomi.api_key",
            timeout_seconds=900,
        ),
        "openai": ModelProviderConfig(
            kind="openai_compatible",
            base_url="https://api.openai.com/v1/chat/completions",
            api_key_secret="openai.api_key",
        ),
        "anthropic": ModelProviderConfig(
            kind="anthropic_messages",
            api_key_secret="anthropic.api_key",
        ),
        "codex": ModelProviderConfig(
            kind="codex_cli",
            command="/Applications/ChatGPT.app/Contents/Resources/codex",
            timeout_seconds=900,
            reasoning_effort="high",
        ),
        "claude": ModelProviderConfig(
            kind="claude_code_cli",
            command="claude",
            timeout_seconds=900,
        ),
        "von_claude": ModelProviderConfig(
            kind="claude_code_cli",
            command="von-claude",
            timeout_seconds=900,
        ),
    }


def _task_route_configs(data: dict[str, Any]) -> dict[str, TaskRouteConfig]:
    routes: dict[str, TaskRouteConfig] = {}
    for task_name, raw in data.items():
        if not isinstance(task_name, str) or not task_name.strip():
            raise ConfigError("models.task_routes keys must be non-empty strings.")
        item = _mapping(raw, f"models.task_routes.{task_name}")
        routes[task_name.strip()] = TaskRouteConfig(
            provider=_required_string(item, "provider"),
            model=_required_string(item, "model"),
        )
    return routes


def _provider_kind(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string.")
    kind = value.strip()
    if kind not in {
        "local",
        "openai_compatible",
        "anthropic_messages",
        "codex_cli",
        "claude_code_cli",
    }:
        raise ConfigError(f"Unsupported provider kind: {kind}")
    return kind


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise ConfigError(f"{name} must be a positive integer.")
    return value


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


def _concept_groups(value: Any, name: str) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping.")
    groups: dict[str, list[str]] = {}
    for group_name, aliases in value.items():
        if not isinstance(group_name, str) or not group_name.strip():
            raise ConfigError(f"{name} keys must be non-empty strings.")
        groups[group_name.strip()] = _string_list(
            aliases,
            f"{name}.{group_name}",
            allow_empty=False,
        )
    return groups


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string or null.")
    return value.strip()


def _reasoning_effort(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() not in {"medium", "high", "xhigh"}:
        raise ConfigError(f"{name} must be medium, high, or xhigh.")
    return value.strip()


def _web_search_provider(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be generic, tavily, or null.")
    provider = value.strip()
    if provider not in {"generic", "tavily"}:
        raise ConfigError(f"{name} must be generic, tavily, or null.")
    return provider


def _web_search_depth(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a supported Tavily search depth.")
    depth = value.strip()
    if depth not in {"basic", "advanced", "fast", "ultra-fast"}:
        raise ConfigError(f"{name} must be basic, advanced, fast, or ultra-fast.")
    return depth


def _source_intent(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("source_intent must be a string.")
    if value not in {"research_brief", "implementation_scan"}:
        raise ConfigError("source_intent must be research_brief or implementation_scan.")
    return value


def _report_language(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("report_language must be a string.")
    if value not in {"en", "zh"}:
        raise ConfigError("report_language must be en or zh.")
    return value
