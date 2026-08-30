"""Strict conversion from App-owned JSON into the existing research configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_radar.config import AppConfig, parse_config
from research_radar.exceptions import ConfigError

_ROOT_FIELDS = {
    "schema_version",
    "project_name",
    "ui_language",
    "workspace_root",
    "providers",
    "routes",
    "topics",
    "discovery",
    "delivery",
    "storage",
    "start_at_login",
}
_PROVIDER_FIELDS = {
    "id",
    "kind",
    "base_url",
    "api_key_secret",
    "command_path",
    "timeout_seconds",
    "thinking",
    "reasoning_effort",
}
_ROUTE_FIELDS = {"task", "provider_id", "model"}
_DISCOVERY_FIELDS = {
    "trusted_domains",
    "web_search_provider",
    "web_search_secret",
    "web_search_endpoint",
    "web_search_max_results",
    "web_search_depth",
    "web_search_timeout_seconds",
}
_DELIVERY_FIELDS = {"wechat", "email"}
_WECHAT_FIELDS = {
    "enabled",
    "author",
    "thumb_media_id",
    "app_id_secret",
    "app_secret_secret",
}
_EMAIL_FIELDS = {
    "enabled",
    "smtp_host",
    "smtp_port",
    "security",
    "username",
    "password_secret",
    "from_address",
    "to_address",
    "timeout_seconds",
}
_STORAGE_FIELDS = {"model_cache_limit_bytes"}
_FORBIDDEN_SECRET_FIELDS = {
    "api_key",
    "password",
    "secret_value",
    "token",
    "api_key_value",
    "token_value",
    "authorization",
    "cookie",
}


class AppConfigurationError(ConfigError):
    """Raised when App-owned configuration violates its versioned contract."""


@dataclass(frozen=True, slots=True)
class AppWeChatConfigV1:
    """App-only WeChat delivery settings."""

    enabled: bool
    author: str
    thumb_media_id: str
    app_id_secret: str
    app_secret_secret: str


@dataclass(frozen=True, slots=True)
class LoadedAppConfigurationV1:
    """Validated App settings plus the existing research configuration."""

    research: AppConfig
    wechat: AppWeChatConfigV1
    email_enabled: bool
    workspace_root: Path
    model_cache_limit_bytes: int | None


def load_app_configuration(
    path: Path,
    *,
    require_topics: bool = True,
) -> LoadedAppConfigurationV1:
    """Load one strict App JSON file and convert it to the existing AppConfig."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppConfigurationError("App configuration could not be read.") from exc
    root = _mapping(value, "App configuration")
    _reject_secret_values(root)
    _exact_keys(root, _ROOT_FIELDS, "App configuration")
    if _integer(root.get("schema_version"), "schema_version") != 1:
        raise AppConfigurationError("Unsupported App configuration schema version.")
    if root.get("ui_language") not in {"system", "zh-Hans", "en"}:
        raise AppConfigurationError("ui_language must be system, zh-Hans, or en.")
    _boolean(root.get("start_at_login"), "start_at_login")

    app_support_root = path.resolve(strict=True).parent.parent
    workspace_root = _contained_absolute_path(
        root.get("workspace_root"), app_support_root, "workspace_root"
    )
    providers = _providers(root.get("providers"))
    routes = _routes(root.get("routes"), set(providers))
    topics = _list(root.get("topics"), "topics")
    discovery = _discovery(root.get("discovery"))
    delivery = _mapping(root.get("delivery"), "delivery")
    _exact_keys(delivery, _DELIVERY_FIELDS, "delivery")
    wechat = _wechat(delivery.get("wechat"))
    email_enabled, email = _email(delivery.get("email"))
    storage = _mapping(root.get("storage"), "storage")
    _exact_keys(storage, _STORAGE_FIELDS, "storage")
    cache_limit = storage.get("model_cache_limit_bytes")
    if cache_limit is not None:
        cache_limit = _positive_integer(cache_limit, "storage.model_cache_limit_bytes")

    research_data = {
        "project": {"name": _string(root.get("project_name"), "project_name")},
        "topics": topics,
        "model_providers": providers,
        "models": {"task_routes": routes},
        "discovery": discovery,
        "email": email,
        "security": {"secret_backend": "keychain"},
    }
    try:
        research = parse_config(research_data, require_topics=require_topics)
    except ConfigError as exc:
        raise AppConfigurationError(str(exc)) from exc
    return LoadedAppConfigurationV1(
        research=research,
        wechat=wechat,
        email_enabled=email_enabled,
        workspace_root=workspace_root,
        model_cache_limit_bytes=cache_limit,
    )


