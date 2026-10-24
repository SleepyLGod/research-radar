import json
import shlex
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from research_radar.app_bridge.runner import BridgeDependencies, run_bridge


def test_codex_failure_keeps_terminal_reason_across_pipeline_and_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from research_radar.analysis.cli_providers import CodexCliProvider
    from research_radar.analysis.providers import Message
    from research_radar.app_bridge.handlers import _progress_listener
    from research_radar.exceptions import AnalysisError
    from research_radar.pipeline.progress import ProgressWriter

    request, events, result, error, root = _job(
        tmp_path, command="run_daily", payload={
            "topic_id": "llm-inference", "report_date": "2026-08-30",
            "limit": 5, "deep_limit": 2, "language": "zh", "model_cache": True,
            "model_cache_limit_bytes": None,
        },
    )

    def command_failed(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            19, command,
            stderr="startup\n" + command[-1] + "\n" + "chatter\n" * 1000
            + "token=offline-private-canary\nERROR: OFFLINE_TERMINAL_REASON",
        )

    monkeypatch.setattr(subprocess, "run", command_failed)

    def fail(*args: object, **kwargs: object) -> None:
        progress = ProgressWriter(
            root / "progress.jsonl", listener=_progress_listener(kwargs["events"]),
        )
        progress.record("verifier", "started")
        provider = CodexCliProvider(name="codex", command=shlex.quote(sys.executable))
        try:
            provider.complete(
                [Message(role="user", content="PRIVATE_READING_PACKET " * 1000)], model="offline",
            )
        except AnalysisError as exc:
            progress.record("verifier", "failed", error=str(exc))
            raise

    dependencies = replace(
        BridgeDependencies.testing(), run_daily=fail,
        clock=lambda: datetime(2026, 8, 30, 10, tzinfo=UTC),
    )
    assert run_bridge(request_path=request, events_path=events, result_path=result,
                      error_path=error, establish_session=False, watch_parent=False,
                      dependencies=dependencies) == 1
    terminal = json.loads(error.read_text())
    stream = [json.loads(line) for line in events.read_text().splitlines()]
    progress = [json.loads(line) for line in (root / "progress.jsonl").read_text().splitlines()]
    assert terminal["code"] == "research_failed" and terminal["stage"] == "verifier"
    assert "exit 19" in terminal["message"] and "OFFLINE_TERMINAL_REASON" in terminal["message"]
    assert len(terminal["message"]) <= 500
    assert terminal["message"] == stream[-1]["message"] == stream[-1]["error"]["message"]
    assert terminal["message"] == progress[-1]["error"]
    for artifact in (error, events, root / "progress.jsonl"):
        assert "PRIVATE_READING_PACKET" not in artifact.read_text()
        assert "offline-private-canary" not in artifact.read_text()
    assert not result.exists()


@pytest.mark.parametrize("length", [100, 500, 501, 2000])
def test_failure_message_is_bounded_and_consistent_with_events(tmp_path: Path, length: int) -> None:
    from research_radar.app_bridge.runner import BridgeExecutionError

    request, events, result, error, _ = _job(
        tmp_path, command="preflight", payload={"live_probe": False},
    )

    def fail(*args, **kwargs):
        raise BridgeExecutionError(
            code="provider_unavailable", stage="preflight", retryable=True,
            message="token=offline-private-canary " + "x" * length,
        )

    dependencies = replace(BridgeDependencies.testing(), preflight=fail)
    assert run_bridge(request_path=request, events_path=events, result_path=result,
                      error_path=error, establish_session=False, watch_parent=False,
                      dependencies=dependencies) == 1
    terminal = json.loads(error.read_text())
    event = json.loads(events.read_text().splitlines()[-1])
    assert terminal["code"] == "provider_unavailable"
    assert terminal["stage"] == "preflight" and terminal["retryable"] is True
    assert 0 < len(terminal["message"]) <= 500
    assert terminal["message"] == event["message"] == event["error"]["message"]
    assert "offline-private-canary" not in error.read_text() + events.read_text()
    assert not result.exists()


