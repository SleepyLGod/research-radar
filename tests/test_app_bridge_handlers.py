from types import SimpleNamespace

from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.routing import TaskModelRoute
from research_radar.app_bridge import handlers
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


class _Provider:
    name = "deepseek"

    def complete(self, messages, *, model):
        return ModelResponse(
            content="ResearchRadar provider probe ok.",
            model=model,
            metadata={"provider": self.name},
        )


def test_configured_route_checks_call_shared_provider_probe(monkeypatch) -> None:
    route = SimpleNamespace(provider="deepseek", model="deepseek-v4-flash")
    research = SimpleNamespace(
        models=SimpleNamespace(
            task_routes={"anchor_repair": route, "deep_reading": route}
        )
    )
    config = SimpleNamespace(research=research)
    resolved = TaskModelRoute(
        provider=_Provider(),
        model="deepseek-v4-flash",
        provider_name="deepseek",
    )
    calls: list[str] = []
    monkeypatch.setattr(handlers, "resolve_task_route", lambda *args: resolved)
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
            "model": "deepseek-v4-flash",
        },
        {
            "id": "deep_reading",
            "status": "ready",
            "message": "Provider route is ready.",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
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
