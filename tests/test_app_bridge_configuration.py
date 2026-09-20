import json
from pathlib import Path

import pytest

from research_radar.app_bridge.configuration import (
    AppConfigurationError,
    load_app_configuration,
)


@pytest.mark.parametrize("appearance", ["system", "light", "dark"])
def test_appearance_is_accepted_but_does_not_change_research(tmp_path, appearance) -> None:
    value = _app_config(tmp_path)
    path = _write_config(tmp_path, value)
    baseline = load_app_configuration(path, require_topics=False)
    value["ui_appearance"] = appearance
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_app_configuration(path, require_topics=False) == baseline


@pytest.mark.parametrize("appearance", [None, "automatic", 1, {}, []])
def test_invalid_appearance_is_rejected(tmp_path, appearance) -> None:
    value = _app_config(tmp_path)
    value["ui_appearance"] = appearance
    with pytest.raises(AppConfigurationError):
        load_app_configuration(_write_config(tmp_path, value), require_topics=False)


@pytest.mark.parametrize("command", [None, "/missing/codex", "codex", "/tmp"])
def test_daily_rejects_unavailable_codex_before_research(
    tmp_path: Path, command: str | None
) -> None:
    from research_radar.app_bridge.events import EventWriter
    from research_radar.app_bridge.handlers import handle_run_daily
    from research_radar.app_bridge.protocol import EngineRequestV1, RunDailyPayloadV1
    from research_radar.app_bridge.runner import BridgeExecutionError

    value = _app_config(tmp_path)
    value["providers"][1]["command_path"] = command
    config_path = _write_config(tmp_path, value)
    config = load_app_configuration(config_path, require_topics=False)

    def forbidden(*args: object, **kwargs: object) -> Path:
        pytest.fail("Research must not start with unavailable Codex")

    with pytest.raises(BridgeExecutionError) as caught:
        handle_run_daily(
            EngineRequestV1(
                1,
                "fixture",
                "run_daily",
                "2026-09-20T00:00:00Z",
                tmp_path,
                config_path,
                RunDailyPayloadV1("memory", "2026-09-20", 1, 1, "en", False, None),
            ),
            config=config,
            secrets=object(),
            events=EventWriter(tmp_path / "events.jsonl", request_id="fixture"),
            pdf_helper_path=Path("/usr/bin/true"),
            daily_runner=forbidden,
        )
    assert caught.value.code == "codex_not_configured"


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
            {"task": "deep_reading", "provider_id": "deepseek", "model": "deepseek-flash"},
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


def test_load_actual_swift_config_with_omitted_nil_fields(tmp_path: Path) -> None:
    # Captured from the native Codable encoder; only workspace_root is relocated.
    fixture = (
        Path(__file__).parent / "fixtures/offline_frozen/swift-app-config-omitted-optionals.json"
    )
    value = json.loads(fixture.read_text())
    value["workspace_root"] = str(tmp_path / "workspace")
    path = _write_config(tmp_path, value)
    omitted = load_app_configuration(path)
    value["discovery"].update(
        {
            "web_search_provider": None,
            "web_search_secret": None,
            "web_search_endpoint": None,
        }
    )
    value["storage"]["model_cache_limit_bytes"] = None
    path.write_text(json.dumps(value))
    assert load_app_configuration(path) == omitted
    assert omitted.research.topic("memory").report_language == "en"
    assert omitted.email_enabled and omitted.wechat.enabled


@pytest.mark.parametrize(
    "field",
    [
        "base_url",
        "api_key_secret",
        "command_path",
        "thinking",
        "reasoning_effort",
    ],
)
def test_provider_missing_optional_equals_explicit_null(tmp_path: Path, field: str) -> None:
    value = _app_config(tmp_path)
    value["providers"][0][field] = None
    path = _write_config(tmp_path, value)
    explicit = load_app_configuration(path, require_topics=False)
    del value["providers"][0][field]
    path.write_text(json.dumps(value))
    assert load_app_configuration(path, require_topics=False) == explicit


@pytest.mark.parametrize(
    "section,field",
    [
        ("root", "storage"),
        ("provider", "id"),
        ("provider", "kind"),
        ("provider", "timeout_seconds"),
        ("discovery", "trusted_domains"),
        ("discovery", "web_search_max_results"),
        ("discovery", "web_search_depth"),
        ("discovery", "web_search_timeout_seconds"),
        ("wechat", "author"),
        ("email", "smtp_host"),
    ],
)
def test_nullable_values_do_not_make_required_keys_optional(
    tmp_path: Path, section: str, field: str
) -> None:
    value = _app_config(tmp_path)
    target = {
        "root": value,
        "provider": value["providers"][0],
        "discovery": value["discovery"],
        "wechat": value["delivery"]["wechat"],
        "email": value["delivery"]["email"],
    }[section]
    del target[field]
    with pytest.raises(AppConfigurationError, match=f"missing {field}"):
        load_app_configuration(_write_config(tmp_path, value), require_topics=False)


@pytest.mark.parametrize("section", ["provider", "discovery", "storage"])
def test_optional_sections_still_reject_unknown_keys(tmp_path: Path, section: str) -> None:
    value = _app_config(tmp_path)
    target = value["providers"][0] if section == "provider" else value[section]
    target["unexpected"] = None
    with pytest.raises(AppConfigurationError, match="unknown unexpected"):
        load_app_configuration(_write_config(tmp_path, value), require_topics=False)
