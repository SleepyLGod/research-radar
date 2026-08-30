import os
from pathlib import Path

import pytest

from research_radar.analysis.model_cache import (
    CachedLLMProvider,
    enforce_model_cache_limit,
    model_call_cache_key,
    provider_cache_delta,
    provider_cache_stats,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.storage.files import read_json


class CountingProvider:
    name = "counting"

    def __init__(self, content: str = "cached response") -> None:
        self.content = content
        self.call_count = 0

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(
            content=self.content,
            model=model,
            metadata={"provider": self.name},
        )


class VariantProvider(CountingProvider):
    def __init__(self, cache_identity: str) -> None:
        super().__init__()
        self.cache_identity = cache_identity


def test_model_cache_key_changes_by_task_model_provider_and_messages() -> None:
    messages = [Message(role="user", content="private prompt")]
    base = model_call_cache_key(
        provider_name="deepseek",
        model="reader",
        task_name="deep_reading",
        messages=messages,
    )

    assert base != model_call_cache_key(
        provider_name="openai",
        model="reader",
        task_name="deep_reading",
        messages=messages,
    )
    assert base != model_call_cache_key(
        provider_name="deepseek",
        model="verifier",
        task_name="deep_reading",
        messages=messages,
    )
    assert base != model_call_cache_key(
        provider_name="deepseek",
        model="reader",
        task_name="verifier",
        messages=messages,
    )
    assert base != model_call_cache_key(
        provider_name="deepseek",
        model="reader",
        task_name="deep_reading",
        messages=[Message(role="user", content="different prompt")],
    )


def test_cached_provider_returns_cached_response_without_prompt_storage(tmp_path: Path) -> None:
    provider = CountingProvider()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="deep_reading")
    messages = [Message(role="user", content="secret prompt text")]

    first = cached.complete(messages, model="deepseek-v4-pro")
    second = cached.complete(messages, model="deepseek-v4-pro")

    assert first.content == "cached response"
    assert second.content == "cached response"
    assert second.metadata["cache_hit"] is True
    assert provider.call_count == 1
    assert cached.hit_count == 1
    assert cached.miss_count == 1

    cache_files = list((tmp_path / "deep_reading").glob("*.json"))
    assert len(cache_files) == 1
    payload = read_json(cache_files[0])
    rendered = str(payload)
    assert "secret prompt text" not in rendered
    assert payload["content"] == "cached response"


def test_model_cache_key_changes_with_provider_cache_identity(tmp_path: Path) -> None:
    messages = [Message(role="user", content="same prompt")]
    high = CachedLLMProvider(
        VariantProvider("reasoning_effort=high"),
        cache_dir=tmp_path,
        task_name="verifier",
    )
    xhigh = CachedLLMProvider(
        VariantProvider("reasoning_effort=xhigh"),
        cache_dir=tmp_path,
        task_name="verifier",
    )
    thinking = CachedLLMProvider(
        VariantProvider("thinking=enabled;reasoning_effort=high"),
        cache_dir=tmp_path,
        task_name="verifier",
    )

    high_response = high.complete(messages, model="gpt-5.6-terra")
    xhigh_response = xhigh.complete(messages, model="gpt-5.6-terra")
    thinking_response = thinking.complete(messages, model="gpt-5.6-terra")

    assert high_response.metadata["cache_key"] != xhigh_response.metadata["cache_key"]
    assert high_response.metadata["cache_key"] != thinking_response.metadata["cache_key"]


def test_cache_stats_helpers_treat_none_as_no_cache() -> None:
    before = provider_cache_stats(None)

    assert before == {"hit_count": 0, "miss_count": 0}
    assert provider_cache_delta(before, None) == {
        "cache_hit_count": 0,
        "cache_miss_count": 0,
    }


