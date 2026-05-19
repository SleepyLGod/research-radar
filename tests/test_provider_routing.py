import json
import os
from http.client import IncompleteRead
from pathlib import Path

from research_radar.analysis.anthropic import AnthropicMessagesProvider
from research_radar.analysis.cli_providers import ClaudeCodeCliProvider, CodexCliProvider
from research_radar.analysis.openai_compatible import OpenAICompatibleProvider
from research_radar.analysis.providers import Message
from research_radar.analysis.routing import build_provider, resolve_task_route
from research_radar.config import ConfigError, parse_config
from research_radar.exceptions import AnalysisError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def test_parse_config_accepts_model_providers_and_task_routes() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "custom_openai": {
                    "kind": "openai_compatible",
                    "base_url": "https://api.example.test/chat/completions",
                    "api_key_secret": "openai.api_key",
                }
            },
            "models": {
                "task_routes": {
                    "deep_reading": {
                        "provider": "custom_openai",
                        "model": "example-model",
                    }
                }
            },
        }
    )

    assert config.model_providers["custom_openai"].kind == "openai_compatible"
    assert config.models.task_routes["deep_reading"].provider == "custom_openai"
    assert config.models.task_routes["deep_reading"].model == "example-model"


def test_unknown_provider_instance_fails() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    manager = SecretManager(InMemorySecretBackend())

    try:
        build_provider(config, manager, "missing")
    except ConfigError as exc:
        assert "Unknown model provider" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_missing_cli_command_fails_health_check() -> None:
    provider = CodexCliProvider(name="codex", command="/missing/research-radar-codex")

    try:
        provider.health_check()
    except AnalysisError as exc:
        assert "Provider command not found" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")


def test_openai_and_deepseek_use_openai_compatible_provider() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    manager = SecretManager(InMemorySecretBackend())

    assert isinstance(build_provider(config, manager, "deepseek"), OpenAICompatibleProvider)
    assert isinstance(build_provider(config, manager, "openai"), OpenAICompatibleProvider)


def test_openai_compatible_wraps_incomplete_http_reads(monkeypatch) -> None:
    manager = SecretManager(InMemorySecretBackend())
    manager.set_openai_api_key("fake-key")
    provider = OpenAICompatibleProvider(
        name="openai",
        endpoint="https://api.example.test/chat/completions",
        api_key_secret="openai.api_key",
        secrets=manager,
    )

    def fake_urlopen(*args, **kwargs):
        raise IncompleteRead(b"")

    monkeypatch.setattr("research_radar.analysis.openai_compatible.urlopen", fake_urlopen)

    try:
        provider.complete([Message(role="user", content="hello")], model="fake")
    except AnalysisError as exc:
        assert "openai request failed" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")


def test_anthropic_provider_parses_messages_response(monkeypatch) -> None:
    manager = SecretManager(InMemorySecretBackend())
    manager.set_anthropic_api_key("fake-key")
    provider = AnthropicMessagesProvider(
        name="anthropic",
        api_key_secret="anthropic.api_key",
        secrets=manager,
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"content": [{"text": "anthropic response"}]}).encode()

    monkeypatch.setattr(
        "research_radar.analysis.anthropic.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    response = provider.complete([Message(role="user", content="hello")], model="sonnet")

    assert response.content == "anthropic response"
    assert response.metadata["provider"] == "anthropic"


def test_codex_cli_provider_reads_output_last_message(tmp_path: Path) -> None:
    command = _fake_codex_command(tmp_path)
    provider = CodexCliProvider(name="codex", command=str(command))

    response = provider.complete([Message(role="user", content="hello")], model="fake-model")

    assert response.content == "codex response"
    assert response.metadata["provider"] == "codex"


def test_claude_code_cli_provider_reads_stdout(tmp_path: Path) -> None:
    command = _fake_claude_command(tmp_path)
    provider = ClaudeCodeCliProvider(name="von_claude", command=str(command))

    response = provider.complete([Message(role="user", content="hello")], model="sonnet")

    assert response.content == "claude response"
    assert response.metadata["provider"] == "von_claude"


def test_task_specific_override_beats_global_provider(tmp_path: Path) -> None:
    command = _fake_codex_command(tmp_path)
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "codex": {"kind": "codex_cli", "command": str(command)},
            },
        }
    )
    manager = SecretManager(InMemorySecretBackend())

    route = resolve_task_route(
        config,
        manager,
        "verifier",
        provider_override="codex",
        global_provider="deepseek",
        global_model="deepseek-chat",
        default_local=False,
    )

    assert route.provider_name == "codex"
    assert route.model == "gpt-5.4"
    assert isinstance(route.provider, CodexCliProvider)


def _fake_codex_command(tmp_path: Path) -> Path:
    command = tmp_path / "fake-codex"
    command.write_text(
        "#!/bin/sh\n"
        "output=''\n"
        "prev=''\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$prev\" = '--output-last-message' ]; then output=\"$arg\"; fi\n"
        "  prev=\"$arg\"\n"
        "done\n"
        "printf 'codex response\\n' > \"$output\"\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return command


def _fake_claude_command(tmp_path: Path) -> Path:
    command = tmp_path / "fake-claude"
    command.write_text("#!/bin/sh\nprintf 'claude response\\n'\n", encoding="utf-8")
    command.chmod(0o755)
    os.environ["PATH"] = f"{tmp_path}:{os.environ.get('PATH', '')}"
    return command
