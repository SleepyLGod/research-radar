import json
from argparse import Namespace
from pathlib import Path

import pytest

from research_radar import cli
from research_radar.analysis.cli_providers import CodexCliProvider
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.openai_compatible import OpenAICompatibleProvider
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.compose.draft import build_daily_draft
from research_radar.config import parse_config
from research_radar.exceptions import (
    ProviderTransportError,
    PublishError,
    ResearchRadarError,
    SecretError,
)
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, SourceCandidate, SourceType
from research_radar.storage.files import read_json, write_json


def test_topic_bootstrap_cli_writes_default_draft_and_prints_yaml(
    capsys,
    tmp_path: Path,
) -> None:
    cli.main(
        [
            "topic",
            "bootstrap",
            "--topic",
            "diffusion world models for embodied agents",
            "--root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    draft_path = tmp_path / "topic_drafts" / "diffusion-world-models-embodied-agents.yaml"

    assert draft_path.exists()
    assert f"Wrote topic draft: {draft_path.resolve()}" in output
    assert "```yaml" in output
    assert "diffusion-world-models-embodied-agents" in output


def test_topic_bootstrap_cli_supports_custom_output_and_language(
    capsys,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "drafts" / "custom.yaml"

    cli.main(
        [
            "topic",
            "bootstrap",
            "--topic",
            "diffusion world models",
            "--root",
            str(tmp_path),
            "--output",
            str(output_path),
            "--language",
            "zh",
        ]
    )

    output = capsys.readouterr().out
    text = output_path.read_text(encoding="utf-8")

    assert f"Wrote topic draft: {output_path.resolve()}" in output
    assert "report_language: zh" in text
    assert "report_language: zh" in output


def test_secrets_set_parser_accepts_xiaomi() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["secrets", "set", "xiaomi"])

    assert args.name == "xiaomi"


def test_eval_topics_parser_accepts_topic_budget_seconds() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["eval", "topics", "--topic-budget-seconds", "900"])

    assert args.topic_budget_seconds == 900


def test_eval_topics_parser_rejects_negative_topic_budget_seconds() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["eval", "topics", "--topic-budget-seconds", "-1"])

    assert exc_info.value.code == 2


def test_secrets_set_named_parser_accepts_arbitrary_secret_name() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["secrets", "set-named", "kimi.api_key"])

    assert args.name == "kimi.api_key"


def test_secrets_set_named_stores_without_printing_value(monkeypatch, capsys) -> None:
    stored: dict[str, str] = {}

    class FakeBackend:
        def set_secret(self, name: str, value: str) -> None:
            stored[name] = value

        def get_secret(self, name: str) -> str:
            return stored[name]

    monkeypatch.setattr(cli, "KeychainSecretBackend", lambda: FakeBackend())
    monkeypatch.setattr(cli, "_prompt_secret", lambda label: "secret-value-that-must-not-print")

    cli.handle_secrets_set_named(Namespace(name="kimi.api_key"))

    output = capsys.readouterr().out
    assert stored["kimi.api_key"] == "secret-value-that-must-not-print"
    assert "kimi.api_key" in output
    assert "secret-value-that-must-not-print" not in output


def test_secrets_status_prints_presence_without_values(monkeypatch, capsys) -> None:
    class FakeManager:
        def get_named_secret(self, name: str) -> str:
            if name == "deepseek.api_key":
                return "secret-value-that-must-not-print"
            raise SecretError(f"Secret not found: {name}")

    monkeypatch.setattr(cli, "_secret_manager", lambda source: FakeManager())

    cli.handle_secrets_status(Namespace(secret_source="keychain", env_file=None))

    output = capsys.readouterr().out
    assert "deepseek.api_key: present" in output
    assert "web_search.api_key: missing" in output
    assert "secret-value-that-must-not-print" not in output


def test_secrets_status_can_check_one_named_secret(monkeypatch, capsys) -> None:
    class FakeManager:
        def get_named_secret(self, name: str) -> str:
            if name == "kimi.api_key":
                return "secret-value-that-must-not-print"
            raise SecretError(f"Secret not found: {name}")

    monkeypatch.setattr(cli, "_secret_manager", lambda source: FakeManager())

    cli.handle_secrets_status(
        Namespace(secret_source="keychain", env_file=None, name="kimi.api_key")
    )

    output = capsys.readouterr().out
    assert "kimi.api_key: present" in output
    assert "deepseek.api_key" not in output
    assert "secret-value-that-must-not-print" not in output


def test_provider_probe_parser_defaults_to_small_probe() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["provider", "probe", "--provider", "xiaomi"])

    assert args.provider == "xiaomi"
    assert args.probe == "small"
    assert args.config == Path("config.yaml")


def test_provider_routes_parser_defaults_to_daily_mode() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["provider", "routes"])

    assert args.mode == "daily"
    assert args.config == Path("config.yaml")


