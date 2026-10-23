"""App topic generation must honor routing and accept Chinese descriptions."""

import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from research_radar.analysis.providers import LLMProvider, Message, ModelResponse, StaticProvider
from research_radar.app_bridge.events import EventWriter
from research_radar.app_bridge.handlers import handle_bootstrap_topic
from research_radar.app_bridge.protocol import BootstrapTopicPayloadV1
from research_radar.config import AppConfig, parse_config
from research_radar.exceptions import AnalysisError, ConfigError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager
from research_radar.topic_bootstrap import bootstrap_topic_draft

PROFILE = {
    "id": "agent-memory",
    "queries": ["long term agent memory"],
    "paper_queries": ["agent memory benchmark"],
    "web_queries": ["agent memory repository"],
    "negative_phrases": ["hardware memory"],
    "concept_groups": {
        "agent_context": ["memory agent"],
        "memory_mechanism": ["long-term memory"],
        "evaluation_signal": ["memory benchmark"],
        "negative_compute_or_training": ["hardware memory"],
    },
    "priority_sources": ["arxiv.org"],
}


def test_model_topic_accepts_chinese_description_without_english_input_tokens() -> None:
    topic = bootstrap_topic_draft(
        "智能体长期记忆",
        language="zh",
        provider=StaticProvider(json.dumps(PROFILE)),
        model="offline-bootstrap",
    )
    assert topic.id == "agent-memory"
    assert topic.report_language == "zh"
    assert topic.queries == ["long term agent memory"]
    assert topic.concept_groups["agent_context"] == ["memory agent"]


@pytest.mark.parametrize("description", ["agent long-term memory", "智能体长期记忆"])
def test_app_bootstrap_uses_configured_provider_model_and_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    description: str,
) -> None:
    cancel = Event()
    manager = SecretManager(InMemorySecretBackend())
    config = SimpleNamespace(
        research=parse_config(
            {
                "topics": [],
                "model_providers": {"chosen": {"kind": "local"}},
                "models": {
                    "task_routes": {
                        "topic_bootstrap": {
                            "provider": "chosen",
                            "model": "chosen-bootstrap-model",
                        }
                    }
                },
            },
            require_topics=False,
        )
    )

    class OfflineModel:
        name = "chosen"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            assert model == "chosen-bootstrap-model"
            assert description in messages[-1].content
            return ModelResponse(json.dumps(PROFILE), model)

    def build(
        research: AppConfig,
        secrets: SecretManager,
        provider_name: str,
        *,
        cancellation_event: Event | None,
    ) -> LLMProvider:
        assert research is config.research and secrets is manager
        assert provider_name == "chosen" and cancellation_event is cancel
        return OfflineModel()

    monkeypatch.setattr("research_radar.analysis.routing.build_provider", build)
    result = handle_bootstrap_topic(
        SimpleNamespace(payload=BootstrapTopicPayloadV1(description, "zh")),
        config=config,
        secrets=manager,
        events=EventWriter(tmp_path / "events.jsonl", request_id="offline"),
        pdf_helper_path=None,
        cancellation_event=cancel,
    )
    assert result["id"] == "agent-memory"
    assert result["queries"] == ["long term agent memory"]
    assert result["paper_queries"] == ["agent memory benchmark"]
    assert result["research_focus"] == description
    assert result["report_language"] == "zh"


@pytest.mark.parametrize("failure", ["missing_route", "provider_error", "local"])
def test_app_bootstrap_does_not_silently_replace_configured_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    raw = (
        {}
        if failure == "missing_route"
        else {
            "model_providers": {"chosen": {"kind": "local"}},
            "models": {
                "task_routes": {
                    "topic_bootstrap": {
                        "provider": "local" if failure == "local" else "chosen",
                        "model": "offline",
                    }
                }
            },
        }
    )
    config = SimpleNamespace(research=parse_config({"topics": [], **raw}, require_topics=False))
    if failure == "provider_error":

        def failed(*args: object, **kwargs: object) -> LLMProvider:
            raise AnalysisError("Offline model unavailable")

        monkeypatch.setattr("research_radar.analysis.routing.build_provider", failed)
    arguments = dict(
        config=config,
        secrets=SecretManager(InMemorySecretBackend()),
        events=EventWriter(tmp_path / "events.jsonl", request_id="offline"),
        pdf_helper_path=None,
    )
    request = SimpleNamespace(payload=BootstrapTopicPayloadV1("agent memory", "en"))
    if failure == "local":
        result = handle_bootstrap_topic(request, **arguments)
        assert result["id"] == "agent-memory"
    else:
        with pytest.raises(ConfigError if failure == "missing_route" else AnalysisError):
            handle_bootstrap_topic(request, **arguments)
