"""Offline streaming transport, completion and cache regressions."""

import io
import json
import socket
import threading
import time
from http.client import HTTPResponse, IncompleteRead
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from test_pipeline_fake import (
    DEEP_READING_FIXTURE_TEXT,
    FakeConnector,
    _deep_reading_claim_units_json,
)

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis import openai_stream
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import model_paper_reading_with_attempts
from research_radar.analysis.providers import Message
from research_radar.analysis.routing import build_provider
from research_radar.config import parse_config
from research_radar.exceptions import ConfigError, OperationCancelled, ProviderTransportError
from research_radar.models import Artifact, SourceCandidate, SourceType
from research_radar.pipeline import daily
from research_radar.security.secrets import InMemorySecretBackend, SecretManager
from research_radar.storage.files import read_json


def secrets() -> SecretManager:
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("offline.key", "offline-only-key")
    return manager


def provider(**kwargs: object) -> transport.OpenAICompatibleProvider:
    return transport.OpenAICompatibleProvider(
        name="offline", endpoint="https://example.invalid/chat/completions",
        api_key_secret="offline.key", secrets=secrets(), **kwargs,
    )


def event(
    content: object = None, *, finish: object = None,
    extra: dict[str, object] | None = None, model: str = "reported-model",
) -> bytes:
    return frame({"model": model, "choices": [{
        "index": 0, "delta": {"content": content, **(extra or {})}, "finish_reason": finish,
    }]})


def frame(payload: object) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


DONE = b"data: [DONE]\n\n"


class Response(io.BytesIO):
    def __init__(self, parts: list[bytes | BaseException]) -> None:
        super().__init__()
        self.parts = iter(parts)

    def read1(self, size: int = -1) -> bytes:
        part = next(self.parts, b"")
        if isinstance(part, BaseException):
            raise part
        return part


@pytest.mark.parametrize("enabled", [False, True])
def test_stream_setting_reaches_request_through_shared_config_and_routing(
    monkeypatch: pytest.MonkeyPatch, enabled: bool,
) -> None:
    requests = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        requests.append(json.loads(req.data))
        return io.BytesIO(event("OK", finish="stop") + DONE if enabled else
                          b'{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}')

    monkeypatch.setattr(transport, "urlopen", request)
    config = parse_config({
        "topics": [{"id": "memory", "queries": ["agent memory"]}],
        "model_providers": {"custom": {
            "kind": "openai_compatible", "base_url": "https://example.invalid/chat/completions",
            "api_key_secret": "offline.key", "stream": enabled,
        }},
    })
    result = build_provider(config, secrets(), "custom").complete([], model="requested-model")

    assert result.content == "OK"
    assert config.model_providers["custom"].stream is enabled
    assert config.model_providers["deepseek"].stream is False
    assert requests[0].get("stream", False) is enabled
    if not enabled:
        assert "stream" not in requests[0]


@pytest.mark.parametrize("value", [None, "true", 1, 0, [], {}])
def test_stream_setting_rejects_non_boolean_values(value: object) -> None:
    with pytest.raises(ConfigError, match="stream.*boolean"):
        parse_config({
            "topics": [{"id": "memory", "queries": ["agent memory"]}],
            "model_providers": {"custom": {"kind": "openai_compatible", "stream": value}},
        })
    with pytest.raises(ValueError, match="stream.*boolean"):
        provider(stream=value)