def test_provider_list_outputs_configured_providers_without_secret_values(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "kimi": {
                    "kind": "openai_compatible",
                    "base_url": "https://api.example.test/v1/chat/completions",
                    "api_key_secret": "kimi.api_key",
                    "timeout_seconds": 333,
                }
            },
        }
    )

    class FakeManager:
        def get_named_secret(self, name: str) -> str:
            if name == "kimi.api_key":
                return "secret-value-that-must-not-print"
            raise SecretError(f"Secret not found: {name}")

    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)
    monkeypatch.setattr(cli, "_secret_manager", lambda source: FakeManager())

    cli.handle_provider_list(
        Namespace(config=tmp_path / "config.yaml", secret_source="keychain", env_file=None)
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    kimi = next(item for item in output["providers"] if item["name"] == "kimi")
    codex = next(item for item in output["providers"] if item["name"] == "codex")
    assert kimi["kind"] == "openai_compatible"
    assert kimi["host"] == "api.example.test"
    assert kimi["timeout_seconds"] == 333
    assert kimi["secret"] == "present"
    assert codex["secret"] == "not_required"
    assert "secret-value-that-must-not-print" not in output_text


def test_provider_routes_show_daily_defaults_and_deepseek_replacement(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "codex": {"kind": "codex_cli", "command": "/missing/research-radar-codex"}
            },
            "models": {
                "task_routes": {
                    "source_gist": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                    "deep_reading": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                    "anchor_repair": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                    "report_localization": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-flash",
                    },
                    "verifier": {"provider": "codex", "model": "gpt-5.5"},
                }
            },
        }
    )
    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)

    cli.handle_provider_routes(
        Namespace(
            config=tmp_path / "config.yaml",
            mode="daily",
            provider=None,
            model=None,
            deepseek_provider="xiaomi",
            gist_provider=None,
            gist_model=None,
            reader_provider=None,
            reader_model=None,
            verifier_provider=None,
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            localization_provider=None,
            localization_model=None,
            bootstrap_provider=None,
            bootstrap_model=None,
        )
    )

    output = json.loads(capsys.readouterr().out)
    routes = {item["task"]: item for item in output["routes"]}
    assert routes["source_gist"]["provider"] == "xiaomi"
    assert routes["source_gist"]["model"] == "mimo-v2.5-pro"
    assert routes["deep_reading"]["provider"] == "xiaomi"
    assert routes["deep_reading"]["model"] == "mimo-v2.5-pro"
    assert routes["verifier"]["provider"] == "codex"
    assert routes["verifier"]["model"] == "gpt-5.5"


def test_provider_routes_show_task_specific_override_precedence(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "models": {
                "task_routes": {
                    "deep_reading": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                    "verifier": {"provider": "codex", "model": "gpt-5.5"},
                }
            },
        }
    )
    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)

    cli.handle_provider_routes(
        Namespace(
            config=tmp_path / "config.yaml",
            mode="paper",
            provider=None,
            model=None,
            deepseek_provider="xiaomi",
            gist_provider=None,
            gist_model=None,
            reader_provider="deepseek",
            reader_model=None,
            verifier_provider="xiaomi",
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            localization_provider=None,
            localization_model=None,
            bootstrap_provider=None,
            bootstrap_model=None,
        )
    )

    output = json.loads(capsys.readouterr().out)
    routes = {item["task"]: item for item in output["routes"]}
    assert routes["deep_reading"]["provider"] == "deepseek"
    assert routes["deep_reading"]["model"] == "deepseek-v4-pro"
    assert routes["verifier"]["provider"] == "xiaomi"
    assert routes["verifier"]["model"] == "mimo-v2.5-pro"


def test_provider_routes_unknown_provider_fails_clearly(monkeypatch, tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "models": {
                "task_routes": {
                    "deep_reading": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                }
            },
        }
    )
    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)

    with pytest.raises(ResearchRadarError, match="Unknown model provider: missing"):
        cli.handle_provider_routes(
            Namespace(
                config=tmp_path / "config.yaml",
                mode="paper",
                provider=None,
                model=None,
                deepseek_provider=None,
                gist_provider=None,
                gist_model=None,
                reader_provider="missing",
                reader_model=None,
                verifier_provider=None,
                verifier_model=None,
                anchor_repair_provider=None,
                anchor_repair_model=None,
                localization_provider=None,
                localization_model=None,
                bootstrap_provider=None,
                bootstrap_model=None,
            )
        )


def test_schedule_daily_draft_parser_defaults_to_codex_verifier() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            "schedule",
            "daily-draft",
            "--topic",
            "agent-memory",
            "--time",
            "09:30",
            "--config",
            "config.example.yaml",
            "--root",
            "research-radar-data",
            "--thumb-media-id",
            "thumb-media-id",
        ]
    )

    assert args.verifier_provider == "codex"
    assert args.verifier_model is None


def test_schedule_daily_draft_parser_requires_core_arguments() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "schedule",
                "daily-draft",
                "--topic",
                "agent-memory",
                "--time",
                "09:30",
                "--config",
                "config.example.yaml",
                "--root",
                "/tmp/research-radar",
            ]
        )

    assert exc_info.value.code == 2


