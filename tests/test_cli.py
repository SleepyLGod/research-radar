from argparse import Namespace
from pathlib import Path

from research_radar import cli
from research_radar.analysis.cli_providers import CodexCliProvider
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.openai_compatible import OpenAICompatibleProvider
from research_radar.compose.draft import build_daily_draft
from research_radar.config import parse_config
from research_radar.exceptions import PublishError
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
    assert captured["verifier_model"] == "deepseek-chat"
    assert captured["limit"] == 3
    assert isinstance(captured["deep_reader"], OpenAICompatibleProvider)
    assert captured["deep_reader"].name == "deepseek"
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
            model="deepseek-chat",
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
    assert captured["deep_model"] == "deepseek-chat"
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
    html = (run_dir / "wechat.html").read_text(encoding="utf-8")
    assert "Prepared WeChat draft dry run" in output
    assert result["status"] == "dry_run"
    assert result["draft_created"] is False
    assert request["draft_only"] is True
    assert request["auto_publish"] is False
    assert "Verified claim for WeChat draft." in html
    assert "stale unverified html" not in html


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


def _write_publishable_article_draft(tmp_path: Path) -> Path:
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
    write_json(run_dir / "article_draft.json", build_daily_draft("agent-memory", [source], [claim]))
    return run_dir
