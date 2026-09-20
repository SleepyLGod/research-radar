import io
import json
from threading import Event
from urllib.error import HTTPError

import pytest

from research_radar.application.search_probe import probe_web_search
from research_radar.config import WebSearchConfig
from research_radar.discovery import web_search
from research_radar.exceptions import DiscoveryError, OperationCancelled
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def manager() -> SecretManager:
    backend = InMemorySecretBackend()
    backend.set_secret("search.test", "fixture-only-secret")
    return SecretManager(backend)


def settings() -> WebSearchConfig:
    return WebSearchConfig(provider="tavily", header_secret_name="search.test",
                           max_results=12, search_depth="advanced", timeout_seconds=9)


def test_search_probe_uses_one_minimal_connector_request(monkeypatch) -> None:
    calls = []

    def respond(request, *, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps({"results": [{
            "title": "Research", "url": "https://example.org/paper", "content": "Paper",
        }]}).encode())

    monkeypatch.setattr(web_search, "urlopen", respond)
    probe_web_search(settings(), manager())
    assert len(calls) == 1
    request, timeout = calls[0]
    payload = json.loads(request.data)
    assert timeout == 9
    assert payload["max_results"] == 1
    assert payload["search_depth"] == "basic"
    assert payload["include_answer"] is False
    assert payload["include_images"] is False
    assert payload["include_raw_content"] is False
    assert "fixture-only-secret" not in request.data.decode()


@pytest.mark.parametrize("payload", [{}, {"results": []}, {"error": "Invalid key"}, []])
def test_search_probe_does_not_claim_ready_without_a_usable_result(monkeypatch, payload) -> None:
    monkeypatch.setattr(
        web_search, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()),
    )
    with pytest.raises(DiscoveryError):
        probe_web_search(settings(), manager())


def test_search_probe_failure_does_not_expose_server_body_or_retry(monkeypatch) -> None:
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise HTTPError("https://api.tavily.com/search", 401, "private response", {}, None)

    monkeypatch.setattr(web_search, "urlopen", fail)
    with pytest.raises(DiscoveryError) as caught:
        probe_web_search(settings(), manager())
    assert calls == [1]
    assert "private response" not in str(caught.value)


def test_search_probe_cancel_does_not_access_secret_or_network() -> None:
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelled):
        probe_web_search(settings(), object(), cancellation_event=cancelled)


def test_search_probe_cancel_during_request_is_not_a_connection_failure(monkeypatch) -> None:
    cancelled = Event()

    def cancel(*args, **kwargs):
        cancelled.set()
        raise OSError("request interrupted")

    monkeypatch.setattr(web_search, "urlopen", cancel)
    with pytest.raises(OperationCancelled):
        probe_web_search(settings(), manager(), cancellation_event=cancelled)


def test_search_probe_does_not_contact_unknown_provider() -> None:
    with pytest.raises(DiscoveryError):
        probe_web_search(WebSearchConfig(provider="generic"), object())
