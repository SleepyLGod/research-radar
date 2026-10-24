"""Job-local credential caching without touching the system Keychain."""

import os
from concurrent.futures import ThreadPoolExecutor

import keyring
import pytest
from keyring.errors import KeyringError, KeyringLocked

from research_radar.app_bridge.runner import BridgeDependencies
from research_radar.exceptions import SecretError
from research_radar.security.secrets import KeychainSecretBackend


def test_engine_job_caches_successful_reads_and_next_job_reads_fresh(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    values = {"deepseek.api_key": "fake-first", "web_search.api_key": "fake-search"}

    def get_password(service: str, name: str) -> str | None:
        calls.append((service, name))
        return values.get(name)

    monkeypatch.setattr(keyring, "get_password", get_password)
    environment = dict(os.environ)
    dependencies = BridgeDependencies.production()
    first = dependencies.secret_manager_factory()
    assert first.get_named_secret("deepseek.api_key") == "fake-first"
    values["deepseek.api_key"] = "fake-second"
    assert first.get_named_secret("deepseek.api_key") == "fake-first"
    assert first.get_named_secret("web_search.api_key") == "fake-search"
    second = dependencies.secret_manager_factory()
    assert second.get_named_secret("deepseek.api_key") == "fake-second"
    assert calls == [
        ("ResearchRadar", "deepseek.api_key"),
        ("ResearchRadar", "web_search.api_key"),
        ("ResearchRadar", "deepseek.api_key"),
    ]
    assert os.environ == environment
    assert "fake-first" not in repr(first)


def test_concurrent_reads_share_one_keychain_lookup(monkeypatch) -> None:
    calls: list[str] = []

    def get_password(service: str, name: str) -> str:
        calls.append(name)
        return "fake-value"

    monkeypatch.setattr(keyring, "get_password", get_password)
    backend = KeychainSecretBackend()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(backend.get_secret, ["deepseek.api_key"] * 20))
    assert results == ["fake-value"] * 20
    assert calls == ["deepseek.api_key"]


def test_missing_and_failed_reads_are_not_cached(monkeypatch) -> None:
    outcomes = iter([None, RuntimeError("locked"), "fake-unlocked"])

    def get_password(service: str, name: str) -> str | None:
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(keyring, "get_password", get_password)
    backend = KeychainSecretBackend()
    with pytest.raises(SecretError, match="Secret not found"):
        backend.get_secret("deepseek.api_key")
    with pytest.raises(RuntimeError, match="locked"):
        backend.get_secret("deepseek.api_key")
    assert backend.get_secret("deepseek.api_key") == "fake-unlocked"
    assert backend.get_secret("deepseek.api_key") == "fake-unlocked"


def test_successful_write_refreshes_cached_value(monkeypatch) -> None:
    values = {"deepseek.api_key": "fake-before"}
    reads: list[str] = []

    def get_password(service: str, name: str) -> str | None:
        reads.append(name)
        return values.get(name)

    def set_password(service: str, name: str, value: str) -> None:
        values[name] = value

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "set_password", set_password)
    backend = KeychainSecretBackend()
    assert backend.get_secret("deepseek.api_key") == "fake-before"
    backend.set_secret("deepseek.api_key", "fake-after")
    assert backend.get_secret("deepseek.api_key") == "fake-after"
    assert reads == ["deepseek.api_key"]


@pytest.mark.parametrize("error_type", [KeyringError, KeyringLocked])
def test_keyring_error_is_safe_and_retryable_on_same_backend(
    monkeypatch: pytest.MonkeyPatch, error_type: type[KeyringError],
) -> None:
    calls: list[str] = []

    def get_password(service: str, name: str) -> str:
        calls.append(name)
        if len(calls) == 1:
            raise error_type("fake-sensitive-error-detail")
        return "fake-recovered"

    monkeypatch.setattr(keyring, "get_password", get_password)
    backend = KeychainSecretBackend()
    with pytest.raises(SecretError, match="^Keychain secret access failed[.]$") as caught:
        backend.get_secret("deepseek.api_key")
    assert caught.value.__suppress_context__ is True
    assert backend.get_secret("deepseek.api_key") == "fake-recovered"
    assert backend.get_secret("deepseek.api_key") == "fake-recovered"
    assert calls == ["deepseek.api_key"] * 2