def test_stream_setting_is_not_silently_ignored_by_other_provider_kinds() -> None:
    with pytest.raises(ConfigError, match="stream.*only valid for openai_compatible"):
        parse_config({
            "topics": [{"id": "memory", "queries": ["agent memory"]}],
            "model_providers": {"codex": {"kind": "codex_cli", "stream": True}},
        })


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_stream_reassembles_split_utf8_and_ignores_reasoning(
    monkeypatch: pytest.MonkeyPatch, newline: bytes,
) -> None:
    payload = (
        b'\xef\xbb\xbf: keepalive\n\n'
        + event(extra={"role": "assistant", "reasoning_content": "private reasoning"})
        + event("中文 ") + event("result 70.4%") + event(finish="stop")
        + frame({"choices": [], "usage": {"total_tokens": 12}}) + DONE
    ).replace(b"\n", newline)
    response = Response([payload[i:i + 1] for i in range(len(payload))])
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: response)

    result = provider(stream=True).complete([Message("user", "private prompt")], model="alias")

    assert result.content == "中文 result 70.4%"
    assert result.model == "alias"
    assert result.metadata["reported_model"] == "reported-model"
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["attempt_count"] == 1
    assert "private reasoning" not in str(result)
    assert response.closed


@pytest.mark.parametrize(
    ("body", "state"),
    [
        (event("{}", finish="stop"), "stream_missing_done"),
        (event("{}") + DONE, "stream_missing_finish"),
        (DONE, "stream_missing_finish"),
        (event("{}", finish="length") + DONE, "output_limit"),
        (event("private final", finish="content_filter") + DONE, "content_filtered"),
        (event("private final", finish="tool_calls") + DONE, "unsupported_tool_call"),
        (event("private final", finish="stop", extra={"tool_calls": [{"id": "private"}]})
         + DONE, "unsupported_tool_call"),
        (event("private final", finish="stop", extra={"refusal": "private refusal"}) + DONE,
         "content_filtered"),
        (event(finish="stop", extra={"reasoning_content": "private reasoning"}) + DONE,
         "missing_final_answer"),
        (event(" \t", finish="stop") + DONE, "missing_final_answer"),
        (event([], finish="stop") + DONE, "invalid_message_content"),
        (event("{}", finish="unexpected") + DONE, "invalid_finish_reason"),
        (b"data: private malformed JSON\n\n" + DONE, "stream_invalid_json"),
        (frame({"error": {"message": "private error offline-only-key"}}) + DONE,
         "stream_provider_error"),
        (frame({"choices": [1]}) + DONE, "stream_invalid_shape"),
        (frame({"choices": [{"index": 1, "delta": {"content": "private"}}]}) + DONE,
         "stream_invalid_shape"),
        (frame({"choices": [{"delta": []}]}) + DONE, "stream_invalid_shape"),
        (event("{}", finish="stop") + event("private after finish") + DONE,
         "stream_invalid_shape"),
        (event("{}", model="first") + event(finish="stop", model="second") + DONE,
         "stream_model_changed"),
        (b"data: \xff\n\n" + DONE, "stream_invalid_utf8"),
        (b"data: \xe4", "stream_invalid_utf8"),
        (event("{}", finish="stop") + b"data: [DONE]", "stream_missing_done"),
        (frame([]) + DONE, "stream_invalid_shape"),
        (frame({"choices": []}) + DONE, "stream_invalid_shape"),
        (frame({"choices": [{"delta": {}, "finish_reason": []}]}) + DONE,
         "stream_invalid_shape"),
        (frame({"choices": [{"index": False, "delta": {}}]}) + DONE,
         "stream_invalid_shape"),
        (frame({"choices": [{"delta": {}}, {"delta": {}}]}) + DONE,
         "stream_invalid_shape"),
        (event("{}", finish="stop") + event(finish="stop") + DONE, "stream_invalid_shape"),
        pytest.param(
            b'data: {"choices":' + b'[' * 20_000 + b'0' + b']' * 20_000 + b'}\n\n' + DONE,
            "stream_invalid_json", id="deeply-nested-json",
        ),
    ],
)
def test_incomplete_or_invalid_stream_is_not_retried_or_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes, state: str,
) -> None:
    calls = []
    response = io.BytesIO(body)

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(provider(stream=True), cache_dir=tmp_path, task_name="reader")

    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([Message("user", "private prompt")], model="alias")

    assert calls == [1]
    assert response.closed
    assert failure.value.diagnostics["response_state"] == state
    assert failure.value.diagnostics["retryable"] is False
    assert failure.value.diagnostics["stream"] is True
    assert not list(tmp_path.rglob("*.json"))
    assert "response_excerpt" not in failure.value.diagnostics
    diagnostic = str(failure.value) + str(failure.value.diagnostics)
    assert "private" not in diagnostic
    assert "offline-only-key" not in diagnostic


