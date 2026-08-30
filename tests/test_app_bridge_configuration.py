import json
from pathlib import Path

import pytest

from research_radar.app_bridge.configuration import (
    AppConfigurationError,
    load_app_configuration,
)


def _app_config(root: Path, *, topics: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "project_name": "ResearchRadar",
        "ui_language": "system",
        "workspace_root": str(root / "workspace"),
        "providers": [
            {
                "id": "deepseek",
                "kind": "openai_compatible",
                "base_url": "https://api.deepseek.com/chat/completions",
                "api_key_secret": "deepseek.api_key",
                "command_path": None,
                "timeout_seconds": 900,
                "thinking": "enabled",
                "reasoning_effort": "high",
            },
            {
                "id": "codex",
                "kind": "codex_cli",
                "base_url": None,
                "api_key_secret": None,
                "command_path": "/usr/bin/true",
                "timeout_seconds": 900,
                "thinking": None,
                "reasoning_effort": "high",
            },
        ],
        "routes": [
            {"task": "deep_reading", "provider_id": "deepseek", "model": "deepseek-v4-flash"},
            {"task": "verifier", "provider_id": "codex", "model": "gpt-5.6-terra"},
        ],
        "topics": topics or [],
        "discovery": {
            "trusted_domains": [],
            "web_search_provider": "tavily",
            "web_search_secret": "web_search.api_key",
            "web_search_endpoint": None,
            "web_search_max_results": 5,
            "web_search_depth": "advanced",
            "web_search_timeout_seconds": 30,
        },
        "delivery": {
            "wechat": {
                "enabled": False,
                "author": "ResearchRadar",
                "thumb_media_id": "",
                "app_id_secret": "wechat.app_id",
                "app_secret_secret": "wechat.app_secret",
            },
            "email": {
                "enabled": False,
                "smtp_host": "",
                "smtp_port": 465,
                "security": "tls",
                "username": "",
                "password_secret": "email.smtp_password",
                "from_address": "",
                "to_address": "",
                "timeout_seconds": 30,
            },
        },
        "storage": {"model_cache_limit_bytes": None},
        "start_at_login": False,
    }


def _write_config(root: Path, value: dict[str, object]) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(mode=0o700)
    path = config_dir / "app-config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_load_app_configuration_converts_to_existing_research_config(tmp_path: Path) -> None:
    root = tmp_path / "ResearchRadar"
    root.mkdir(mode=0o700)
    topic = {
        "id": "llm-inference",
        "queries": ["LLM inference systems"],
        "paper_queries": ["LLM serving benchmark"],
        "web_queries": [],
        "exclusion_terms": [],
        "required_phrases": ["inference"],
        "negative_phrases": ["prompt engineering"],
        "concept_groups": {"agent_context": ["LLM serving"]},
        "priority_sources": ["arxiv"],
        "source_intent": "research_brief",
        "report_language": "zh",
    }

    loaded = load_app_configuration(_write_config(root, _app_config(root, topics=[topic])))

    assert loaded.research.topic("llm-inference").report_language == "zh"
    assert loaded.research.model_providers["deepseek"].thinking == "enabled"
    assert loaded.research.models.task_routes["verifier"].model == "gpt-5.6-terra"
    assert loaded.research.security.secret_backend == "keychain"
    assert loaded.workspace_root == (root / "workspace").resolve()
    assert loaded.model_cache_limit_bytes is None
    assert loaded.wechat.enabled is False
    assert loaded.email_enabled is False


def test_load_app_configuration_allows_empty_topics_only_for_onboarding(tmp_path: Path) -> None:
    root = tmp_path / "ResearchRadar"
    root.mkdir(mode=0o700)
    path = _write_config(root, _app_config(root))

    with pytest.raises(AppConfigurationError, match="at least one topic"):
        load_app_configuration(path)

    loaded = load_app_configuration(path, require_topics=False)
    assert loaded.research.topics == []


def test_load_app_configuration_rejects_unknown_and_secret_value_fields(tmp_path: Path) -> None:
    root = tmp_path / "ResearchRadar"
    root.mkdir(mode=0o700)
    value = _app_config(root)
    value["api_key"] = "do-not-store"

    with pytest.raises(AppConfigurationError, match="Secret values"):
        load_app_configuration(_write_config(root, value), require_topics=False)


def test_load_app_configuration_rejects_workspace_outside_app_support(tmp_path: Path) -> None:
    root = tmp_path / "ResearchRadar"
    root.mkdir(mode=0o700)
    value = _app_config(root)
    value["workspace_root"] = str(tmp_path / "outside")

    with pytest.raises(AppConfigurationError, match="workspace_root"):
        load_app_configuration(_write_config(root, value), require_topics=False)


def test_load_app_configuration_rejects_app_support_as_workspace(tmp_path: Path) -> None:
    root = tmp_path / "ResearchRadar"
    root.mkdir(mode=0o700)
    value = _app_config(root)
    value["workspace_root"] = str(root)

    with pytest.raises(AppConfigurationError, match="inside App Support"):
        load_app_configuration(_write_config(root, value), require_topics=False)