def test_schedule_daily_draft_writes_runner_and_plist(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    output_dir = tmp_path / "schedule"
    uv_path = tmp_path / "bin" / "uv"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_resolve_uv_executable", lambda: uv_path)
    cli.handle_schedule_daily_draft(
        Namespace(
            topic="agent-memory",
            time="09:30",
            config=tmp_path / "config.yaml",
            root=tmp_path / "runs-root",
            thumb_media_id="thumb-media-id",
            title=None,
            digest=None,
            output_dir=output_dir,
            limit=5,
            deep_limit=1,
            language="zh",
            model_cache=True,
            publish_dry_run=True,
            deepseek_provider="xiaomi",
            gist_provider=None,
            gist_model=None,
            reader_provider=None,
            reader_model=None,
            verifier_provider="codex",
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            localization_provider=None,
            localization_model=None,
        )
    )

    output = capsys.readouterr().out
    runner_path = output_dir / "ai.research-radar.daily-draft.agent-memory.sh"
    plist_path = output_dir / "ai.research-radar.daily-draft.agent-memory.plist"
    runner = runner_path.read_text(encoding="utf-8")
    plist = plist_path.read_text(encoding="utf-8")

    assert "Generated local daily draft schedule artifacts" in output
    assert runner_path.exists()
    assert plist_path.exists()
    assert str(uv_path.resolve()) in runner
    assert "RUN_OUTPUT=\"$(uv run " not in runner
    assert "research-radar run daily" in runner
    assert "research-radar publish wechat-draft" in runner
    assert "--secret-source keychain" in runner
    assert "--deepseek-provider xiaomi" in runner
    assert "--verifier-provider codex" in runner
    assert "--verifier-model gpt-5.5" in runner
    assert "--dry-run" in runner
    assert "API_KEY" not in plist
    assert "appsecret" not in plist.casefold()
    assert "access_token" not in plist.casefold()


def test_schedule_daily_draft_non_codex_verifier_does_not_inherit_codex_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    output_dir = tmp_path / "schedule"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_resolve_uv_executable", lambda: tmp_path / "bin" / "uv")
    cli.handle_schedule_daily_draft(
        Namespace(
            topic="agent-memory",
            time="09:30",
            config=tmp_path / "config.yaml",
            root=tmp_path / "runs-root",
            thumb_media_id="thumb-media-id",
            title=None,
            digest=None,
            output_dir=output_dir,
            limit=5,
            deep_limit=1,
            language=None,
            model_cache=False,
            publish_dry_run=True,
            deepseek_provider=None,
            gist_provider=None,
            gist_model=None,
            reader_provider=None,
            reader_model=None,
            verifier_provider="deepseek",
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            localization_provider=None,
            localization_model=None,
        )
    )

    runner = (
        output_dir / "ai.research-radar.daily-draft.agent-memory.sh"
    ).read_text(encoding="utf-8")
    assert "--verifier-provider deepseek" in runner
    assert "--verifier-model gpt-5.5" not in runner


def test_schedule_daily_draft_fails_when_uv_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    with pytest.raises(cli.ConfigError, match="Could not find `uv`"):
        cli.handle_schedule_daily_draft(
            Namespace(
                topic="agent-memory",
                time="09:30",
                config=tmp_path / "config.yaml",
                root=tmp_path / "runs-root",
                thumb_media_id="thumb-media-id",
                title=None,
                digest=None,
                output_dir=tmp_path / "schedule",
                limit=5,
                deep_limit=1,
                language="zh",
                model_cache=True,
                publish_dry_run=True,
                deepseek_provider=None,
                gist_provider=None,
                gist_model=None,
                reader_provider=None,
                reader_model=None,
                verifier_provider="codex",
                verifier_model=None,
                anchor_repair_provider=None,
                anchor_repair_model=None,
                localization_provider=None,
                localization_model=None,
            )
        )


def test_run_daily_can_write_run_dir_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    run_dir = tmp_path / "runs" / "daily-run"
    output_path = tmp_path / "last_run_dir.txt"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", lambda *args, **kwargs: run_dir)
    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="local",
            model=None,
            secret_source="env",
            env_file=None,
            limit=5,
            deep_limit=0,
            language=None,
            model_cache=False,
            run_dir_output=output_path,
        )
    )

    assert output_path.read_text(encoding="utf-8").strip() == str(run_dir)


