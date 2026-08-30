import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from research_radar.app_bridge.runner import BridgeDependencies, run_bridge


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
