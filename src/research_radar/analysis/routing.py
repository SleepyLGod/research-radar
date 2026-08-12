"""Task-to-model provider routing."""

from __future__ import annotations

from dataclasses import dataclass

from research_radar.analysis.anthropic import AnthropicMessagesProvider
from research_radar.analysis.cli_providers import ClaudeCodeCliProvider, CodexCliProvider
from research_radar.analysis.openai_compatible import OpenAICompatibleProvider
from research_radar.analysis.providers import LLMProvider, StaticProvider
from research_radar.config import AppConfig, ModelProviderConfig
from research_radar.exceptions import ConfigError
from research_radar.security.secrets import SecretManager


@dataclass(frozen=True)
class TaskModelRoute:
    """Resolved provider and model for one task."""

    provider: LLMProvider | None
    model: str | None
    provider_name: str


@dataclass(frozen=True)
class TaskRoutePreview:
    """Resolved provider and model names without building the provider."""

    provider_name: str
    model: str | None


def resolve_task_route(
    config: AppConfig,
    secrets: SecretManager,
    task_name: str,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
    global_provider: str | None = None,
    global_model: str | None = None,
    provider_replacements: dict[str, str] | None = None,
    default_local: bool = False,
) -> TaskModelRoute:
    """Resolve the provider and model for one task."""

    preview = resolve_task_route_preview(
        config,
        task_name,
        provider_override=provider_override,
        model_override=model_override,
        global_provider=global_provider,
        global_model=global_model,
        provider_replacements=provider_replacements,
        default_local=default_local,
    )
    if preview.provider_name == "local":
        return TaskModelRoute(provider=None, model=None, provider_name=preview.provider_name)
    if preview.model is None:
        raise ConfigError(
            f"No model configured for task {task_name} provider {preview.provider_name}."
        )
    provider = build_provider(config, secrets, preview.provider_name)
    return TaskModelRoute(
        provider=provider,
        model=preview.model,
        provider_name=preview.provider_name,
    )


def resolve_task_route_preview(
    config: AppConfig,
    task_name: str,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
    global_provider: str | None = None,
    global_model: str | None = None,
    provider_replacements: dict[str, str] | None = None,
    default_local: bool = False,
) -> TaskRoutePreview:
    """Resolve provider and model names without instantiating the provider."""

    route = config.models.task_routes.get(task_name)
    if provider_override:
        provider_name = provider_override
        model = model_override or _task_model_for_provider(route, provider_name)
    elif global_provider:
        provider_name = global_provider
        model = (
            model_override
            or global_model
            or _task_model_for_provider(route, provider_name)
        )
    elif route:
        provider_name = _replacement_provider(route.provider, provider_replacements)
        model = model_override or _task_model_for_provider(route, provider_name)
    elif default_local:
        provider_name = "local"
        model = model_override or global_model or "local"
    else:
        raise ConfigError(f"No model route configured for task: {task_name}")

    if provider_name == "local":
        return TaskRoutePreview(provider_name=provider_name, model=None)
    if provider_name not in config.model_providers:
        raise ConfigError(f"Unknown model provider: {provider_name}")
    if model is None:
        raise ConfigError(f"No model configured for task {task_name} provider {provider_name}.")
    return TaskRoutePreview(provider_name=provider_name, model=model)


def _replacement_provider(
    provider_name: str,
    replacements: dict[str, str] | None,
) -> str:
    if replacements is None:
        return provider_name
    return replacements.get(provider_name, provider_name)


def _task_model_for_provider(
    route: object | None,
    provider_name: str,
) -> str | None:
    if route is not None and getattr(route, "provider", None) == provider_name:
        return getattr(route, "model", None)
    return _default_model(provider_name)


def build_provider(
    config: AppConfig,
    secrets: SecretManager,
    provider_name: str,
) -> LLMProvider:
    """Build one configured provider instance."""

    try:
        provider_config = config.model_providers[provider_name]
    except KeyError as exc:
        raise ConfigError(f"Unknown model provider: {provider_name}") from exc

    provider = _build_provider(provider_name, provider_config, secrets)
    health_check = getattr(provider, "health_check", None)
    if callable(health_check):
        health_check()
    return provider


def _build_provider(
    provider_name: str,
    provider_config: ModelProviderConfig,
    secrets: SecretManager,
) -> LLMProvider:
    if provider_config.kind == "local":
        return StaticProvider()
    if provider_config.kind == "openai_compatible":
        if provider_config.base_url is None:
            raise ConfigError(f"model provider {provider_name} requires base_url.")
        if provider_config.api_key_secret is None:
            raise ConfigError(f"model provider {provider_name} requires api_key_secret.")
        return OpenAICompatibleProvider(
            name=provider_name,
            endpoint=provider_config.base_url,
            api_key_secret=provider_config.api_key_secret,
            secrets=secrets,
            timeout_seconds=provider_config.timeout_seconds,
            thinking=provider_config.thinking,
            reasoning_effort=provider_config.reasoning_effort,
        )
    if provider_config.kind == "anthropic_messages":
        if provider_config.api_key_secret is None:
            raise ConfigError(f"model provider {provider_name} requires api_key_secret.")
        return AnthropicMessagesProvider(
            name=provider_name,
            api_key_secret=provider_config.api_key_secret,
            secrets=secrets,
            timeout_seconds=provider_config.timeout_seconds,
        )
    if provider_config.kind == "codex_cli":
        if provider_config.command is None:
            raise ConfigError(f"model provider {provider_name} requires command.")
        return CodexCliProvider(
            name=provider_name,
            command=provider_config.command,
            timeout_seconds=provider_config.timeout_seconds,
            reasoning_effort=provider_config.reasoning_effort,
        )
    if provider_config.kind == "claude_code_cli":
        if provider_config.command is None:
            raise ConfigError(f"model provider {provider_name} requires command.")
        return ClaudeCodeCliProvider(
            name=provider_name,
            command=provider_config.command,
            timeout_seconds=provider_config.timeout_seconds,
        )
    raise ConfigError(f"Unsupported provider kind: {provider_config.kind}")


def _default_model(provider_name: str) -> str | None:
    defaults = {
        "deepseek": "deepseek-v4-flash",
        "xiaomi": "mimo-v2.5-pro",
        "openai": "gpt-5.4",
        "anthropic": "claude-sonnet-4-5",
        "codex": "gpt-5.6-terra",
        "claude": "sonnet",
        "von_claude": "sonnet",
        "local": "local",
    }
    return defaults.get(provider_name)
