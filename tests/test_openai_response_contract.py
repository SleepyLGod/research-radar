"""Offline response validation and endpoint-isolated caching regressions."""

import io
import json
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis.cli_providers import CodexCliProvider
from research_radar.analysis.model_cache import (
    CACHE_SCHEMA_VERSION,
    CachedLLMProvider,
    model_call_cache_key,
)
from research_radar.analysis.paper_reading import model_paper_reading_with_attempts
from research_radar.analysis.providers import Message
from research_radar.analysis.routing import build_provider
from research_radar.config import parse_config
from research_radar.exceptions import ProviderTransportError
from research_radar.models import Artifact, SourceCandidate, SourceType
from research_radar.security.secrets import InMemorySecretBackend, SecretManager
from research_radar.storage.files import write_json


def make_provider(
    endpoint: str = "https://host-a.invalid/v1/chat/completions", **kwargs: object,
) -> transport.OpenAICompatibleProvider:
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("offline.key", "offline-only-key")
    return transport.OpenAICompatibleProvider(
        name="same-provider", endpoint=endpoint, api_key_secret="offline.key", secrets=manager,
        **kwargs,
    )


def test_output_budget_flows_from_config_to_payload_and_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    payloads = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        payloads.append(json.loads(req.data))
        return io.BytesIO(b'{"choices":[{"message":{"content":"valid"},"finish_reason":"stop"}]}')

    monkeypatch.setattr(transport, "urlopen", request)
    messages = [Message("user", "same input")]
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("offline.key", "offline-only-key")
    for budget, expected_hit in [(None, False), (32768, False), (32768, True), (16384, False)]:
        config = parse_config({
            "topics": [{"id": "memory", "queries": ["agent memory"]}],
            "model_providers": {"custom": {
                "kind": "openai_compatible", "base_url": "https://host-a.invalid/chat/completions",
                "api_key_secret": "offline.key", "max_tokens": budget,
            }},
        })
        provider = build_provider(config, manager, "custom")
        response = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="reader").complete(
            messages, model="same-model",
        )
        assert response.metadata["cache_hit"] is expected_hit

    assert len(payloads) == 3
    assert "max_tokens" not in payloads[0]
    assert [payload["max_tokens"] for payload in payloads[1:]] == [32768, 16384]


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "32768"])
def test_direct_provider_rejects_invalid_output_budget(budget: object) -> None:
    with pytest.raises(ValueError, match="max_tokens.*positive integer"):
        make_provider(max_tokens=budget)


def test_budget_none_preserves_existing_provider_identity() -> None:
    assert make_provider().cache_identity == make_provider(max_tokens=None).cache_identity


