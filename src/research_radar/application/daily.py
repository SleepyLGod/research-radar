"""Typed orchestration for one evidence-gated daily report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from research_radar.analysis.figures import FigureExtractor
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.routing import TaskModelRoute, resolve_task_route
from research_radar.config import AppConfig
from research_radar.discovery.arxiv import ArxivConnector
from research_radar.discovery.base import DiscoveryConnector
from research_radar.discovery.github import GitHubRepoConnector
from research_radar.discovery.openalex import OpenAlexConnector
from research_radar.discovery.semantic_scholar import SemanticScholarConnector
from research_radar.discovery.web_search import (
    TAVILY_SEARCH_ENDPOINT,
    GenericWebSearchConnector,
    TavilyWebSearchConnector,
)
from research_radar.exceptions import ConfigError, ResearchRadarError, SecretError
from research_radar.pipeline.daily import run_daily
from research_radar.pipeline.progress import ProgressListener
from research_radar.security.secrets import SecretManager


@dataclass(frozen=True)
class ProviderOverrides:
    """Optional provider and model overrides for daily tasks."""

    provider: str | None = None
    model: str | None = None
    deepseek_provider: str | None = None
    gist_provider: str | None = None
    gist_model: str | None = None
    reader_provider: str | None = None
    reader_model: str | None = None
    verifier_provider: str | None = None
    verifier_model: str | None = None
    anchor_repair_provider: str | None = None
    anchor_repair_model: str | None = None
    localization_provider: str | None = None
    localization_model: str | None = None


@dataclass(frozen=True)
class DailyRunOptions:
    """Inputs that are independent from argparse and YAML presentation."""

    root: Path
    topic_id: str
    limit: int = 10
    deep_limit: int = 0
    language: str | None = None
    model_cache: bool = False
    model_cache_limit_bytes: int | None = None
    routes: ProviderOverrides = ProviderOverrides()


def run_daily_application(
    options: DailyRunOptions,
    config: AppConfig,
    secret_manager: SecretManager,
    *,
    progress_listener: ProgressListener | None = None,
    warning_listener: Callable[[str], None] | None = None,
    pipeline_runner: Callable[..., Path] = run_daily,
    figure_extractor: FigureExtractor | None = None,
) -> Path:
    """Resolve dependencies and run one daily report without CLI coupling."""

    if options.limit < 1:
        raise ResearchRadarError("limit must be at least 1.")
    if options.deep_limit < 0:
        raise ResearchRadarError("deep_limit cannot be negative.")
    if options.model_cache_limit_bytes is not None and options.model_cache_limit_bytes <= 0:
        raise ResearchRadarError("model_cache_limit_bytes must be positive when set.")

    language = options.language or config.topic(options.topic_id).report_language
    connectors = build_daily_connectors(config, secret_manager, warning_listener)
    gist = _resolve_route(config, secret_manager, "source_gist", options)
    reader = _reader_route(config, secret_manager, options)
    anchor = _optional_route(config, secret_manager, "anchor_repair", options)
    localization = _localization_route(config, secret_manager, options, language)
    verifier = _resolve_route(config, secret_manager, "verifier", options)

    gist = _cached(gist, options, "source_gist")
    reader = _cached(reader, options, "deep_reading")
    anchor = _cached(anchor, options, "anchor_repair")
    localization = _cached(localization, options, "report_localization")
    verifier = _cached(verifier, options, "verifier")

    pipeline_options: dict[str, object] = {
        "verifier": verifier.provider,
        "verifier_model": verifier.model,
        "gist_provider": gist.provider,
        "gist_model": gist.model,
        "limit": options.limit,
        "deep_reader": reader.provider,
        "deep_model": reader.model,
        "deep_limit": options.deep_limit,
        "anchor_repair_provider": anchor.provider,
        "anchor_repair_model": anchor.model,
        "localizer": localization.provider,
        "localization_model": localization.model,
        "language": options.language,
        "progress_listener": progress_listener,
    }
    if figure_extractor is not None:
        pipeline_options["figure_extractor"] = figure_extractor
    return pipeline_runner(
        options.root,
        config,
        options.topic_id,
        connectors,
        **pipeline_options,
    )


def _resolve_route(
    config: AppConfig,
    manager: SecretManager,
    task: str,
    options: DailyRunOptions,
) -> TaskModelRoute:
    provider, model = _task_override(options.routes, task)
    return resolve_task_route(
        config,
        manager,
        task,
        provider_override=provider,
        model_override=model,
        global_provider=options.routes.provider,
        global_model=options.routes.model,
        provider_replacements=_provider_replacements(options.routes),
        default_local=True,
    )


def _reader_route(
    config: AppConfig,
    manager: SecretManager,
    options: DailyRunOptions,
) -> TaskModelRoute:
    if options.deep_limit <= 0:
        return TaskModelRoute(provider=None, model=None, provider_name="local")
    return _resolve_route(config, manager, "deep_reading", options)


def _optional_route(
    config: AppConfig,
    manager: SecretManager,
    task: str,
    options: DailyRunOptions,
) -> TaskModelRoute:
    provider, _ = _task_override(options.routes, task)
    try:
        return _resolve_route(config, manager, task, options)
    except ConfigError:
        if provider or options.routes.provider:
            raise
        return TaskModelRoute(provider=None, model=None, provider_name="local")


def _localization_route(
    config: AppConfig,
    manager: SecretManager,
    options: DailyRunOptions,
    language: str,
) -> TaskModelRoute:
    if language != "zh":
        return TaskModelRoute(provider=None, model=None, provider_name="local")
    return _optional_route(config, manager, "report_localization", options)


def _task_override(routes: ProviderOverrides, task: str) -> tuple[str | None, str | None]:
    names = {
        "source_gist": (routes.gist_provider, routes.gist_model),
        "deep_reading": (routes.reader_provider, routes.reader_model),
        "verifier": (routes.verifier_provider, routes.verifier_model),
        "anchor_repair": (routes.anchor_repair_provider, routes.anchor_repair_model),
        "report_localization": (routes.localization_provider, routes.localization_model),
    }
    return names[task]


def _provider_replacements(routes: ProviderOverrides) -> dict[str, str] | None:
    if routes.deepseek_provider is None:
        return None
    return {"deepseek": routes.deepseek_provider}


def _cached(route: TaskModelRoute, options: DailyRunOptions, task: str) -> TaskModelRoute:
    if not options.model_cache or route.provider is None:
        return route
    return TaskModelRoute(
        provider=CachedLLMProvider(
            route.provider,
            cache_dir=options.root / "cache" / "model_calls",
            task_name=task,
            cache_limit_bytes=options.model_cache_limit_bytes,
        ),
        model=route.model,
        provider_name=route.provider_name,
    )


def build_daily_connectors(
    config: AppConfig,
    manager: SecretManager,
    warning_listener: Callable[[str], None] | None = None,
) -> list[DiscoveryConnector]:
    """Build the configured discovery connectors for daily-style runs."""
    connectors: list[DiscoveryConnector] = [
        ArxivConnector(),
        SemanticScholarConnector(manager),
        OpenAlexConnector(),
    ]
    web_search = _web_search_connector(config, manager, warning_listener)
    if web_search is not None:
        connectors.append(web_search)
    connectors.append(GitHubRepoConnector(manager))
    return connectors


def _web_search_connector(
    config: AppConfig,
    manager: SecretManager,
    warning_listener: Callable[[str], None] | None,
) -> DiscoveryConnector | None:
    settings = config.discovery.web_search
    provider = settings.provider or ("generic" if settings.endpoint is not None else None)
    if provider is None:
        return None
    if provider == "tavily":
        secret_name = settings.header_secret_name or "web_search.api_key"
        try:
            token = manager.get_named_secret(secret_name)
        except SecretError:
            _warn(warning_listener, "Web search disabled: missing configured Tavily API key.")
            return None
        return TavilyWebSearchConnector(
            api_key=token,
            endpoint=settings.endpoint or TAVILY_SEARCH_ENDPOINT,
            max_results=settings.max_results,
            search_depth=settings.search_depth,
            timeout_seconds=settings.timeout_seconds,
        )
    if settings.endpoint is None:
        return None
    headers: dict[str, str] = {}
    if settings.header_secret_name:
        try:
            token = manager.get_named_secret(settings.header_secret_name)
        except SecretError:
            _warn(warning_listener, "Web search disabled: missing configured header secret.")
            return None
        headers["Authorization"] = f"Bearer {token}"
    return GenericWebSearchConnector(
        settings.endpoint,
        headers=headers,
        timeout_seconds=settings.timeout_seconds,
    )


def _warn(listener: Callable[[str], None] | None, message: str) -> None:
    if listener is not None:
        listener(message)