def test_provider_probe_outputs_success_diagnostics(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    captured: dict[str, object] = {}

    class FakeProvider:
        name = "xiaomi"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            captured["model"] = model
            captured["prompt"] = messages[0].content
            return ModelResponse(
                content="ResearchRadar provider probe ok.",
                model=model,
                metadata={"provider": self.name},
            )

    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)
    monkeypatch.setattr(
        cli,
        "resolve_task_route",
        lambda *args, **kwargs: cli.TaskModelRoute(
            provider=FakeProvider(),
            model="mimo-v2.5-pro",
            provider_name="xiaomi",
        ),
    )

    cli.handle_provider_probe(
        Namespace(
            provider="xiaomi",
            model=None,
            config=tmp_path / "config.yaml",
            probe="small",
            secret_source="env",
            env_file=None,
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert output["provider"] == "xiaomi"
    assert output["model"] == "mimo-v2.5-pro"
    assert output["timeout_seconds"] == 900
    assert "provider probe ok" in output["response_excerpt"]
    assert captured["model"] == "mimo-v2.5-pro"
    assert "Reply with exactly" in str(captured["prompt"])


def test_provider_probe_accepts_custom_named_provider(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "kimi": {
                    "kind": "openai_compatible",
                    "base_url": "https://api.example.test/v1/chat/completions",
                    "api_key_secret": "kimi.api_key",
                    "timeout_seconds": 222,
                }
            },
        }
    )

    class FakeProvider:
        name = "kimi"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            return ModelResponse(
                content="ResearchRadar provider probe ok.",
                model=model,
                metadata={"provider": self.name},
            )

    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)
    monkeypatch.setattr(
        cli,
        "resolve_task_route",
        lambda *args, **kwargs: cli.TaskModelRoute(
            provider=FakeProvider(),
            model="moonshot-model",
            provider_name="kimi",
        ),
    )

    cli.handle_provider_probe(
        Namespace(
            provider="kimi",
            model="moonshot-model",
            config=tmp_path / "config.yaml",
            probe="small",
            secret_source="env",
            env_file=None,
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert output["provider"] == "kimi"
    assert output["model"] == "moonshot-model"
    assert output["timeout_seconds"] == 222


def test_provider_probe_validates_json_response(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    class FakeProvider:
        name = "xiaomi"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            return ModelResponse(
                content='```json\n{"status":"ok","provider_test":true}\n```',
                model=model,
                metadata={"provider": self.name},
            )

    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)
    monkeypatch.setattr(
        cli,
        "resolve_task_route",
        lambda *args, **kwargs: cli.TaskModelRoute(
            provider=FakeProvider(),
            model="mimo-v2.5-pro",
            provider_name="xiaomi",
        ),
    )

    cli.handle_provider_probe(
        Namespace(
            provider="xiaomi",
            model=None,
            config=tmp_path / "config.yaml",
            probe="json",
            secret_source="env",
            env_file=None,
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert output["json_valid"] is True


def test_provider_probe_reports_response_char_count(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    captured: dict[str, object] = {}

    class FakeProvider:
        name = "xiaomi"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            captured["prompt"] = messages[0].content
            return ModelResponse(
                content="Long response body.",
                model=model,
                metadata={"provider": self.name},
            )

    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)
    monkeypatch.setattr(
        cli,
        "resolve_task_route",
        lambda *args, **kwargs: cli.TaskModelRoute(
            provider=FakeProvider(),
            model="mimo-v2.5-pro",
            provider_name="xiaomi",
        ),
    )

    cli.handle_provider_probe(
        Namespace(
            provider="xiaomi",
            model=None,
            config=tmp_path / "config.yaml",
            probe="long",
            secret_source="env",
            env_file=None,
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert output["response_char_count"] == len("Long response body.")
    assert "LLM API transport stress-test" in str(captured["prompt"])


def test_provider_probe_outputs_redacted_failure_diagnostics(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    class FakeProvider:
        name = "xiaomi"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            raise ProviderTransportError(
                "xiaomi request failed; access_token=fake-secret-token",
                {
                    "provider": "xiaomi",
                    "model": model,
                    "response_excerpt": "access_token=fake-secret-token",
                },
            )

    monkeypatch.setattr(cli, "_load_routing_config", lambda path: config)
    monkeypatch.setattr(
        cli,
        "resolve_task_route",
        lambda *args, **kwargs: cli.TaskModelRoute(
            provider=FakeProvider(),
            model="mimo-v2.5-pro",
            provider_name="xiaomi",
        ),
    )

    try:
        cli.handle_provider_probe(
            Namespace(
                provider="xiaomi",
                model=None,
                config=tmp_path / "config.yaml",
                probe="small",
                secret_source="env",
                env_file=None,
            )
        )
    except ProviderTransportError:
        pass
    else:
        raise AssertionError("Expected ProviderTransportError")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert output["provider"] == "xiaomi"
    assert "fake-secret-token" not in json.dumps(output)
    assert "access_token" in json.dumps(output)


def test_run_daily_can_use_deepseek_verifier_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    captured: dict[str, object] = {}
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY='fake-deepseek-key'\n", encoding="utf-8")

    def fake_run_daily(*args, **kwargs):
        captured["verifier"] = kwargs.get("verifier")
        captured["verifier_model"] = kwargs.get("verifier_model")
        captured["limit"] = kwargs.get("limit")
        captured["deep_reader"] = kwargs.get("deep_reader")
        captured["deep_model"] = kwargs.get("deep_model")
        captured["deep_limit"] = kwargs.get("deep_limit")
        captured["language"] = kwargs.get("language")
        return tmp_path / "runs" / "fake-run"

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="deepseek",
            model=None,
            secret_source="env",
            env_file=env_file,
            limit=3,
            deep_limit=1,
            language="zh",
        )
    )

    assert isinstance(captured["verifier"], OpenAICompatibleProvider)
    assert captured["verifier"].name == "deepseek"
    assert captured["verifier_model"] == "deepseek-v4-flash"
    assert captured["limit"] == 3
    assert isinstance(captured["deep_reader"], OpenAICompatibleProvider)
    assert captured["deep_reader"].name == "deepseek"
    assert captured["deep_model"] == "deepseek-v4-flash"
    assert captured["deep_limit"] == 1
    assert captured["language"] == "zh"


def test_run_daily_deepseek_provider_replacement_uses_xiaomi(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "models": {
                "task_routes": {
                    "source_gist": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                    "deep_reading": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                    },
                    "anchor_repair": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                    },
                    "verifier": {"provider": "local", "model": "local"},
                }
            },
        }
    )
    captured: dict[str, object] = {}
    env_file = tmp_path / ".env"
    env_file.write_text("XIAOMI_API_KEY='fake-xiaomi-key'\n", encoding="utf-8")

    def fake_run_daily(*args, **kwargs):
        captured.update(kwargs)
        return tmp_path / "runs" / "fake-run"

    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider=None,
            model=None,
            deepseek_provider="xiaomi",
            gist_provider=None,
            gist_model=None,
            reader_provider=None,
            reader_model=None,
            verifier_provider=None,
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            localization_provider=None,
            localization_model=None,
            secret_source="env",
            env_file=env_file,
            limit=3,
            deep_limit=1,
            language=None,
            model_cache=False,
        )
    )

    assert isinstance(captured["gist_provider"], OpenAICompatibleProvider)
    assert captured["gist_provider"].name == "xiaomi"
    assert captured["gist_model"] == "mimo-v2.5-pro"
    assert isinstance(captured["deep_reader"], OpenAICompatibleProvider)
    assert captured["deep_reader"].name == "xiaomi"
    assert captured["deep_model"] == "mimo-v2.5-pro"
    assert isinstance(captured["anchor_repair_provider"], OpenAICompatibleProvider)
    assert captured["anchor_repair_provider"].name == "xiaomi"
    assert captured["anchor_repair_model"] == "mimo-v2.5-pro"
    assert captured["verifier"] is None
    assert captured["verifier_model"] is None