def test_explicit_output_budget_does_not_accept_or_cache_a_truncated_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    requests = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        requests.append(json.loads(req.data))
        return io.BytesIO(b'{"choices":[{"message":{"content":"{}"},"finish_reason":"length"}]}')

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(
        make_provider(max_tokens=32768), cache_dir=tmp_path, task_name="reader",
    )

    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([Message("user", "same input")], model="same-model")

    assert len(requests) == 1
    assert failure.value.diagnostics["response_state"] == "output_limit"
    assert failure.value.diagnostics["max_tokens"] == requests[0]["max_tokens"] == 32768
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.parametrize(
    ("content", "finish_reason", "message_extra", "state"),
    [
        (None, "stop", {}, "missing_final_answer"),
        (None, None, {"reasoning_content": "private reasoning"}, "missing_final_answer"),
        ("", "stop", {}, "missing_final_answer"),
        (" \n\t", "stop", {}, "missing_final_answer"),
        ([], "stop", {}, "invalid_message_content"),
        ({"text": "private final answer"}, "stop", {}, "invalid_message_content"),
        (42, "stop", {}, "invalid_message_content"),
        ('{"ok":true}', "length", {}, "output_limit"),
        (None, "length", {"reasoning_content": "private reasoning"}, "output_limit"),
        ("private final answer", "content_filter", {}, "content_filtered"),
        (None, "stop", {"refusal": "private refusal"}, "content_filtered"),
        (None, "tool_calls", {}, "unsupported_tool_call"),
        (None, "function_call", {}, "unsupported_tool_call"),
        ('{"ok":true}', "stop", {"tool_calls": [{"id": "offline"}]}, "unsupported_tool_call"),
        ("private final answer", "unexpected-end", {}, "invalid_finish_reason"),
        ("private final answer", [], {}, "invalid_finish_reason"),
    ],
)
def test_invalid_completion_is_not_retried_or_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    content: object, finish_reason: object, message_extra: dict[str, object], state: str,
) -> None:
    calls = []
    body = {
        "model": "server-model", "choices": [{
            "finish_reason": finish_reason,
            "message": {
                "content": content, "reasoning_content": "private reasoning", **message_extra,
            },
        }],
    }

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")

    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([Message("user", "private prompt")], model="requested-model")

    assert calls == [1]
    assert failure.value.diagnostics["response_state"] == state
    assert failure.value.diagnostics["retryable"] is False
    assert failure.value.diagnostics["attempt_count"] == 1
    diagnostic = str(failure.value) + str(failure.value.diagnostics)
    for private in (
        "private prompt", "private final answer", "private reasoning", "offline-only-key",
    ):
        assert private not in diagnostic
    assert "response_excerpt" not in failure.value.diagnostics
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(("body", "state"), [
    ([], "invalid_response_shape"),
    ({"choices": []}, "invalid_response_shape"),
    ({"choices": [{"message": {}}]}, "missing_final_answer"),
    ({"choices": [{"message": {"reasoning_content": "private reasoning"}}]},
     "missing_final_answer"),
    ({"choices": [{
        "finish_reason": "length", "message": {"reasoning_content": "private reasoning"},
    }]}, "output_limit"),
])
def test_unusable_completion_is_classified_without_response_body(
    monkeypatch: pytest.MonkeyPatch, body: object, state: str,
) -> None:
    monkeypatch.setattr(
        transport, "urlopen", lambda *_a, **_k: io.BytesIO(json.dumps(body).encode()),
    )

    with pytest.raises(ProviderTransportError) as failure:
        make_provider().complete([], model="requested-model")

    assert failure.value.diagnostics["response_state"] == state
    assert "private reasoning" not in str(failure.value)
    assert "response_excerpt" not in failure.value.diagnostics


@pytest.mark.parametrize("finish", [{}, {"finish_reason": None}, {"finish_reason": "stop"}])
def test_valid_answer_preserves_text_and_separates_requested_from_reported_model(
    monkeypatch: pytest.MonkeyPatch, finish: dict[str, object],
) -> None:
    body = {"model": "server/model-version", "choices": [{
        **finish, "message": {"content": "  answer\n", "reasoning_content": "private reasoning"},
    }]}
    monkeypatch.setattr(
        transport, "urlopen", lambda *_a, **_k: io.BytesIO(json.dumps(body).encode()),
    )

    result = make_provider().complete([], model="requested-alias")

    assert result.content == "  answer\n"
    assert result.model == "requested-alias"
    assert result.metadata["reported_model"] == "server/model-version"
    assert result.metadata["finish_reason"] == finish.get("finish_reason")
    assert "private reasoning" not in str(result)


@pytest.mark.parametrize("reported", [None, "", {}, 5, "model with spaces", "offline-only-key"])
def test_missing_or_invalid_reported_model_remains_unknown(
    monkeypatch: pytest.MonkeyPatch, reported: object,
) -> None:
    body = {"model": reported, "choices": [{"message": {"content": "answer"}}]}
    monkeypatch.setattr(
        transport, "urlopen", lambda *_a, **_k: io.BytesIO(json.dumps(body).encode()),
    )

    result = make_provider().complete([], model="requested-alias")

    assert result.model == "requested-alias"
    assert result.metadata["reported_model"] is None


