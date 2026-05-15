from http.client import IncompleteRead

from research_radar.analysis.deepseek import DeepSeekProvider
from research_radar.analysis.providers import Message
from research_radar.exceptions import AnalysisError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def test_deepseek_provider_wraps_incomplete_http_reads(monkeypatch) -> None:
    manager = SecretManager(InMemorySecretBackend())
    manager.set_deepseek_api_key("fake-key")
    provider = DeepSeekProvider(manager)

    def fake_urlopen(*args, **kwargs):
        raise IncompleteRead(b"")

    monkeypatch.setattr("research_radar.analysis.deepseek.urlopen", fake_urlopen)

    try:
        provider.complete([Message(role="user", content="hello")], model="fake")
    except AnalysisError as exc:
        assert "DeepSeek request failed" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")