def test_codex_configuration_error_matches_swift_fixture(tmp_path: Path) -> None:
    from research_radar.app_bridge.runner import BridgeExecutionError

    fixture = json.loads(Path(
        "apps/macos/ResearchRadar/Tests/Fixtures/Protocol/codex-configuration-error.json"
    ).read_text())
    request, events, result, error, _ = _job(
        tmp_path, command="preflight", payload={"live_probe": False},
    )

    def fail(*args, **kwargs):
        raise BridgeExecutionError(
            code="codex_not_configured", stage="preflight",
            message="Configure an available Codex executable in Settings before research.",
        )

    dependencies = replace(BridgeDependencies.testing(), preflight=fail,
                           clock=lambda: datetime(2026, 8, 30, 10, tzinfo=UTC))
    assert run_bridge(request_path=request, events_path=events, result_path=result,
                      error_path=error, establish_session=False, watch_parent=False,
                      dependencies=dependencies) == 1
    assert json.loads(error.read_text()) == {
        **fixture, "request_id": request.parent.name,
    }


def test_transport_failure_keeps_actual_source_gist_stage(tmp_path: Path) -> None:
    from research_radar.app_bridge.handlers import _progress_listener
    from research_radar.exceptions import ProviderTransportError

    request, events, result, error, _ = _job(
        tmp_path, command="run_daily", payload={
            "topic_id": "llm-inference", "report_date": "2026-08-30",
            "limit": 5, "deep_limit": 2, "language": "zh", "model_cache": True,
            "model_cache_limit_bytes": None,
        },
    )

    def fail(*args, **kwargs):
        _progress_listener(kwargs["events"])({"stage": "source_gist", "status": "started"})
        raise ProviderTransportError("Incomplete response", {"attempt_count": 2, "retryable": True})

    dependencies = replace(
        BridgeDependencies.testing(), run_daily=fail,
        clock=lambda: datetime(2026, 8, 30, 10, tzinfo=UTC),
    )
    assert run_bridge(request_path=request, events_path=events, result_path=result,
                      error_path=error, establish_session=False, watch_parent=False,
                      dependencies=dependencies) == 1
    terminal = json.loads(error.read_text())
    stream = [json.loads(line) for line in events.read_text().splitlines()]
    assert terminal["stage"] == stream[-1]["stage"] == "source_gist"
    assert terminal["code"] == "model_response_retry_exhausted"
    assert stream[-2]["stage"] == "source_gist"


def test_cooperative_provider_cancel_is_a_cancelled_terminal(tmp_path: Path) -> None:
    from research_radar.exceptions import OperationCancelled

    request, events, result, error, _ = _job(
        tmp_path, command="preflight", payload={"live_probe": False},
    )

    def cancel(*args, **kwargs):
        kwargs["cancellation_event"].set()
        raise OperationCancelled()

    dependencies = replace(BridgeDependencies.testing(), preflight=cancel)
    assert run_bridge(request_path=request, events_path=events, result_path=result,
                      error_path=error, establish_session=False, watch_parent=False,
                      dependencies=dependencies) == 130
    assert json.loads(error.read_text())["code"] == "cancelled"
    assert not result.exists()


def _job(
    tmp_path: Path,
    *,
    command: str,
    payload: dict[str, object],
) -> tuple[Path, Path, Path, Path, Path]:
    root = tmp_path / "ResearchRadar"
    root.mkdir(mode=0o700)
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700)
    job = jobs / str(uuid4())
    job.mkdir(mode=0o700)
    config = root / "config.json"
    config.write_text("{}", encoding="utf-8")
    request = job / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": job.name,
                "command": command,
                "created_at": "2026-08-30T10:00:00Z",
                "app_support_root": str(root),
                "config_path": str(config),
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    return request, job / "events.jsonl", job / "result.json", job / "error.json", root