@pytest.mark.parametrize("other_endpoint", [
    "https://host-b.invalid/v1/chat/completions",
    "https://host-a.invalid/v2/chat/completions",
    "https://host-a.invalid/v1/chat/completions?deployment=other",
])
def test_endpoint_change_misses_cache_and_same_endpoint_still_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, other_endpoint: str,
) -> None:
    urls = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        urls.append(req.full_url)
        body = {"choices": [{"message": {"content": f"result-{len(urls)}"}}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(transport, "urlopen", request)
    messages = [Message("user", "private prompt")]
    first = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")
    second = CachedLLMProvider(
        make_provider(other_endpoint), cache_dir=tmp_path, task_name="reader",
    )

    assert first.complete(messages, model="same-model").content == "result-1"
    assert second.complete(messages, model="same-model").content == "result-2"
    reopened = CachedLLMProvider(
        make_provider(other_endpoint), cache_dir=tmp_path, task_name="reader",
    )
    hit = reopened.complete(messages, model="same-model")

    assert hit.content == "result-2"
    assert hit.metadata["cache_hit"] is True
    assert len(urls) == 2
    for entry in tmp_path.rglob("*.json"):
        stored = entry.read_text()
        assert "https://" not in stored
        assert "private prompt" not in stored
        assert "offline-only-key" not in stored


def seed_legacy_cache(root: Path, *, name: str, identity: str, messages: list[Message]) -> Path:
    key = model_call_cache_key(
        provider_name=name, model="same-model", task_name="reader", messages=messages,
        provider_cache_identity=identity,
    )
    entry = root / "reader" / f"{key}.json"
    write_json(entry, {
        "schema_version": CACHE_SCHEMA_VERSION, "cache_key": key, "provider": name,
        "model": "same-model", "content": "legacy response",
    })
    return entry


def test_old_openai_cache_is_preserved_but_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    messages = [Message("user", "same prompt")]
    old = seed_legacy_cache(tmp_path, name="same-provider", identity="reasoning_effort=high",
                            messages=messages)
    original_bytes = old.read_bytes()
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: io.BytesIO(
        b'{"choices":[{"message":{"content":"fresh response"}}]}'
    ))
    cached = CachedLLMProvider(
        make_provider(reasoning_effort="high"), cache_dir=tmp_path, task_name="reader",
    )

    result = cached.complete(messages, model="same-model")

    assert result.content == "fresh response"
    assert result.metadata["cache_hit"] is False
    assert old.read_bytes() == original_bytes


def test_codex_legacy_cache_still_hits_without_starting_command(tmp_path: Path) -> None:
    messages = [Message("user", "same prompt")]
    seed_legacy_cache(tmp_path, name="codex", identity="reasoning_effort=xhigh", messages=messages)
    codex = CodexCliProvider(name="codex", command="must-not-run", reasoning_effort="xhigh")

    result = CachedLLMProvider(codex, cache_dir=tmp_path, task_name="reader").complete(
        messages, model="same-model",
    )

    assert result.content == "legacy response"
    assert result.metadata["cache_hit"] is True
    assert result.metadata.get("reported_model") is None
    assert result.metadata.get("finish_reason") is None


@pytest.mark.parametrize(("first_settings", "second_settings"), [
    ({}, {"thinking": "enabled"}),
    ({"reasoning_effort": "high"}, {"reasoning_effort": "xhigh"}),
])
def test_inference_settings_still_separate_cached_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    first_settings: dict[str, str], second_settings: dict[str, str],
) -> None:
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        body = {"choices": [{"message": {"content": f"result-{len(calls)}"}}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(transport, "urlopen", request)
    messages = [Message("user", "same prompt")]
    first = CachedLLMProvider(
        make_provider(**first_settings), cache_dir=tmp_path, task_name="reader",
    )
    second = CachedLLMProvider(
        make_provider(**second_settings), cache_dir=tmp_path, task_name="reader",
    )

    assert first.complete(messages, model="same-model").content == "result-1"
    assert second.complete(messages, model="same-model").content == "result-2"
    assert first.complete(messages, model="same-model").content == "result-1"
    assert calls == [1, 1]


def test_cached_answer_does_not_invent_server_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    body = {
        "model": "server/model-version",
        "choices": [{"finish_reason": "stop", "message": {"content": "answer"}}],
    }
    monkeypatch.setattr(
        transport, "urlopen", lambda *_a, **_k: io.BytesIO(json.dumps(body).encode()),
    )
    cached = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")
    first = cached.complete([], model="requested-alias")

    assert first.metadata["reported_model"] == "server/model-version"
    assert first.metadata["finish_reason"] == "stop"
    hit = cached.complete([], model="requested-alias")

    assert hit.metadata["cache_hit"] is True
    assert hit.model == "requested-alias"
    assert hit.metadata.get("reported_model") is None
    assert hit.metadata.get("finish_reason") is None


def test_endpoint_identity_does_not_expose_endpoint_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    endpoint = "https://example.invalid/chat?api_key=endpoint-only-token"
    instance = make_provider(endpoint)
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: io.BytesIO(
        b'{"choices":[{"message":{"content":"answer"}}]}'
    ))

    CachedLLMProvider(instance, cache_dir=tmp_path, task_name="reader").complete([], model="same")

    assert endpoint not in instance.cache_identity
    assert "endpoint-only-token" not in instance.cache_identity
    entry = next(tmp_path.rglob("*.json")).read_text()
    assert "endpoint-only-token" not in entry
    assert endpoint not in entry


def test_output_limit_does_not_trigger_reader_json_repair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return io.BytesIO(b'{"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}')

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")
    artifact = Artifact(
        source=SourceCandidate(
            title="Offline paper", url="https://example.invalid/paper",
            source_type=SourceType.PAPER, source_name="offline",
        ),
        text="[page 1]\nA method and its evaluation.",
    )

    with pytest.raises(ProviderTransportError) as failure:
        model_paper_reading_with_attempts(artifact, cached, model="offline-model")

    assert failure.value.diagnostics["response_state"] == "output_limit"
    assert calls == [1]
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("body", [
    b'{"choices":[{"message":{"reasoning_content":"private reasoning',
    b'private final answer offline-only-key is not JSON',
])
def test_invalid_json_does_not_persist_response_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes,
) -> None:
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return io.BytesIO(body)

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")

    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="same")

    assert failure.value.diagnostics["response_state"] == "invalid_response_json"
    assert "response_excerpt" not in failure.value.diagnostics
    assert calls == [1]
    assert not list(tmp_path.rglob("*.json"))