def test_run_daily_task_specific_override_beats_deepseek_provider_replacement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "models": {
                "task_routes": {
                    "deep_reading": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                    },
                    "verifier": {"provider": "local", "model": "local"},
                }
            },
        }
    )
    captured: dict[str, object] = {}
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY='fake-deepseek-key'\n"
        "XIAOMI_API_KEY='fake-xiaomi-key'\n",
        encoding="utf-8",
    )

    def fake_run_daily(*args, **kwargs):
        captured.update(kwargs)
        return tmp_path / "runs" / "fake-run"

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider=None,
            model=None,
            deepseek_provider="xiaomi",
            gist_provider=None,
            gist_model=None,
            reader_provider="deepseek",
            reader_model=None,
            verifier_provider=None,
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            localization_provider=None,
            localization_model=None,
            secret_source="env",
            env_file=env_file,
            limit=3,
            deep_limit=1,
            language=None,
            model_cache=False,
        )
    )

    assert isinstance(captured["deep_reader"], OpenAICompatibleProvider)
    assert captured["deep_reader"].name == "deepseek"
    assert captured["deep_model"] == "deepseek-v4-pro"


def test_run_daily_local_provider_does_not_configure_verifier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    captured: dict[str, object] = {}

    def fake_run_daily(*args, **kwargs):
        captured["verifier"] = kwargs.get("verifier")
        captured["verifier_model"] = kwargs.get("verifier_model")
        captured["limit"] = kwargs.get("limit")
        captured["deep_reader"] = kwargs.get("deep_reader")
        captured["deep_limit"] = kwargs.get("deep_limit")
        return tmp_path / "runs" / "fake-run"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="local",
            model=None,
            secret_source="keychain",
            env_file=None,
            limit=10,
            deep_limit=1,
        )
    )

    assert captured["verifier"] is None
    assert captured["verifier_model"] is None
    assert captured["limit"] == 10
    assert captured["deep_reader"] is None
    assert captured["deep_limit"] == 1


def test_run_daily_model_cache_wraps_model_routes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    captured: dict[str, object] = {}
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY='fake-deepseek-key'\n", encoding="utf-8")

    def fake_run_daily(*args, **kwargs):
        captured.update(kwargs)
        return tmp_path / "runs" / "fake-run"

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="deepseek",
            model=None,
            gist_provider=None,
            gist_model=None,
            reader_provider=None,
            reader_model=None,
            verifier_provider=None,
            verifier_model=None,
            anchor_repair_provider=None,
            anchor_repair_model=None,
            secret_source="env",
            env_file=env_file,
            limit=3,
            deep_limit=1,
            language=None,
            model_cache=True,
        )
    )

    assert isinstance(captured["gist_provider"], CachedLLMProvider)
    assert isinstance(captured["deep_reader"], CachedLLMProvider)
    assert isinstance(captured["verifier"], CachedLLMProvider)
    assert (
        captured["deep_reader"].cache_dir
        == tmp_path / "cache" / "model_calls" / "deep_reading"
    )


