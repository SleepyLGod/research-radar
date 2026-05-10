from research_radar.security.crypto import EnvelopeEncryptor, InMemoryMasterKeyProvider
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import EnvSecretBackend, InMemorySecretBackend, SecretManager


def test_secret_manager_uses_backend() -> None:
    manager = SecretManager(InMemorySecretBackend())
    manager.set_deepseek_api_key("fake-deepseek-key")

    assert manager.get_deepseek_api_key() == "fake-deepseek-key"


def test_env_secret_backend_reads_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-deepseek-key")
    manager = SecretManager(EnvSecretBackend())

    assert manager.get_deepseek_api_key() == "fake-deepseek-key"


def test_envelope_encryption_round_trip() -> None:
    encryptor = EnvelopeEncryptor(InMemoryMasterKeyProvider(b"0" * 32))
    payload = encryptor.encrypt_json({"access_token": "fake-token"}, aad=b"test")

    assert "fake-token" not in str(payload)
    assert encryptor.decrypt_json(payload, aad=b"test") == {"access_token": "fake-token"}


def test_redact_text_removes_sensitive_values() -> None:
    value = "api_key=sk-fakefakefakefakefake path=/Users/someone/private localhost:12345"

    redacted = redact_text(value)

    assert "sk-fake" not in redacted
    assert "/Users/someone" not in redacted
    assert "localhost:12345" not in redacted
