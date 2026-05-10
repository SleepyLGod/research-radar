from argparse import Namespace
from pathlib import Path

from research_radar import cli
from research_radar.analysis.deepseek import DeepSeekProvider
from research_radar.config import parse_config


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
        )
    )

    assert isinstance(captured["verifier"], DeepSeekProvider)
    assert captured["verifier_model"] == "deepseek-chat"
    assert captured["limit"] == 3
    assert isinstance(captured["deep_reader"], DeepSeekProvider)
    assert captured["deep_model"] == "deepseek-chat"
    assert captured["deep_limit"] == 1


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
