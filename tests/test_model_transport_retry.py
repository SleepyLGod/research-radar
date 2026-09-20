import io
import json
import ssl
import threading
import time
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError

import pytest

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.providers import Message
from research_radar.exceptions import ProviderTransportError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def provider(**kwargs):
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("test.key", "test-only-key")
    return transport.OpenAICompatibleProvider(
        name="test", endpoint="https://example.test/chat", api_key_secret="test.key",
        secrets=manager, timeout_seconds=10, **kwargs,
    )


def success():
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode())


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return now


@pytest.mark.parametrize("during_read", [False, True])
def test_disconnect_retries_once_with_remaining_budget(monkeypatch, clock, during_read):
    calls = []

    class TruncatedBody(io.BytesIO):
        def read(self, *args):
            raise IncompleteRead(b"")

    def request(req, *, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            clock[0] += 3
            if during_read:
                return TruncatedBody()
            raise IncompleteRead(b"")
        return success()

    monkeypatch.setattr(transport, "urlopen", request)
    response = provider().complete([Message("user", "test")], model="test")
    assert calls == [10, 6]
    assert response.metadata["attempt_count"] == 2


@pytest.mark.parametrize("error", [IncompleteRead(b""), RemoteDisconnected(),
    URLError(ConnectionResetError()), ConnectionAbortedError(), BrokenPipeError()])
def test_transient_failure_is_bounded_and_not_cached(monkeypatch, clock, tmp_path, error):
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        raise error

    monkeypatch.setattr(transport, "urlopen", request)
    cached = CachedLLMProvider(provider(), cache_dir=tmp_path, task_name="test")
    with pytest.raises(ProviderTransportError) as failure:
        cached.complete([], model="test")
    assert len(calls) == 2
    assert failure.value.diagnostics["attempt_count"] == 2
    assert failure.value.diagnostics["retryable"] is True
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("error", [TimeoutError(), ssl.SSLCertVerificationError(),
    HTTPError("https://example.test", 401, "denied", {}, None),
    HTTPError("https://example.test", 503, "unavailable", {}, None),
    URLError(OSError("unknown"))])
def test_other_errors_are_not_retried(monkeypatch, clock, error):
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        raise error

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider().complete([], model="test")
    assert len(calls) == 1
    assert failure.value.diagnostics["retryable"] is False


@pytest.mark.parametrize("body", [b"not json", b"{}"])
def test_invalid_response_is_not_retried(monkeypatch, clock, body):
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        return io.BytesIO(body)

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError):
        provider().complete([], model="test")
    assert len(calls) == 1


def test_no_retry_when_budget_exhausted(monkeypatch, clock):
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        clock[0] = 10
        raise IncompleteRead(b"")

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as failure:
        provider().complete([], model="test")
    assert len(calls) == 1
    assert failure.value.diagnostics["attempt_count"] == 1


def test_cancel_during_backoff_never_requests_again(monkeypatch, clock):
    from research_radar.exceptions import OperationCancelled

    cancelled = threading.Event()
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        raise IncompleteRead(b"")

    def wait(timeout):
        cancelled.set()
        return True

    monkeypatch.setattr(cancelled, "wait", wait)
    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(OperationCancelled):
        provider(cancellation_event=cancelled).complete([], model="test")
    assert len(calls) == 1


def test_already_cancelled_does_not_read_credentials_or_send(monkeypatch, clock):
    from research_radar.exceptions import OperationCancelled

    cancelled = threading.Event()
    cancelled.set()
    instance = provider(cancellation_event=cancelled)
    monkeypatch.setattr(SecretManager, "get_named_secret", lambda *_: pytest.fail("read secret"))
    with pytest.raises(OperationCancelled):
        instance.complete([], model="test")