def test_run_daily_supports_task_specific_provider_routes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    codex_command = tmp_path / "fake-codex"
    codex_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_command.chmod(0o755)
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "codex": {"kind": "codex_cli", "command": str(codex_command)},
            },
        }
    )
    captured: dict[str, object] = {}

    def fake_run_daily(*args, **kwargs):
        captured["gist_provider"] = kwargs.get("gist_provider")
        captured["gist_model"] = kwargs.get("gist_model")
        captured["deep_reader"] = kwargs.get("deep_reader")
        captured["deep_model"] = kwargs.get("deep_model")
        captured["verifier"] = kwargs.get("verifier")
        captured["verifier_model"] = kwargs.get("verifier_model")
        return tmp_path / "runs" / "fake-run"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="deepseek",
            model="deepseek-v4-flash",
            gist_provider="openai",
            gist_model="gpt-5.4",
            reader_provider=None,
            reader_model=None,
            verifier_provider="codex",
            verifier_model="gpt-5.4",
            secret_source="env",
            env_file=None,
            limit=3,
            deep_limit=1,
            language=None,
        )
    )

    assert captured["gist_provider"].name == "openai"
    assert captured["gist_model"] == "gpt-5.4"
    assert captured["deep_reader"].name == "deepseek"
    assert captured["deep_model"] == "deepseek-v4-flash"
    assert isinstance(captured["verifier"], CodexCliProvider)
    assert captured["verifier_model"] == "gpt-5.4"


def test_run_daily_adds_configured_web_search_connector(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "discovery": {
                "web_search": {
                    "endpoint": "https://search.example.test/api",
                }
            },
        }
    )
    captured: dict[str, object] = {}

    def fake_run_daily(*args, **kwargs):
        captured["connectors"] = args[3]
        return tmp_path / "runs" / "fake-run"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="local",
            model=None,
            secret_source="keychain",
            env_file=None,
            limit=10,
            deep_limit=0,
        )
    )

    connectors = captured["connectors"]
    assert [connector.name for connector in connectors] == [
        "arxiv",
        "semantic_scholar",
        "openalex",
        "web_search",
        "github",
    ]


def test_run_daily_adds_tavily_web_search_connector(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "discovery": {
                "web_search": {
                    "provider": "tavily",
                    "header_secret_name": "web_search.api_key",
                    "max_results": 4,
                    "timeout_seconds": 9,
                }
            },
        }
    )
    captured: dict[str, object] = {}

    def fake_run_daily(*args, **kwargs):
        captured["connectors"] = args[3]
        return tmp_path / "runs" / "fake-run"

    monkeypatch.setenv("WEB_SEARCH_API_KEY", "tvly-test")
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="local",
            model=None,
            secret_source="env",
            env_file=None,
            limit=10,
            deep_limit=0,
        )
    )

    connectors = captured["connectors"]
    assert [connector.name for connector in connectors] == [
        "arxiv",
        "semantic_scholar",
        "openalex",
        "web_search",
        "github",
    ]
    assert connectors[3].__class__.__name__ == "TavilyWebSearchConnector"
    assert connectors[3].max_results == 4
    assert connectors[3].timeout_seconds == 9


