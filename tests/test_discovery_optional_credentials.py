"""Offline regression coverage for optional credentials and discovery diagnostics."""

import io
import json
from types import ModuleType
from typing import Any
from urllib.error import HTTPError

import keyring
import pytest
from keyring.errors import KeyringLocked

from research_radar import exceptions
from research_radar.analysis.providers import StaticProvider
from research_radar.config import TopicConfig
from research_radar.discovery import arxiv, github, semantic_scholar
from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.orchestrator import DiscoveryOrchestrator
from research_radar.evaluation.topic_smoke import DEFAULT_TOPIC_SMOKE_SPECS
from research_radar.security.secrets import KeychainSecretBackend, SecretManager
from research_radar.topic_bootstrap import bootstrap_topic_draft

CONNECTORS = [
    (arxiv, arxiv.ArxivConnector, b'<feed xmlns="http://www.w3.org/2005/Atom"/>'),
    (github, github.GitHubRepoConnector, b'{"items": []}'),
    (semantic_scholar, semantic_scholar.SemanticScholarConnector, b'{"data": []}'),
]


@pytest.mark.parametrize("module,connector_type,payload", CONNECTORS)
def test_empty_success_is_not_total_failure(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, connector_type: Any, payload: bytes,
) -> None:
    calls = []

    def open_response(*args: Any, **kwargs: Any) -> io.BytesIO:
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError("https://secret.invalid/token", 429, "private-body", {}, None)
        return io.BytesIO(payload)

    monkeypatch.setattr(module, "urlopen", open_response)
    connector = connector_type()
    result = DiscoveryOrchestrator([connector]).discover(
        TopicConfig(id="test", queries=["private-query", "second"]), limit=1,
    )
    assert result.candidates == []
    assert not any(f.metadata["kind"] == "discovery_failed" for f in result.findings)
    diagnostics = result.connector_diagnostics[connector.name]
    expected_count = 2 if module is github else 10
    assert diagnostics["successful_query_count"] == expected_count - 1
    assert diagnostics["failed_query_count"] == 1
    assert diagnostics["queries"][0]["http_status"] == 429
    assert diagnostics["queries"][0]["error_type"] == "HTTPError"
    assert "private" not in json.dumps(diagnostics)
    assert "secret.invalid" not in json.dumps(diagnostics)
    assert len(calls) == expected_count


@pytest.mark.parametrize("module,connector_type,payload", CONNECTORS[1:])
@pytest.mark.parametrize("outcome", ["missing", "denied", "success"])
def test_optional_resolution_once_per_connector_and_new_connector_fresh(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, connector_type: Any,
    payload: bytes, outcome: str,
) -> None:
    reads = []
    headers = []

    def get_password(service: str, name: str) -> str | None:
        reads.append(name)
        if outcome == "denied":
            raise KeyringLocked("private-token")
        return None if outcome == "missing" else "fake-token"

    def open_response(request: Any, **kwargs: Any) -> io.BytesIO:
        headers.append(request.headers)
        return io.BytesIO(payload)

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(module, "urlopen", open_response)
    connector = connector_type(SecretManager(KeychainSecretBackend()))
    context = DiscoveryContext(TopicConfig(id="test", queries=["one", "two"]), limit=1)
    connector.discover(context)
    connector.discover(context)
    assert len(reads) == 1
    warnings = connector.diagnostics["warnings"]
    assert len(warnings) == (1 if outcome == "denied" else 0)
    if warnings:
        assert warnings[0]["kind"] == "optional_credential_access_failed"
    assert "private-token" not in json.dumps(connector.diagnostics)
    assert "fake-token" not in json.dumps(connector.diagnostics)
    auth_key = "Authorization" if module is github else "X-api-key"
    assert all((auth_key in item) == (outcome == "success") for item in headers)
    connector_type(SecretManager(KeychainSecretBackend())).discover(context)
    assert len(reads) == 2


def test_secret_missing_and_access_errors_are_typed_and_backend_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = iter([None, KeyringLocked("private"), "recovered"])

    def get_password(*args: str) -> str | None:
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(keyring, "get_password", get_password)
    backend = KeychainSecretBackend()
    for expected in ["SecretNotFoundError", "SecretAccessError"]:
        with pytest.raises(exceptions.SecretError) as caught:
            backend.get_secret("github.token")
        assert type(caught.value).__name__ == expected
    assert backend.get_secret("github.token") == "recovered"
    assert backend.get_secret("github.token") == "recovered"


