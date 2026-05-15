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

    assert isinstance(captured["verifier"], DeepSeekProvider)
    assert captured["verifier_model"] == "deepseek-chat"
    assert captured["limit"] == 3
    assert isinstance(captured["deep_reader"], DeepSeekProvider)
    assert captured["deep_model"] == "deepseek-chat"
    assert captured["deep_limit"] == 1
    assert captured["language"] == "zh"


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

    assert isinstance(captured["reader"], DeepSeekProvider)
    assert captured["url"] == "https://arxiv.org/pdf/2604.01707v1"
    assert captured["model"] == "deepseek-chat"