def _providers(value: Any) -> dict[str, dict[str, object]]:
    items = _list(value, "providers")
    result: dict[str, dict[str, object]] = {}
    for index, item in enumerate(items):
        provider = _mapping(item, f"providers[{index}]")
        _exact_keys(provider, _PROVIDER_FIELDS, f"providers[{index}]")
        provider_id = _string(provider.get("id"), f"providers[{index}].id")
        if provider_id in result:
            raise AppConfigurationError(f"Duplicate provider id: {provider_id}")
        result[provider_id] = {
            "kind": _string(provider.get("kind"), f"provider {provider_id} kind"),
            "base_url": provider.get("base_url"),
            "api_key_secret": provider.get("api_key_secret"),
            "command": provider.get("command_path"),
            "timeout_seconds": _positive_integer(
                provider.get("timeout_seconds"), f"provider {provider_id} timeout_seconds"
            ),
            "thinking": provider.get("thinking"),
            "reasoning_effort": provider.get("reasoning_effort"),
        }
    return result


def _routes(value: Any, providers: set[str]) -> dict[str, dict[str, str]]:
    items = _list(value, "routes")
    routes: dict[str, dict[str, str]] = {}
    for index, item in enumerate(items):
        route = _mapping(item, f"routes[{index}]")
        _exact_keys(route, _ROUTE_FIELDS, f"routes[{index}]")
        task = _string(route.get("task"), f"routes[{index}].task")
        provider_id = _string(route.get("provider_id"), f"routes[{index}].provider_id")
        if provider_id not in providers:
            raise AppConfigurationError(f"Unknown route provider: {provider_id}")
        if task in routes:
            raise AppConfigurationError(f"Duplicate task route: {task}")
        routes[task] = {
            "provider": provider_id,
            "model": _string(route.get("model"), f"routes[{index}].model"),
        }
    return routes


def _discovery(value: Any) -> dict[str, object]:
    discovery = _mapping(value, "discovery")
    _exact_keys(discovery, _DISCOVERY_FIELDS, "discovery")
    return {
        "trusted_domains": discovery.get("trusted_domains"),
        "web_search": {
            "provider": discovery.get("web_search_provider"),
            "header_secret_name": discovery.get("web_search_secret"),
            "endpoint": discovery.get("web_search_endpoint"),
            "max_results": discovery.get("web_search_max_results"),
            "search_depth": discovery.get("web_search_depth"),
            "timeout_seconds": discovery.get("web_search_timeout_seconds"),
        },
    }


def _wechat(value: Any) -> AppWeChatConfigV1:
    settings = _mapping(value, "delivery.wechat")
    _exact_keys(settings, _WECHAT_FIELDS, "delivery.wechat")
    return AppWeChatConfigV1(
        enabled=_boolean(settings.get("enabled"), "delivery.wechat.enabled"),
        author=_optional_string(settings.get("author"), "delivery.wechat.author") or "",
        thumb_media_id=(
            _optional_string(settings.get("thumb_media_id"), "delivery.wechat.thumb_media_id")
            or ""
        ),
        app_id_secret=_string(
            settings.get("app_id_secret"), "delivery.wechat.app_id_secret"
        ),
        app_secret_secret=_string(
            settings.get("app_secret_secret"), "delivery.wechat.app_secret_secret"
        ),
    )


def _email(value: Any) -> tuple[bool, dict[str, object]]:
    settings = _mapping(value, "delivery.email")
    _exact_keys(settings, _EMAIL_FIELDS, "delivery.email")
    enabled = _boolean(settings.get("enabled"), "delivery.email.enabled")
    optional_fields = {"smtp_host", "username", "from_address", "to_address"}
    converted = {
        key: (_optional_string(item, f"delivery.email.{key}") if key in optional_fields else item)
        for key, item in settings.items()
        if key != "enabled"
    }
    return enabled, converted


def _contained_absolute_path(value: Any, root: Path, label: str) -> Path:
    raw = _string(value, label)
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise AppConfigurationError(f"{label} must be an absolute path.")
    resolved = candidate.resolve(strict=False)
    if resolved == root:
        raise AppConfigurationError(f"{label} must be inside App Support.")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AppConfigurationError(f"{label} must stay within App Support.") from exc
    return resolved


def _reject_secret_values(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _FORBIDDEN_SECRET_FIELDS:
                raise AppConfigurationError("Secret values are not allowed in App configuration.")
            _reject_secret_values(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_values(item)


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        unknown = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        detail = f"unknown {unknown[0]}" if unknown else f"missing {missing[0]}"
        raise AppConfigurationError(f"{label} has {detail}.")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppConfigurationError(f"{label} must be an object.")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise AppConfigurationError(f"{label} must be an array.")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppConfigurationError(f"{label} must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AppConfigurationError(f"{label} must be a string or null.")
    return value.strip() or None


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppConfigurationError(f"{label} must be an integer.")
    return value


def _positive_integer(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result <= 0:
        raise AppConfigurationError(f"{label} must be positive.")
    return result


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise AppConfigurationError(f"{label} must be a boolean.")
    return value
