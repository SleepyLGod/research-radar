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


def test_env_secret_backend_reads_xiaomi_key(monkeypatch) -> None:
    monkeypatch.setenv("XIAOMI_API_KEY", "fake-xiaomi-key")
    manager = SecretManager(EnvSecretBackend())

    assert manager.backend.get_secret("xiaomi.api_key") == "fake-xiaomi-key"


def test_envelope_encryption_round_trip() -> None:
    encryptor = EnvelopeEncryptor(InMemoryMasterKeyProvider(b"0" * 32))
    payload = encryptor.encrypt_json({"access_token": "fake-token"}, aad=b"test")

    assert "fake-token" not in str(payload)
    assert encryptor.decrypt_json(payload, aad=b"test") == {"access_token": "fake-token"}


def test_redact_text_removes_sensitive_values() -> None:
    value = (
        "api_key=sk-fakefakefakefakefake path=/Users/someone/private "
        "/tmp/research-radar /var/folders/abc localhost:12345"
    )

    redacted = redact_text(value)

    assert "sk-fake" not in redacted
    assert "/Users/someone" not in redacted
    assert "/tmp/research-radar" not in redacted
    assert "/var/folders/abc" not in redacted
    assert "localhost:12345" not in redacted


def test_redact_text_does_not_overmatch_tmp_prefix() -> None:
    redacted = redact_text("keep /tmpfile but redact /tmp/research-radar")

    assert "/tmpfile" in redacted
    assert "/tmp/research-radar" not in redacted


def test_redact_text_removes_common_quoted_and_dotted_secret_forms() -> None:
    value = (
        'app_secret="fake-wechat-secret-value" '
        "token=fake-runtime-token-value "
        "github.token=ghp_fakefakefakefake "
        "access_token='fake-wechat-access-token' "
        'api_key: "fake-provider-key-value"'
    )

    redacted = redact_text(value)

    assert "fake-wechat-secret-value" not in redacted
    assert "fake-runtime-token-value" not in redacted
    assert "ghp_fakefakefakefake" not in redacted
    assert "fake-wechat-access-token" not in redacted
    assert "fake-provider-key-value" not in redacted
    assert "app_secret" in redacted
    assert "github.token" in redacted