def test_runner_dispatches_only_selected_handler(tmp_path: Path) -> None:
    request, events, result, error, _ = _job(
        tmp_path,
        command="bootstrap_topic",
        payload={"description": "LLM inference", "language": "zh"},
    )
    calls: list[str] = []

    def selected(*args, **kwargs):
        calls.append("bootstrap_topic")
        return {
            "id": "llm-inference",
            "display_name": "LLM Inference",
            "research_focus": "LLM inference",
            "queries": ["LLM inference"],
            "paper_queries": ["LLM serving benchmark"],
            "web_queries": [],
            "exclusion_terms": [],
            "required_phrases": [],
            "concept_groups": {},
            "negative_phrases": [],
            "priority_sources": [],
            "source_intent": "research_brief",
            "report_language": "zh",
            "warnings": [],
        }

    def unexpected(*args, **kwargs):
        raise AssertionError("wrong handler called")

    dependencies = BridgeDependencies(
        preflight=unexpected,
        bootstrap_topic=selected,
        run_daily=unexpected,
        retry_delivery=unexpected,
        upload_wechat_cover=unexpected,
        clock=lambda: datetime(2026, 8, 30, 10, tzinfo=UTC),
        config_loader=lambda path, require_topics: object(),
        secret_manager_factory=lambda: object(),
    )

    exit_code = run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        establish_session=False,
        watch_parent=False,
        dependencies=dependencies,
    )

    assert exit_code == 0
    assert calls == ["bootstrap_topic"]
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["command"] == "bootstrap_topic"
    assert payload["topic_draft"]["id"] == "llm-inference"
    assert payload["preflight"] is None
    assert payload["report"] is None
    assert payload["delivery"] is None


def test_runner_rejects_historical_daily_before_handler(tmp_path: Path) -> None:
    request, events, result, error, _ = _job(
        tmp_path,
        command="run_daily",
        payload={
            "topic_id": "llm-inference",
            "report_date": "2026-08-29",
            "limit": 5,
            "deep_limit": 2,
            "language": "zh",
            "model_cache": True,
            "model_cache_limit_bytes": None,
        },
    )

    dependencies = replace(
        BridgeDependencies.testing(),
        run_daily=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("daily handler should not run")
        ),
        clock=lambda: datetime(2026, 8, 30, 10, tzinfo=UTC),
        config_loader=lambda path, require_topics: object(),
        secret_manager_factory=lambda: object(),
    )

    exit_code = run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        establish_session=False,
        watch_parent=False,
        dependencies=dependencies,
    )

    assert exit_code == 2
    assert not result.exists()
    payload = json.loads(error.read_text(encoding="utf-8"))
    assert payload["code"] == "invalid_report_date"
    assert payload["stage"] == "discovery"


def test_runner_owns_delivery_completion_timestamp(tmp_path: Path) -> None:
    request, events, result, error, _ = _job(
        tmp_path,
        command="retry_delivery",
        payload={
            "run_dir": str(tmp_path / "placeholder"),
            "channel": "email",
            "allow_resend": False,
            "acknowledge_unknown_outcome": False,
        },
    )
    # Replace the placeholder with a contained run path after _job creates the root.
    app_root = request.parent.parent.parent
    run_dir = app_root / "workspace" / "runs" / "report"
    run_dir.mkdir(parents=True)
    raw = json.loads(request.read_text(encoding="utf-8"))
    raw["payload"]["run_dir"] = str(run_dir)
    request.write_text(json.dumps(raw), encoding="utf-8")
    completed_at = datetime(2026, 8, 30, 11, 30, tzinfo=UTC)
    dependencies = replace(
        BridgeDependencies.testing(),
        retry_delivery=lambda *args, **kwargs: {
            "run_dir": str(run_dir),
            "channel": "email",
            "status": "sent",
            "completed_at": "2000-01-01T00:00:00Z",
        },
        clock=lambda: completed_at,
        config_loader=lambda path, require_topics: object(),
        secret_manager_factory=lambda: object(),
    )

    exit_code = run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        establish_session=False,
        watch_parent=False,
        dependencies=dependencies,
    )

    assert exit_code == 0
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["completed_at"] == "2026-08-30T11:30:00Z"
    assert payload["delivery"]["completed_at"] == payload["completed_at"]