def test_default_identity_is_preserved_and_stream_success_is_cached_separately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    requests = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        payload = json.loads(req.data)
        requests.append(payload)
        return io.BytesIO(event(extra={"reasoning_content": "private reasoning"})
                          + event("{}", finish="stop") + DONE if payload.get("stream") else
                          b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}')

    monkeypatch.setattr(transport, "urlopen", request)
    assert provider().cache_identity == provider(stream=False).cache_identity
    assert provider().cache_identity != provider(stream=True).cache_identity
    for enabled, hit in [(False, False), (True, False), (True, True), (False, True)]:
        cached = CachedLLMProvider(provider(stream=enabled), cache_dir=tmp_path, task_name="reader")
        result = cached.complete([Message("user", "same input")], model="same-model")
        assert result.content == "{}"
        assert result.metadata["cache_hit"] is hit
    assert len(requests) == 2
    assert len(list(tmp_path.rglob("*.json"))) == 2
    assert "private reasoning" not in "".join(p.read_text() for p in tmp_path.rglob("*.json"))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return now


def test_stream_disconnect_reuses_existing_retry_and_remaining_budget(
    monkeypatch: pytest.MonkeyPatch, clock: list[float],
) -> None:
    requests = []

    def request(_req: Request, *, timeout: float) -> io.BytesIO:
        requests.append(timeout)
        if len(requests) == 1:
            clock[0] += 3
            return Response([event("discard me"), IncompleteRead(b"private reasoning")])
        return io.BytesIO(event("complete", finish="stop") + DONE)

    monkeypatch.setattr(transport, "urlopen", request)
    result = provider(stream=True, timeout_seconds=10).complete([], model="alias")
    assert requests == [10, 6]
    assert result.content == "complete"
    assert result.metadata["attempt_count"] == 2


def test_two_stream_disconnects_stop_without_partial_content_or_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clock: list[float],
) -> None:
    requests = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        requests.append(1)
        return Response([event("private final"), IncompleteRead(b"private reasoning")])

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(provider(stream=True), cache_dir=tmp_path, task_name="reader")
    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="alias")
    assert requests == [1, 1]
    assert failure.value.diagnostics["attempt_count"] == 2
    assert "private" not in str(failure.value) + str(failure.value.diagnostics)
    assert list(tmp_path.rglob("*.json")) == []


def test_stream_deadline_is_not_reset_by_chunks(
    monkeypatch: pytest.MonkeyPatch, clock: list[float],
) -> None:
    timeouts = []
    calls = []

    class SlowResponse(Response):
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append)))

        def read1(self, size: int = -1) -> bytes:
            clock[0] += 4
            return super().read1(size)

    response = SlowResponse([event("one"), event("two"), event("three", finish="stop") + DONE])

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider(stream=True, timeout_seconds=10).complete([], model="alias")
    assert calls == [1]
    assert timeouts == [10, 6, 2]
    assert failure.value.diagnostics["error_type"] == "TimeoutError"
    assert response.closed


def test_cancel_during_stream_closes_response_without_retry_or_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cancelled = threading.Event()
    calls = []

    class CancelResponse(Response):
        def read1(self, size: int = -1) -> bytes:
            cancelled.set()
            return super().read1(size)

    response = CancelResponse([event("private partial")])

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(
        provider(stream=True, cancellation_event=cancelled), cache_dir=tmp_path, task_name="reader",
    )
    with pytest.raises(OperationCancelled):
        cached.complete([], model="alias")
    assert calls == [1]
    assert response.closed
    assert list(tmp_path.rglob("*.json")) == []