def test_unbounded_cache_hit_does_not_change_entry_timestamp(tmp_path: Path) -> None:
    messages = [Message(role="user", content="same prompt")]
    cached = CachedLLMProvider(CountingProvider(), cache_dir=tmp_path, task_name="reader")
    cached.complete(messages, model="model")
    entry = next((tmp_path / "reader").glob("*.json"))
    os.utime(entry, (10, 10))

    cached.complete(messages, model="model")

    assert entry.stat().st_mtime == 10


def test_bounded_cache_hit_updates_only_cache_entry_timestamp(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    report = tmp_path / "runs" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text("report", encoding="utf-8")
    messages = [Message(role="user", content="same prompt")]
    cached = CachedLLMProvider(
        CountingProvider(),
        cache_dir=cache_root,
        task_name="reader",
        cache_limit_bytes=10_000,
    )
    cached.complete(messages, model="model")
    entry = next((cache_root / "reader").glob("*.json"))
    os.utime(entry, (10, 10))
    os.utime(report, (20, 20))

    cached.complete(messages, model="model")

    assert entry.stat().st_mtime > 10
    assert report.stat().st_mtime == 20
    assert report.read_text(encoding="utf-8") == "report"


def test_bounded_cache_hit_does_not_rescan_cache_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages = [Message(role="user", content="same prompt")]
    cached = CachedLLMProvider(
        CountingProvider(),
        cache_dir=tmp_path,
        task_name="reader",
        cache_limit_bytes=10_000,
    )
    cached.complete(messages, model="model")

    monkeypatch.setattr(
        "research_radar.analysis.model_cache.enforce_model_cache_limit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cache hit must not rescan the cache root")
        ),
    )

    response = cached.complete(messages, model="model")

    assert response.metadata["cache_hit"] is True


def test_cache_limit_removes_oldest_contained_entries_only(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache" / "model_calls"
    first = cache_root / "reader" / "first.json"
    second = cache_root / "verifier" / "second.json"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"a" * 20)
    second.write_bytes(b"b" * 20)
    os.utime(first, (10, 10))
    os.utime(second, (20, 20))
    outside = tmp_path / "runs" / "article_draft.json"
    outside.parent.mkdir(parents=True)
    outside.write_text("keep", encoding="utf-8")

    retired = tmp_path / "retired"
    retired.mkdir()
    removed = enforce_model_cache_limit(
        cache_root,
        20,
        retire=lambda path: path.rename(retired / path.name),
    )

    assert removed == [first]
    assert not first.exists()
    assert second.exists()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_cache_limit_does_not_follow_symlinks(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    (cache_root / "linked.json").symlink_to(outside)

    removed = enforce_model_cache_limit(
        cache_root,
        1,
        retire=lambda path: path.rename(tmp_path / f"retired-{path.name}"),
    )

    assert removed == []
    assert outside.read_text(encoding="utf-8") == "keep"


def test_cache_maintenance_failure_does_not_fail_model_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_maintenance(cache_root: Path, limit_bytes: int) -> list[Path]:
        raise OSError("Trash unavailable")

    monkeypatch.setattr(
        "research_radar.analysis.model_cache.enforce_model_cache_limit",
        fail_maintenance,
    )
    cached = CachedLLMProvider(
        CountingProvider(),
        cache_dir=tmp_path,
        task_name="reader",
        cache_limit_bytes=10,
    )

    response = cached.complete([Message(role="user", content="prompt")], model="model")

    assert response.content == "cached response"
    assert cached.maintenance_error == "Trash unavailable"


def test_cache_hit_timestamp_failure_does_not_fail_model_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    messages = [Message(role="user", content="same prompt")]
    cached = CachedLLMProvider(
        CountingProvider(),
        cache_dir=tmp_path,
        task_name="reader",
        cache_limit_bytes=10_000,
    )
    cached.complete(messages, model="model")

    def fail_timestamp(*args, **kwargs) -> None:
        raise OSError("read-only cache")

    monkeypatch.setattr("research_radar.analysis.model_cache.os.utime", fail_timestamp)

    response = cached.complete(messages, model="model")

    assert response.content == "cached response"
    assert response.metadata["cache_hit"] is True
    assert cached.maintenance_error == "read-only cache"
