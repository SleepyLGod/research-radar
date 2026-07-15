"""Opt-in local cache for model provider calls."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from research_radar.analysis.providers import LLMProvider, Message, ModelResponse
from research_radar.storage.files import ensure_dir, read_json, write_json

CACHE_SCHEMA_VERSION = 2


class CachedLLMProvider:
    """Wrap an LLM provider with a local content-addressed response cache."""

    def __init__(self, provider: LLMProvider, *, cache_dir: Path, task_name: str) -> None:
        self._provider = provider
        self.name = provider.name
        self.cache_dir = ensure_dir(cache_dir / task_name)
        self.task_name = task_name
        self.provider_cache_identity = str(getattr(provider, "cache_identity", ""))
        self.hit_count = 0
        self.miss_count = 0

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return a cached model response or call the wrapped provider."""

        cache_key = model_call_cache_key(
            provider_name=self.name,
            model=model,
            task_name=self.task_name,
            messages=messages,
            provider_cache_identity=self.provider_cache_identity,
        )
        cache_path = self.cache_dir / f"{cache_key}.json"
        cached = _read_cached_response(cache_path, cache_key)
        if cached is not None:
            self.hit_count += 1
            return ModelResponse(
                content=str(cached["content"]),
                model=str(cached["model"]),
                metadata={
                    "provider": self.name,
                    "cache_hit": True,
                    "cache_key": cache_key,
                    "cache_task": self.task_name,
                },
            )

        self.miss_count += 1
        response = self._provider.complete(messages, model=model)
        _write_cached_response(
            cache_path,
            cache_key=cache_key,
            provider_name=self.name,
            task_name=self.task_name,
            response=response,
            messages=messages,
        )
        return ModelResponse(
            content=response.content,
            model=response.model,
            metadata={
                **response.metadata,
                "cache_hit": False,
                "cache_key": cache_key,
                "cache_task": self.task_name,
            },
        )


def model_call_cache_key(
    *,
    provider_name: str,
    model: str,
    task_name: str,
    messages: list[Message],
    provider_cache_identity: str = "",
) -> str:
    """Return a stable cache key without storing raw prompt text."""

    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "provider": provider_name,
        "model": model,
        "task_name": task_name,
        "provider_cache_identity": provider_cache_identity,
        "message_hash": _messages_hash(messages),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def provider_cache_stats(provider: LLMProvider | None) -> dict[str, int]:
    """Return cache hit/miss counters for a provider wrapper."""

    if isinstance(provider, CachedLLMProvider):
        return {"hit_count": provider.hit_count, "miss_count": provider.miss_count}
    return {"hit_count": 0, "miss_count": 0}


def provider_cache_delta(
    before: dict[str, int],
    provider: LLMProvider | None,
) -> dict[str, int]:
    """Return cache counter deltas suitable for progress metadata."""

    after = provider_cache_stats(provider)
    return {
        "cache_hit_count": max(0, after["hit_count"] - before.get("hit_count", 0)),
        "cache_miss_count": max(0, after["miss_count"] - before.get("miss_count", 0)),
    }


def merge_cache_deltas(*deltas: dict[str, int]) -> dict[str, int]:
    """Merge cache hit/miss deltas from multiple providers."""

    return {
        "cache_hit_count": sum(delta.get("cache_hit_count", 0) for delta in deltas),
        "cache_miss_count": sum(delta.get("cache_miss_count", 0) for delta in deltas),
    }


def _messages_hash(messages: list[Message]) -> str:
    payload = [{"role": message.role, "content": message.content} for message in messages]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _read_cached_response(path: Path, cache_key: str) -> dict[str, object] | None:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None
    if payload.get("cache_key") != cache_key:
        return None
    if not isinstance(payload.get("content"), str):
        return None
    if not isinstance(payload.get("model"), str):
        return None
    return payload


def _write_cached_response(
    path: Path,
    *,
    cache_key: str,
    provider_name: str,
    task_name: str,
    response: ModelResponse,
    messages: list[Message],
) -> None:
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_key": cache_key,
        "provider": provider_name,
        "model": response.model,
        "task_name": task_name,
        "message_hash": _messages_hash(messages),
        "created_at": datetime.now(UTC).isoformat(),
        "content": response.content,
    }
    try:
        write_json(path, payload)
    except OSError:
        return
