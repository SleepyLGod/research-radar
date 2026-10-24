from types import SimpleNamespace

import pytest

from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.routing import TaskModelRoute
from research_radar.app_bridge import handlers
from research_radar.exceptions import ResearchRadarError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


class _Provider:
    name = "deepseek"

    def complete(self, messages, *, model):
        return ModelResponse(
            content="ResearchRadar provider probe ok.",
            model=model,
            metadata={"provider": self.name},
        )


def test_probe_failure_is_bounded_redacted_and_retains_diagnostic(monkeypatch) -> None:
    secret = "sk-" + "abcdefghijklmnopqrst"
    private_path = "/" + "Users/test/private.txt"
    route = SimpleNamespace(provider="codex", model="gpt-5.6-luna")
    config = SimpleNamespace(research=SimpleNamespace(
        models=SimpleNamespace(task_routes={"verifier": route})
    ))

    def fail(*args, **kwargs):
        raise ResearchRadarError(
            f"Transport failed {secret} {private_path} " + "x" * 900
        )

    monkeypatch.setattr(handlers, "resolve_task_route", fail)
    check = handlers._configured_route_checks(config, object())[0]
    assert check["status"] == "action_required"
    assert "Transport failed" in check["message"]
    assert "abcdefghijklmnopqrst" not in check["message"]
    assert private_path not in check["message"]
    assert len(check["message"]) <= 503


def test_configured_route_checks_call_shared_provider_probe(monkeypatch) -> None:
    route = SimpleNamespace(provider="deepseek", model="deepseek-flash")
    research = SimpleNamespace(
        models=SimpleNamespace(
            task_routes={"anchor_repair": route, "deep_reading": route}
        )
    )
    config = SimpleNamespace(research=research)
    resolved = TaskModelRoute(
        provider=_Provider(),
        model="deepseek-flash",
        provider_name="deepseek",
    )
    calls: list[str] = []
    monkeypatch.setattr(handlers, "resolve_task_route", lambda *args, **kwargs: resolved)
    monkeypatch.setattr(
        handlers,
        "probe_provider",
        lambda value, *, probe: calls.append(f"{value.provider_name}:{probe}"),
    )

    checks = handlers._configured_route_checks(config, object())

    assert calls == ["deepseek:small"]
    assert checks == [
        {
            "id": "anchor_repair",
            "status": "ready",
            "message": "Provider route is ready.",
            "provider": "deepseek",
            "model": "deepseek-flash",
        },
        {
            "id": "deep_reading",
            "status": "ready",
            "message": "Provider route is ready.",
            "provider": "deepseek",
            "model": "deepseek-flash",
        }
    ]


def test_wechat_secret_manager_maps_configured_secret_names() -> None:
    backend = InMemorySecretBackend()
    backend.set_secret("wx.id", "app-id")
    backend.set_secret("wx.secret", "app-secret")
    manager = SecretManager(backend)
    config = SimpleNamespace(
        wechat=SimpleNamespace(
            app_id_secret="wx.id",
            app_secret_secret="wx.secret",
        )
    )

    aliased = handlers._wechat_secret_manager(manager, config)

    assert aliased.get_wechat_app_id() == "app-id"
    assert aliased.get_wechat_app_secret() == "app-secret"
    aliased.backend.set_secret("storage.master_key", "master-key")
    assert backend.get_secret("storage.master_key") == "master-key"


def test_metadata_count_rejects_invalid_runtime_values() -> None:
    assert handlers._metadata_count({"count": None}, "count") == 0
    assert handlers._metadata_count({"count": "12"}, "count") == 0
    assert handlers._metadata_count({"count": [12]}, "count") == 0
    assert handlers._metadata_count({"count": True}, "count") == 0
    assert handlers._metadata_count({"count": 12}, "count") == 12


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("search_fails", [False, True])
def test_preflight_search_is_explicit_separate_and_affects_readiness(
    monkeypatch, live: bool, search_fails: bool,
) -> None:
    from research_radar.app_bridge import runner
    from research_radar.config import WebSearchConfig

    monkeypatch.setattr(runner, "dependency_report", lambda: {"fixture": {"available": True}})
    calls = []

    def probe(config, secrets, *, cancellation_event):
        calls.append(config)
        if search_fails:
            raise ResearchRadarError("Search unavailable " + "sk-" + "abcdefghijklmnopqrst")

    monkeypatch.setattr(handlers, "probe_web_search", probe)
    config = SimpleNamespace(research=SimpleNamespace(
        models=SimpleNamespace(task_routes={}),
        discovery=SimpleNamespace(web_search=WebSearchConfig(provider="tavily")),
    ))
    result = handlers.handle_preflight(
        SimpleNamespace(payload=SimpleNamespace(live_probe=live)), config=config,
        secrets=object(), events=object(), pdf_helper_path=None,
    )
    assert len(calls) == int(live)
    assert result["ready"] is (not live or not search_fails)
    if live:
        check = result["checks"][-1]
        assert check["id"] == "web_search"
        assert check["provider"] == "tavily"
        assert check["model"] is None
        assert check["status"] == ("action_required" if search_fails else "ready")
        assert "abcdefghijklmnopqrst" not in check["message"]
    else:
        assert len(result["checks"]) == 1


@pytest.mark.parametrize("provider", [None, "generic"])
def test_preflight_does_not_fail_unprobed_search_configurations(monkeypatch, provider) -> None:
    from research_radar.app_bridge import runner
    from research_radar.config import WebSearchConfig

    monkeypatch.setattr(runner, "dependency_report", lambda: {"fixture": {"available": True}})

    def forbidden(*args, **kwargs):
        pytest.fail("A Tavily probe must not run for another search configuration")

    monkeypatch.setattr(handlers, "probe_web_search", forbidden)
    config = SimpleNamespace(research=SimpleNamespace(
        models=SimpleNamespace(task_routes={}),
        discovery=SimpleNamespace(web_search=WebSearchConfig(provider=provider)),
    ))
    result = handlers.handle_preflight(
        SimpleNamespace(payload=SimpleNamespace(live_probe=True)), config=config,
        secrets=object(), events=object(), pdf_helper_path=None,
    )
    assert result["ready"] is True
    check = result["checks"][-1]
    assert check["id"] == "web_search"
    assert check["status"] == "optional"
    assert "not checked" in check["message"]
