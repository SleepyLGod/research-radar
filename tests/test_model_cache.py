from pathlib import Path

from research_radar.analysis.model_cache import (
    CachedLLMProvider,
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
