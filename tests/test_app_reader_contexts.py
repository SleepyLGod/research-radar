"""App-owned declarations reach shared providers without guessed capacities."""

from pathlib import Path

import pytest
from test_app_bridge_configuration import _app_config, _write_config

from research_radar.analysis.reader_input import ReaderContextBudget
from research_radar.analysis.routing import build_provider
from research_radar.app_bridge.configuration import AppConfigurationError, load_app_configuration
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


@pytest.mark.parametrize("task", ["deep_reading", "verifier"])
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("wrong_model", [False, True])
def test_preflight_rejects_missing_exact_model_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: str, live: bool, wrong_model: bool,
) -> None:
    from types import SimpleNamespace

    from research_radar.app_bridge import handlers, runner

    value = _app_config(tmp_path)
    limits = {"context_window_tokens": 200000, "output_reserve_tokens": 10000,
              "overhead_reserve_tokens": 5000}
    for route in value["routes"]:
        provider = next(p for p in value["providers"] if p["id"] == route["provider_id"])
        provider["reader_contexts"] = {route["model"]: limits}
        if route["task"] == task:
            provider["reader_contexts"] = {"another-model": limits} if wrong_model else {}
    value["discovery"]["web_search_provider"] = None
    loaded = load_app_configuration(_write_config(tmp_path, value), require_topics=False)
    probes: list[str] = []
    monkeypatch.setattr(runner, "dependency_report", lambda: {"offline": {"available": True}})
    monkeypatch.setattr(
        handlers, "probe_provider", lambda route, **kwargs: probes.append(route.model),
    )

    result = handlers.handle_preflight(
        SimpleNamespace(payload=SimpleNamespace(live_probe=live)), config=loaded,
        secrets=SecretManager(InMemorySecretBackend()), events=object(), pdf_helper_path=None,
    )

    assert result["ready"] is False
    check = next(item for item in result["checks"] if item["id"] == task)
    assert check["status"] == "action_required"
    assert "reader_context_unknown" in check["message"]
    assert check["model"] not in probes
    if not live:
        assert probes == []


@pytest.mark.parametrize("live", [False, True])
def test_preflight_local_routes_need_no_reader_budget_or_provider_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: bool,
) -> None:
    from types import SimpleNamespace

    from research_radar.app_bridge import handlers, runner

    value = _app_config(tmp_path)
    value["providers"] = [{"id": "local", "kind": "local", "timeout_seconds": 120}]
    for route in value["routes"]:
        route.update(provider_id="local", model="local")
    value["discovery"]["web_search_provider"] = None
    loaded = load_app_configuration(_write_config(tmp_path, value), require_topics=False)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Local preflight must not construct or probe a provider")

    monkeypatch.setattr(runner, "dependency_report", lambda: {"offline": {"available": True}})
    monkeypatch.setattr(handlers, "resolve_task_route", forbidden)
    monkeypatch.setattr(handlers, "probe_provider", forbidden)
    result = handlers.handle_preflight(
        SimpleNamespace(payload=SimpleNamespace(live_probe=live)), config=loaded,
        secrets=SecretManager(InMemorySecretBackend()), events=object(), pdf_helper_path=None,
    )
    assert result["ready"] is True
    assert loaded.research.model_providers["local"].reader_contexts == {}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_preflight_checks_independent_writer_only_for_chinese_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str,
) -> None:
    from types import SimpleNamespace

    from research_radar.app_bridge import handlers, runner

    value = _app_config(tmp_path, topics=[{
        "id": "memory", "display_name": "Memory", "research_focus": "Agent memory",
        "queries": ["agent memory"], "paper_queries": ["agent memory"],
        "report_language": language,
    }])
    reader = next(r for r in value["routes"] if r["task"] == "deep_reading")
    verifier = next(r for r in value["routes"] if r["task"] == "verifier")
    value["routes"].append({"task": "report_localization",
                            "provider_id": reader["provider_id"], "model": "independent-writer"})
    limits = {"context_window_tokens": 200000, "output_reserve_tokens": 10000,
              "overhead_reserve_tokens": 5000}
    for route in (reader, verifier):
        provider = next(p for p in value["providers"] if p["id"] == route["provider_id"])
        provider.setdefault("reader_contexts", {})[route["model"]] = limits
    loaded = load_app_configuration(_write_config(tmp_path, value), require_topics=False)
    monkeypatch.setattr(runner, "dependency_report", lambda: {"offline": {"available": True}})

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Local readiness must not probe providers or read secrets")

    monkeypatch.setattr(handlers, "resolve_task_route", forbidden)
    result = handlers.handle_preflight(
        SimpleNamespace(payload=SimpleNamespace(live_probe=False)), config=loaded,
        secrets=SecretManager(InMemorySecretBackend()), events=object(), pdf_helper_path=None,
    )
    assert result["ready"] is (language == "en")
    checks = [check for check in result["checks"] if check["id"] == "report_localization"]
    if language == "zh":
        assert len(checks) == 1 and checks[0]["status"] == "action_required"
    else:
        assert checks == []


def test_app_exact_model_budget_reaches_the_shared_provider(tmp_path: Path) -> None:
    value = _app_config(tmp_path)
    limits = {"context_window_tokens": 200000, "output_reserve_tokens": 10000,
              "overhead_reserve_tokens": 5000}
    value["providers"][0]["reader_contexts"] = {"offline-model": limits}
    loaded = load_app_configuration(_write_config(tmp_path, value), require_topics=False)
    provider = build_provider(loaded.research, SecretManager(InMemorySecretBackend()), "deepseek")
    assert provider.reader_contexts == {"offline-model": ReaderContextBudget(**limits)}
    assert "deepseek-flash" not in provider.reader_contexts


@pytest.mark.parametrize("value", [[], False, 42, "auto"])
def test_invalid_budget_container_is_not_silently_defaulted(tmp_path: Path, value: object) -> None:
    config = _app_config(tmp_path)
    config["providers"][0]["reader_contexts"] = value
    with pytest.raises(AppConfigurationError):
        load_app_configuration(_write_config(tmp_path, config), require_topics=False)


@pytest.mark.parametrize("budget", [
    {"context_window_tokens": True, "output_reserve_tokens": 1, "overhead_reserve_tokens": 1},
    {"context_window_tokens": 100, "output_reserve_tokens": 99, "overhead_reserve_tokens": 1},
    {"context_window_tokens": 100, "output_reserve_tokens": -1, "overhead_reserve_tokens": 1},
    {"context_window_tokens": 100, "output_reserve_tokens": 1},
    {"context_window_tokens": 100, "output_reserve_tokens": 1, "overhead_reserve_tokens": 1,
     "api_key": "not-permitted"},
])
def test_app_invalid_budget_is_rejected_without_provider_calls(
    tmp_path: Path, budget: object,
) -> None:
    value = _app_config(tmp_path)
    value["providers"][0]["reader_contexts"] = {"offline-model": budget}
    with pytest.raises(AppConfigurationError):
        load_app_configuration(_write_config(tmp_path, value), require_topics=False)
