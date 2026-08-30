from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.routing import TaskModelRoute
from research_radar.application.provider_probe import load_probe_json, probe_provider


class _Provider:
    name = "example"

    def complete(self, messages, *, model):
        assert messages[0].role == "user"
        return ModelResponse(
            content='```json\n{"status":"ok"}\n```',
            model=model,
            metadata={"provider": self.name},
        )


def test_probe_provider_returns_typed_redacted_result() -> None:
    ticks = iter([10.0, 10.25])
    result = probe_provider(
        TaskModelRoute(
            provider=_Provider(),
            model="example-model",
            provider_name="example",
        ),
        probe="json",
        timer=lambda: next(ticks),
    )

    assert result.provider == "example"
    assert result.model == "example-model"
    assert result.duration_seconds == 0.25
    assert result.json_valid is True
    assert result.response_char_count > 0


def test_probe_json_ignores_trailing_model_commentary() -> None:
    assert load_probe_json('{"status":"ok"}\nThis is the requested object.') == {
        "status": "ok"
    }