def test_stream_http504_keeps_existing_no_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        raise HTTPError(req.full_url, 504, "timeout", {}, io.BytesIO(b"upstream timeout"))

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider(stream=True).complete([], model="alias")
    assert calls == [1]
    assert failure.value.diagnostics["status"] == 504
    assert failure.value.diagnostics["retryable"] is False


def test_stream_http_error_does_not_log_an_echoed_model_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        raise HTTPError(req.full_url, 502, "gateway", {},
                        io.BytesIO(b"private reasoning\nprivate final offline-only-key"))

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider(stream=True).complete([], model="alias")
    assert failure.value.diagnostics["status"] == 502
    assert "response_excerpt" not in failure.value.diagnostics
    assert "private" not in str(failure.value)


def test_stream_contract_failure_does_not_trigger_reader_json_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return io.BytesIO(event('{}', finish="length") + DONE)

    monkeypatch.setattr(transport, "urlopen", request)
    artifact = Artifact(SourceCandidate("Paper", "https://example.invalid/paper", SourceType.PAPER,
                                        "offline"), text="Saved paper text")
    with pytest.raises(ProviderTransportError):
        model_paper_reading_with_attempts(artifact, provider(stream=True), model="alias")
    assert calls == [1]


@pytest.mark.parametrize("case", ["line", "event", "answer"])
def test_stream_limits_bound_both_events_and_accumulated_answer(
    monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    monkeypatch.setattr(openai_stream, "_MAX_STREAM_CHARS", 1024)
    bodies = {
        "line": [b"data: " + b"x" * 1025],
        "event": [b"data: " + b"x" * 600 + b"\n", b"data: " + b"y" * 600 + b"\n\n"],
        "answer": [event("x" * 600), event("y" * 600), event(finish="stop"), DONE],
    }
    response = Response(bodies[case])
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider(stream=True).complete([], model="alias")
    assert calls == [1]
    assert response.closed
    assert failure.value.diagnostics["response_state"] == "stream_size_limit"


def test_sse_multiline_data_comments_and_missing_server_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        b': keepalive\n\nevent: message\nid: ignored\n'
        b'data: {"choices": [\n'
        b'data: {"delta": {"content": "OK"}, "finish_reason": "stop"}]}\n\n' + DONE
    )
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: io.BytesIO(body))

    result = provider(stream=True).complete([], model="requested-alias")

    assert result.content == "OK"
    assert result.model == "requested-alias"
    assert result.metadata["reported_model"] is None


def test_stream_cancel_before_request_does_not_even_read_test_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = threading.Event()
    cancelled.set()
    instance = provider(stream=True, cancellation_event=cancelled)
    monkeypatch.setattr(SecretManager, "get_named_secret", lambda *_: pytest.fail("secret read"))
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: pytest.fail("request sent"))

    with pytest.raises(OperationCancelled):
        instance.complete([], model="alias")


def test_stream_cancel_during_existing_backoff_does_not_send_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = threading.Event()
    calls = []

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return Response([IncompleteRead(b"private partial")])

    monkeypatch.setattr(transport, "urlopen", request)
    monkeypatch.setattr(cancelled, "wait", lambda _timeout: cancelled.set())
    with pytest.raises(OperationCancelled):
        provider(stream=True, cancellation_event=cancelled).complete([], model="alias")
    assert calls == [1]


def test_header_wait_consumes_stream_time_budget(
    monkeypatch: pytest.MonkeyPatch, clock: list[float],
) -> None:
    response = Response([event("too late", finish="stop") + DONE])

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        clock[0] = 10
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider(stream=True, timeout_seconds=10).complete([], model="alias")
    assert failure.value.diagnostics["error_type"] == "TimeoutError"
    assert next(response.parts).startswith(b"data:")
    assert response.closed