def test_publish_wechat_draft_dry_run_uses_article_draft(
    capsys,
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path)
    (run_dir / "wechat.html").write_text("stale unverified html", encoding="utf-8")

    cli.main(
        [
            "publish",
            "wechat-draft",
            "--run",
            str(run_dir),
            "--title",
            "Daily title",
            "--digest",
            "Manual digest",
            "--thumb-media-id",
            "thumb123",
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    result = read_json(run_dir / "publish_wechat_draft.json")
    request = read_json(run_dir / "publish_wechat_draft_request.json")
    preview_html = (run_dir / "wechat.html").read_text(encoding="utf-8")
    publish_html = (run_dir / "wechat_publish.html").read_text(encoding="utf-8")
    assert "Prepared WeChat draft dry run" in output
    assert result["status"] == "dry_run"
    assert result["draft_created"] is False
    assert request["draft_only"] is True
    assert request["auto_publish"] is False
    assert request["content_path"].endswith("wechat_publish.html")
    assert preview_html == "stale unverified html"
    assert "Verified claim for WeChat draft." in publish_html


def test_publish_wechat_draft_dry_run_omits_local_figure_images(
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path, with_local_figure=True)
    cli.main(["compose", "wechat", "--run", str(run_dir)])

    cli.main(
        [
            "publish",
            "wechat-draft",
            "--run",
            str(run_dir),
            "--title",
            "Daily title",
            "--digest",
            "Manual digest",
            "--thumb-media-id",
            "thumb123",
            "--dry-run",
        ]
    )

    preview_html = (run_dir / "wechat.html").read_text(encoding="utf-8")
    publish_html = (run_dir / "wechat_publish.html").read_text(encoding="utf-8")
    assert '<img src="figures/' in preview_html
    assert '<img src="figures/' not in publish_html
    assert "Figure image requires WeChat media upload before publishing." in publish_html


def test_publish_wechat_draft_uploads_local_figure_images(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path, with_local_figure=True)
    captured: dict[str, object] = {}
    uploaded_paths: list[str] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def upload_article_image(self, image_path: Path) -> str:
            uploaded_paths.append(str(image_path))
            return "https://mmbiz.qpic.cn/fixture/architecture.png"

        def add_draft(self, article) -> dict[str, object]:
            captured["article"] = article
            return {"media_id": "draft-media"}

    monkeypatch.setattr(cli, "WeChatDraftClient", FakeClient)

    cli.main(
        [
            "publish",
            "wechat-draft",
            "--run",
            str(run_dir),
            "--title",
            "Daily title",
            "--digest",
            "Manual digest",
            "--thumb-media-id",
            "thumb123",
        ]
    )

    result = read_json(run_dir / "publish_wechat_draft.json")
    request = read_json(run_dir / "publish_wechat_draft_request.json")
    publish_html = (run_dir / "wechat_publish.html").read_text(encoding="utf-8")
    article = captured["article"]
    assert result["status"] == "created"
    assert result["draft_created"] is True
    assert uploaded_paths == [str(run_dir / "figures/paper/architecture.png")]
    assert "figures/paper/architecture.png" not in publish_html
    assert "https://mmbiz.qpic.cn/fixture/architecture.png" in publish_html
    assert "https://mmbiz.qpic.cn/fixture/architecture.png" in article.content
    assert request["media_uploads"] == [
        {
            "local_src": "figures/paper/architecture.png",
            "uploaded_url": "https://mmbiz.qpic.cn/fixture/architecture.png",
        }
    ]
    assert request["content_path"].endswith("wechat_publish.html")


def test_publish_wechat_draft_fails_when_figure_upload_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path, with_local_figure=True)
    called = False

    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def upload_article_image(self, image_path: Path) -> str:
            raise PublishError("WeChat image upload failed: token=secret-value")

        def add_draft(self, article) -> dict[str, object]:
            nonlocal called
            called = True
            return {"media_id": "draft-media"}

    monkeypatch.setattr(cli, "WeChatDraftClient", FailingClient)

    try:
        cli.main(
            [
                "publish",
                "wechat-draft",
                "--run",
                str(run_dir),
                "--title",
                "Daily title",
                "--digest",
                "Manual digest",
                "--thumb-media-id",
                "thumb123",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected publish failure")

    error = read_json(run_dir / "publish_error.json")
    assert called is False
    assert error["error_type"] == "PublishError"
    assert "secret-value" not in error["message"]
    assert "WeChat image upload failed" in error["message"]


def test_compose_wechat_prefers_article_draft_when_present(
    capsys,
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path)
    write_json(
        run_dir / "claims.jsonl",
        [
            {
                "text": "Legacy claim-only output.",
                "status": "supported",
                "evidence": [{"source_url": "https://example.com", "quote": "legacy"}],
            }
        ],
    )

    cli.main(["compose", "wechat", "--run", str(run_dir)])

    output = capsys.readouterr().out
    html = (run_dir / "wechat.html").read_text(encoding="utf-8")
    assert "Wrote" in output
    assert "Verified claim for WeChat draft." in html
    assert "Legacy claim-only output." not in html


def test_publish_wechat_draft_posts_rendered_article_draft(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path)
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_draft(self, article) -> dict[str, object]:
            captured["article"] = article
            return {"media_id": "draft-media"}

    monkeypatch.setattr(cli, "WeChatDraftClient", FakeClient)

    cli.main(
        [
            "publish",
            "wechat-draft",
            "--run",
            str(run_dir),
            "--title",
            "Daily title",
            "--digest",
            "Manual digest",
            "--thumb-media-id",
            "thumb123",
        ]
    )

    result = read_json(run_dir / "publish_wechat_draft.json")
    article = captured["article"]
    assert result["status"] == "created"
    assert result["draft_created"] is True
    assert result["response"] == {"media_id": "draft-media"}
    assert article.title == "Daily title"
    assert "Verified claim for WeChat draft." in article.content


def test_publish_wechat_draft_writes_failure_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_publishable_article_draft(tmp_path)

    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_draft(self, article) -> dict[str, object]:
            raise PublishError("WeChat draft request failed: token=secret-value")

    monkeypatch.setattr(cli, "WeChatDraftClient", FailingClient)

    try:
        cli.main(
            [
                "publish",
                "wechat-draft",
                "--run",
                str(run_dir),
                "--title",
                "Daily title",
                "--digest",
                "Manual digest",
                "--thumb-media-id",
                "thumb123",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected publish failure")

    error = read_json(run_dir / "publish_error.json")
    assert error["target"] == "wechat_draft"
    assert error["error_type"] == "PublishError"
    assert "secret-value" not in error["message"]


def test_publish_wechat_parser_requires_manual_metadata() -> None:
    parser = cli.build_parser()

    try:
        parser.parse_args(["publish", "wechat-draft", "--run", "runs/example"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected parser failure")


def test_publish_wechat_upload_thumb_parser_accepts_image() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            "publish",
            "wechat-upload-thumb",
            "--image",
            "/tmp/cover.png",
        ]
    )

    assert args.image == Path("/tmp/cover.png")


def test_publish_wechat_upload_thumb_prints_media_id_and_writes_output(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"fake-png")
    output_path = tmp_path / "thumb.json"
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def upload_permanent_image_material(self, image_path: Path) -> dict[str, str]:
            captured["image_path"] = image_path
            return {
                "media_id": "thumb-media-id",
                "url": "https://mmbiz.qpic.cn/thumb.png",
            }

    monkeypatch.setattr(cli, "WeChatDraftClient", FakeClient)

    cli.main(
        [
            "publish",
            "wechat-upload-thumb",
            "--image",
            str(image_path),
            "--output",
            str(output_path),
        ]
    )

    output = capsys.readouterr().out
    result = read_json(output_path)
    assert captured["image_path"] == image_path
    assert "thumb_media_id: thumb-media-id" in output
    assert "url: https://mmbiz.qpic.cn/thumb.png" in output
    assert result == {
        "thumb_media_id": "thumb-media-id",
        "url": "https://mmbiz.qpic.cn/thumb.png",
        "image_path": str(image_path),
    }


def test_publish_wechat_upload_thumb_missing_image_fails(capsys, tmp_path: Path) -> None:
    missing_image = tmp_path / "missing.png"

    try:
        cli.main(
            [
                "publish",
                "wechat-upload-thumb",
                "--image",
                str(missing_image),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected upload failure")

    error = capsys.readouterr().err
    assert "WeChat thumbnail image not found" in error


def test_publish_wechat_upload_thumb_redacts_failure(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"fake-png")

    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def upload_permanent_image_material(self, image_path: Path) -> dict[str, str]:
            raise PublishError("WeChat thumbnail upload failed: token=secret-value")

    monkeypatch.setattr(cli, "WeChatDraftClient", FailingClient)

    try:
        cli.main(
            [
                "publish",
                "wechat-upload-thumb",
                "--image",
                str(image_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected upload failure")

    error = capsys.readouterr().err
    assert "WeChat thumbnail upload failed" in error
    assert "secret-value" not in error


def test_run_daily_skips_web_search_when_configured_secret_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "discovery": {
                "web_search": {
                    "endpoint": "https://search.example.test/api",
                    "header_secret_name": "web_search.api_key",
                }
            },
        }
    )
    captured: dict[str, object] = {}

    def fake_run_daily(*args, **kwargs):
        captured["connectors"] = args[3]
        return tmp_path / "runs" / "fake-run"

    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_daily", fake_run_daily)

    cli.handle_run_daily(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            provider="local",
            model=None,
            secret_source="env",
            env_file=None,
            limit=10,
            deep_limit=0,
        )
    )

    connectors = captured["connectors"]
    assert [connector.name for connector in connectors] == [
        "arxiv",
        "semantic_scholar",
        "openalex",
        "github",
    ]


def test_run_paper_can_use_deepseek_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "models": {
                "task_routes": {
                    "deep_reading": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                    }
                }
            },
        }
    )
    captured: dict[str, object] = {}
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY='fake-deepseek-key'\n", encoding="utf-8")

    def fake_run_paper(*args, **kwargs):
        captured["reader"] = args[4]
        captured["url"] = args[3]
        captured["model"] = kwargs.get("model")
        return tmp_path / "runs" / "fake-paper-run"

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "run_paper", fake_run_paper)

    cli.handle_run_paper(
        Namespace(
            config=Path("config.yaml"),
            root=tmp_path,
            topic="agent-memory",
            url="https://arxiv.org/pdf/2604.01707v1",
            provider="deepseek",
            model=None,
            secret_source="env",
            env_file=env_file,
        )
    )

    assert isinstance(captured["reader"], OpenAICompatibleProvider)
    assert captured["reader"].name == "deepseek"
    assert captured["url"] == "https://arxiv.org/pdf/2604.01707v1"
    assert captured["model"] == "deepseek-v4-pro"


def _write_publishable_article_draft(
    tmp_path: Path,
    *,
    with_local_figure: bool = False,
) -> Path:
    run_dir = tmp_path / "runs" / "daily-run"
    claim = Claim(
        text="Verified claim for WeChat draft.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://example.com/paper",
                source_title="Fixture Paper",
                quote="Verified claim for WeChat draft.",
            )
        ],
    )
    source = SourceCandidate(
        title="Fixture Paper",
        url="https://example.com/paper",
        source_type=SourceType.PAPER,
        source_name="fixture",
        metadata={"source_role": {"role": "primary_paper"}},
    )
    figures = {}
    readings = []
    deep_read_sources = []
    if with_local_figure:
        figure_path = run_dir / "figures/paper/architecture.png"
        figure_path.parent.mkdir(parents=True, exist_ok=True)
        figure_path.write_bytes(b"fake-png")
        readings = [
            {
                "title": source.title,
                "essence": "A verified paper.",
            }
        ]
        deep_read_sources = [source]
        figures = {
            source.url: [
                {
                    "title": "fig:architecture",
                    "relative_path": "figures/paper/architecture.png",
                    "caption": "Architecture overview.",
                    "explanation": (
                        "This figure is included as source context; it does not add a new claim."
                    ),
                    "attribution": "Fixture Paper; https://example.com/paper",
                    "license": "unknown",
                    "reuse_status": "needs_manual_review",
                    "renderable": True,
                }
            ]
        }
    write_json(
        run_dir / "article_draft.json",
        build_daily_draft(
            "agent-memory",
            [source],
            [claim],
            readings=readings,
            deep_read_sources=deep_read_sources,
            figures_by_source_url=figures,
        ),
    )
    return run_dir