def test_partial_reasoning_is_not_written_to_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = b'{"choices":[{"message":{"reasoning_content":"private reasoning'

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        raise IncompleteRead(partial, expected=100)

    monkeypatch.setattr(transport, "urlopen", request)
    monkeypatch.setattr(transport.time, "sleep", lambda _: None)

    with pytest.raises(ProviderTransportError) as failure:
        make_provider().complete([], model="same")

    assert failure.value.diagnostics["partial_byte_count"] == len(partial)
    assert "response_excerpt" not in failure.value.diagnostics
    assert "private reasoning" not in str(failure.value)


@pytest.mark.parametrize(("body", "state"), [
    pytest.param(
        b'{"choices":[{"message":{"content":"private answer \xff"},"finish_reason":"stop"}]}',
        "invalid_response_encoding", id="invalid-utf8",
    ),
    pytest.param(
        b'{"choices":' + b'[' * 20_000 + b'0' + b']' * 20_000 + b'}',
        "invalid_response_json", id="deep-json",
    ),
])
def test_invalid_encoding_or_json_depth_is_not_retried_or_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes, state: str,
) -> None:
    calls = []
    response = io.BytesIO(body)

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")
    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="same")

    assert calls == [1]
    assert response.closed
    assert failure.value.diagnostics["response_state"] == state
    assert failure.value.diagnostics["retryable"] is False
    assert "response_excerpt" not in failure.value.diagnostics
    assert "private answer" not in str(failure.value)
    assert list(tmp_path.rglob("*.json")) == []


def test_nonstreaming_keeps_valid_utf8_text_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    content = "中文结果：70.4% — λ ≤ 0.5\n"
    body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: io.BytesIO(
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
    ))

    assert make_provider().complete([], model="same").content == content


def test_partial_response_without_json_envelope_is_not_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    partial = b"private model fragment without JSON envelope"
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        raise IncompleteRead(partial, expected=100)

    monkeypatch.setattr(transport, "urlopen", request)
    monkeypatch.setattr(transport.time, "sleep", lambda _: None)
    cached = CachedLLMProvider(make_provider(), cache_dir=tmp_path, task_name="reader")
    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="same")

    assert calls == [1, 1]
    assert failure.value.diagnostics["partial_byte_count"] == len(partial)
    assert failure.value.diagnostics["expected_byte_count"] == 100
    assert failure.value.diagnostics["transport_state"] == "unknown_partial"
    assert "response_excerpt" not in failure.value.diagnostics
    assert "private model fragment" not in str(failure.value)
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.parametrize("stream", [False, True])
def test_failure_diagnostics_do_not_expose_endpoint_userinfo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stream: bool,
) -> None:
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        raise URLError(OSError("offline failure"))

    monkeypatch.setattr(transport, "urlopen", request)
    instance = make_provider("https://endpoint-user:endpoint-password@example.invalid/chat",
                             stream=stream)
    cached = CachedLLMProvider(instance, cache_dir=tmp_path, task_name="reader")
    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="same")

    assert calls == [1]
    assert failure.value.diagnostics["host"] == "example.invalid"
    diagnostic = str(failure.value) + str(failure.value.diagnostics)
    assert "endpoint-user" not in diagnostic
    assert "endpoint-password" not in diagnostic
    assert list(tmp_path.rglob("*.json")) == []
