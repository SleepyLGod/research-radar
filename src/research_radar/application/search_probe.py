"""Explicit, minimal search connectivity checks without research artifacts."""

from threading import Event

from research_radar.config import TopicConfig, WebSearchConfig
from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.web_search import TAVILY_SEARCH_ENDPOINT, TavilyWebSearchConnector
from research_radar.exceptions import DiscoveryError, OperationCancelled
from research_radar.security.secrets import SecretManager


def probe_web_search(
    config: WebSearchConfig,
    secrets: SecretManager,
    *,
    cancellation_event: Event | None = None,
) -> None:
    """Request one basic Tavily result; do not save candidates or source history."""

    if cancellation_event is not None and cancellation_event.is_set():
        raise OperationCancelled()
    if config.provider != "tavily":
        raise DiscoveryError("Search connectivity check requires Tavily configuration.")
    connector = TavilyWebSearchConnector(
        api_key=secrets.get_named_secret(config.header_secret_name or "web_search.api_key"),
        endpoint=config.endpoint or TAVILY_SEARCH_ENDPOINT,
        max_results=1,
        search_depth="basic",
        timeout_seconds=config.timeout_seconds,
    )
    context = DiscoveryContext(
        topic=TopicConfig(id="connection-check", queries=["research papers"]), limit=1,
    )
    try:
        candidates = connector.discover(context)
    except DiscoveryError:
        if cancellation_event is not None and cancellation_event.is_set():
            raise OperationCancelled() from None
        raise
    if cancellation_event is not None and cancellation_event.is_set():
        raise OperationCancelled()
    if not candidates:
        raise DiscoveryError("Search check returned no usable result; connectivity is unconfirmed.")