def test_decoding_time_also_consumes_the_original_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clock: list[float],
) -> None:
    real_loads = json.loads
    calls = []

    def decode(raw: str | bytes, *args: object, **kwargs: object) -> object:
        value = real_loads(raw, *args, **kwargs)
        if isinstance(value, dict) and value.get("model") == "reported-model":
            clock[0] = 10
        return value

    def request(*_args: object, **_kwargs: object) -> io.BytesIO:
        calls.append(1)
        return io.BytesIO(event("complete", finish="stop") + DONE)

    monkeypatch.setattr(json, "loads", decode)
    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(provider(stream=True, timeout_seconds=10),
                               cache_dir=tmp_path, task_name="reader")
    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="alias")
    assert calls == [1]
    assert failure.value.diagnostics["error_type"] == "TimeoutError"
    assert list(tmp_path.rglob("*.json")) == []


def test_real_http_response_decodes_chunked_sse_with_remaining_socket_timeout(
    monkeypatch: pytest.MonkeyPatch, clock: list[float],
) -> None:
    body = event("中文 result") + event(finish="stop") + DONE
    wire = io.BytesIO(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        + f"{len(body):X}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    )
    timeouts = []

    class WireSocket:
        def makefile(self, _mode: str) -> io.BufferedReader:
            return io.BufferedReader(socket.SocketIO(self, "rb"))

        def recv_into(self, buffer: bytearray) -> int:
            clock[0] += 0.01
            return wire.readinto(memoryview(buffer)[:17])

        def settimeout(self, timeout: float) -> None:
            timeouts.append(timeout)

        def _decref_socketios(self) -> None:
            pass

    response = HTTPResponse(WireSocket())

    def request(*_args: object, **_kwargs: object) -> HTTPResponse:
        response.begin()
        return response

    monkeypatch.setattr(transport, "urlopen", request)
    result = provider(stream=True, timeout_seconds=10).complete([], model="alias")

    assert result.content == "中文 result"
    assert len(timeouts) > 1
    assert 0 < timeouts[-1] < timeouts[0] < 10
    assert response.isclosed()


@pytest.mark.parametrize("enabled", [False, True])
def test_reader_and_verifier_transport_reach_existing_daily_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: bool,
) -> None:
    payloads = []
    answers = {
        "offline-reader": _deep_reading_claim_units_json(),
        "offline-verifier": '{"decisions":[{"claim_index":1,"status":"supported"}]}',
    }

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        payload = json.loads(req.data)
        payloads.append(payload)
        answer = answers[payload["model"]]
        if enabled:
            return io.BytesIO(event(extra={"reasoning_content": "private reasoning"})
                              + event(answer[:100]) + event(answer[100:], finish="stop") + DONE)
        return io.BytesIO(json.dumps({"choices": [{
            "message": {"content": answer}, "finish_reason": "stop",
        }]}).encode())

    monkeypatch.setattr(transport, "urlopen", request)
    monkeypatch.setattr(daily, "ingest_source", lambda source, _: Artifact(
        source=source, text=DEEP_READING_FIXTURE_TEXT,
    ))
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    reader = CachedLLMProvider(provider(stream=enabled), cache_dir=tmp_path / "cache",
                               task_name="reader")
    verifier = CachedLLMProvider(provider(stream=enabled), cache_dir=tmp_path / "cache",
                                 task_name="verifier")

    run = daily.run_daily(tmp_path, config, "memory", [FakeConnector()],
        deep_reader=reader, deep_model="offline-reader", deep_limit=1,
        verifier=verifier, verifier_model="offline-verifier", figure_extractor=lambda *_a, **_k: [])

    draft = read_json(run / "article_draft.json")
    assert draft["metadata"]["research_outcome"]["status"] == "ready"
    assert draft["metadata"]["deep_read_count"] == 1
    assert draft["claims"][0]["status"] == "supported"
    assert "Memory benchmarks reward unsupported answers." in (run / "daily.md").read_text()
    assert [p["model"] for p in payloads] == ["offline-reader", "offline-verifier"]
    assert all(p.get("stream", False) is enabled for p in payloads)
    assert all("private reasoning" not in path.read_text() for path in tmp_path.rglob("*.json"))