@pytest.mark.parametrize("module,connector_type,payload", CONNECTORS)
def test_all_failed_diagnostics_are_bounded_and_redacted(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, connector_type: Any, payload: bytes,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("private-url-auth-body")

    monkeypatch.setattr(module, "urlopen", fail)
    connector = connector_type()
    with pytest.raises(exceptions.DiscoveryError) as caught:
        connector.discover(DiscoveryContext(
            TopicConfig(id="test", queries=[f"private-{i}" for i in range(100)]), limit=1,
        ))
    assert connector.diagnostics["failed_query_count"] == 100
    assert connector.diagnostics["successful_query_count"] == 0
    assert len(connector.diagnostics["queries"]) <= 20
    assert "private" not in str(caught.value) + json.dumps(connector.diagnostics)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("text", ["agent memory", "long term memory for agents"])
def test_agent_memory_bootstrap_adds_vetted_context_aliases(text: str) -> None:
    aliases = bootstrap_topic_draft(text).concept_groups["agent_context"]
    assert "memory agent" in aliases
    assert "memory agents" in aliases


def test_unrelated_bootstrap_does_not_swap_words_or_add_memory_aliases() -> None:
    aliases = bootstrap_topic_draft("world models for embodied agents").concept_groups
    assert "memory agent" not in aliases["agent_context"]
    assert "models world" not in aliases["agent_context"]


def test_model_bootstrap_adds_only_vetted_aliases_preserving_model_context() -> None:
    payload = {
        "queries": ["agent memory"], "paper_queries": ["agent memory benchmark"],
        "concept_groups": {
            "agent_context": ["agent memory", "autonomous agents"],
            "memory_mechanism": ["long-term memory"],
            "evaluation_signal": ["benchmark"],
            "negative_compute_or_training": ["training"],
        },
    }
    topic = bootstrap_topic_draft("agent memory", provider=StaticProvider(json.dumps(payload)))
    assert topic.concept_groups["agent_context"] == [
        "agent memory", "autonomous agents", "memory agent", "memory agents",
    ]


def test_builtin_agent_memory_profile_has_vetted_aliases_only_in_agent_context() -> None:
    profile = next(spec for spec in DEFAULT_TOPIC_SMOKE_SPECS if spec.id == "agent-memory")
    assert "memory agent" in profile.concept_groups["agent_context"]
    assert "memory agents" in profile.concept_groups["agent_context"]
    for spec in DEFAULT_TOPIC_SMOKE_SPECS:
        if spec.id != "agent-memory":
            assert "memory agent" not in spec.concept_groups["agent_context"]


@pytest.mark.parametrize("all_failed", [False, True])
@pytest.mark.parametrize("module,connector_type,payload", CONNECTORS[1:])
def test_orchestrator_promotes_credentials_and_http_failures(
    monkeypatch: pytest.MonkeyPatch, all_failed: bool, module: ModuleType,
    connector_type: Any, payload: bytes,
) -> None:
    reads: list[str] = []
    requests: list[int] = []

    def denied(service: str, name: str) -> None:
        reads.append(name)
        raise KeyringLocked("private-credential")

    def response(*args: Any, **kwargs: Any) -> io.BytesIO:
        requests.append(1)
        if all_failed or len(requests) == 1:
            raise HTTPError("https://private.invalid", 429, "private-body", {}, None)
        return io.BytesIO(payload)

    monkeypatch.setattr(keyring, "get_password", denied)
    monkeypatch.setattr(module, "urlopen", response)
    result = DiscoveryOrchestrator([
        connector_type(SecretManager(KeychainSecretBackend())),
    ]).discover(TopicConfig(id="test", queries=["one", "two"]), limit=1)
    credential_findings = [
        f for f in result.findings
        if f.metadata.get("kind") == "optional_credential_access_failed"
    ]
    assert len(credential_findings) == 1
    assert credential_findings[0].severity == "warning"
    assert credential_findings[0].metadata["discovery_provider"] == module.__name__.split(".")[-1]
    failures = [f for f in result.findings if f.metadata.get("http_status") == 429]
    expected_requests = 2 if module is github else 10
    assert len(failures) == (expected_requests if all_failed else 1)
    assert len(requests) == expected_requests
    assert len(reads) == 1
    assert any(f.metadata.get("kind") == "discovery_failed" for f in result.findings) == all_failed
    assert "private" not in repr(result.findings)


@pytest.mark.parametrize("status,expected", [(503, 503), (99, None), (600, None),
                                             (True, None), ("private", None)])
@pytest.mark.parametrize("all_failed", [False, True])
def test_orchestrator_bounds_and_sanitizes_diagnostic_findings(
    status: object, expected: int | None, all_failed: bool,
) -> None:
    class Connector:
        name = "github"
        diagnostics = {
            "warnings": [{
                "kind": "optional_credential_access_failed",
                "message": "private-token-url-body",
                "error_type": "private-type",
            }] * 100,
            "queries": [{"status": "failed", "http_status": status}] * 100,
        }

        def discover(self, context: DiscoveryContext) -> list[Any]:
            if all_failed:
                raise exceptions.DiscoveryError("Discovery unavailable")
            return []

    result = DiscoveryOrchestrator([Connector()]).discover(
        TopicConfig(id="test", queries=["one"]), limit=1,
    )
    credential_findings = [
        f for f in result.findings
        if f.metadata.get("kind") == "optional_credential_access_failed"
    ]
    assert len(credential_findings) == 1
    assert "private" not in repr(credential_findings)
    query_findings = [
        f for f in result.findings if f.metadata.get("kind") == "web_search_query_failed"
    ]
    assert len(query_findings) == 20
    assert all(f.metadata.get("http_status") == expected for f in query_findings)
