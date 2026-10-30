"""Manual organization bridge checks with only offline model and secret boundaries."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.routing import TaskModelRoute
from research_radar.app_bridge import handlers
from research_radar.app_bridge.events import EventWriter
from research_radar.app_bridge.protocol import load_request
from research_radar.app_bridge.runner import BridgeDependencies, run_bridge


def setup_request(root: Path, command: str = "organize_topic") -> tuple[Path, SimpleNamespace]:
    root.mkdir(mode=0o700, exist_ok=True)
    workspace = root / "workspace"
    run = workspace / "runs" / "offline"
    run.mkdir(parents=True, exist_ok=True)
    report_id = str(uuid4())
    url = "https://arxiv.org/abs/2601.01234v1"
    (run / "article_draft.json").write_text(
        json.dumps(
            {
                "topic_id": "memory",
                "sections": [
                    {
                        "metadata": {
                            "kind": "deep_reads",
                            "deep_reads": [
                                {
                                    "title": "Memory study",
                                    "source": {"url": url, "version": "v1"},
                                    "claims": [
                                        {
                                            "text": "The method selects relevant memories.",
                                            "evidence": [
                                                {
                                                    "source_url": url,
                                                    "quote": "We select memories.",
                                                    "location": "Section 3",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ],
            }
        )
    )
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700, exist_ok=True)
    job = jobs / str(uuid4())
    job.mkdir(mode=0o700)
    config_path = root / "config.json"
    config_path.write_text("{}")
    payload = {"topic_id": "memory"}
    if command == "organize_topic":
        payload.update(research_question="How is memory selected?", language="zh")
        payload["reports"] = [
            {"report_id": report_id, "report_date": "2026-10-28", "run_dir": str(run)}
        ]
    (job / "request.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": job.name,
                "command": command,
                "created_at": "2026-10-28T09:00:00Z",
                "app_support_root": str(root),
                "config_path": str(config_path),
                "payload": payload,
            }
        )
    )
    topic = SimpleNamespace(
        id="memory", description="How is memory selected?", report_language="zh"
    )
    return job, SimpleNamespace(workspace_root=workspace, research=SimpleNamespace(topics=[topic]))


class OfflineModel:
    name = "offline"

    def complete(self, messages, *, model):
        materials = json.loads(messages[1].content)
        assert materials["language"] == "zh"
        assert materials["research_question"] == "How is memory selected?"
        return ModelResponse(
            json.dumps(
                {
                    "facets": [],
                    "groups": [],
                    "relations": [],
                    "synthesis": [],
                    "open_questions": [],
                    "papers": [
                        {
                            "paper_key": paper["paper_key"],
                            "keywords": [],
                            "features": [
                                {
                                    "name": "Mechanism",
                                    "value": "Memory selection",
                                    "basis": "source_statement",
                                    "ref_ids": paper["ref_ids"],
                                    "missing_reason": None,
                                }
                            ],
                        }
                        for paper in materials["papers"]
                    ],
                }
            ),
            model,
        )


def test_manual_handler_uses_saved_topic_and_reader_route_and_read_never_resolves_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, config = setup_request(tmp_path)
    requested = []

    def resolve(config, secrets, task, **kwargs):
        requested.append(task)
        return TaskModelRoute(OfflineModel(), "offline-model", "offline")

    monkeypatch.setattr(handlers, "resolve_task_route", resolve)
    result = handlers.handle_organize_topic(
        load_request(job / "request.json", job_dir=job),
        config=config,
        secrets=object(),
        events=EventWriter(job / "events.jsonl", request_id=job.name),
        pdf_helper_path=None,
    )
    assert requested == ["deep_reading"]
    assert result["topic_id"] == "memory"
    assert result["current"]["paper_count"] == 1
    assert result["current"]["feature_count"] == 1
    assert "snapshot_path" not in result["current"]
    read_job, _ = setup_request(tmp_path, "read_topic_knowledge")
    requested.clear()
    loaded = handlers.handle_read_topic_knowledge(
        load_request(read_job / "request.json", job_dir=read_job),
        config=config,
        secrets=None,
        events=EventWriter(read_job / "events.jsonl", request_id=read_job.name),
        pdf_helper_path=None,
    )
    assert loaded == result and requested == []


def test_read_dispatch_does_not_even_construct_a_secret_manager(tmp_path: Path) -> None:
    job, config = setup_request(tmp_path, "read_topic_knowledge")

    def forbidden():
        raise AssertionError("A saved snapshot read must not access credentials")

    deps = replace(
        BridgeDependencies.testing(),
        config_loader=lambda *_: config,
        read_topic_knowledge=handlers.handle_read_topic_knowledge,
        secret_manager_factory=forbidden,
    )
    assert (
        run_bridge(
            request_path=job / "request.json",
            events_path=job / "events.jsonl",
            result_path=job / "result.json",
            error_path=job / "error.json",
            dependencies=deps,
            establish_session=False,
            watch_parent=False,
        )
        == 0
    )
    assert json.loads((job / "result.json").read_text())["knowledge"] == {
        "topic_id": "memory",
        "current": None,
    }


def test_saved_relation_read_reaches_wire_without_secret_or_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job, config = setup_request(tmp_path)
    run = config.workspace_root / "runs" / "offline"
    draft_path = run / "article_draft.json"
    draft = json.loads(draft_path.read_text())
    readings = draft["sections"][0]["metadata"]["deep_reads"]
    readings.append({
        "title": "Offline paper B: Memory validity",
        "source": {"url": "https://arxiv.org/abs/2601.09876v2", "version": "v2"},
        "claims": [{"text": "Offline claim B about validity.", "evidence": [{
            "source_url": "https://arxiv.org/abs/2601.09876v2",
            "quote": "Offline source quote B, not a research result.",
            "location": "Offline section B",
        }]}],
    })
    readings[0]["title"] = "离线论文 A: Task utility"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False))

    class OfflineRelationModel(OfflineModel):
        def complete(self, messages, *, model):
            materials = json.loads(messages[1].content)
            response = super().complete(messages, model=model)
            value = json.loads(response.content)
            a, b = materials["papers"]
            value["relations"] = [{
                "source": a["paper_key"], "target": b["paper_key"],
                "kind": kind, "basis": "synthesis",
                "reason": "离线关系验收样例，不是模型研究结论。 " + kind,
                "ref_ids": [*a["ref_ids"], *b["ref_ids"]],
            } for kind in (
                "shared_problem", "related_mechanism", "different_assumption", "shared_evaluation"
            )]
            return ModelResponse(json.dumps(value), model)

    monkeypatch.setattr(handlers, "resolve_task_route", lambda *_a, **_k: TaskModelRoute(
        OfflineRelationModel(), "offline-model", "offline"))
    handlers.handle_organize_topic(
        load_request(job / "request.json", job_dir=job), config=config, secrets=None,
        events=EventWriter(job / "events.jsonl", request_id=job.name), pdf_helper_path=None,
    )
    snapshots = {
        path: path.read_bytes() for path in config.workspace_root.glob("knowledge/**/*.json")
    }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Saved relation read must not resolve credentials or call a model")

    monkeypatch.setattr(handlers, "resolve_task_route", forbidden)
    read_job, _ = setup_request(tmp_path, "read_topic_knowledge")
    # Restore saved input bytes after setup_request creates an independent read request.
    draft_path.write_text(json.dumps(draft, ensure_ascii=False))
    draft_before_read = draft_path.read_bytes()
    deps = replace(BridgeDependencies.testing(), config_loader=lambda *_: config,
        read_topic_knowledge=handlers.handle_read_topic_knowledge, secret_manager_factory=forbidden)
    assert run_bridge(request_path=read_job / "request.json", events_path=read_job / "events.jsonl",
        result_path=read_job / "result.json", error_path=read_job / "error.json",
        dependencies=deps, establish_session=False, watch_parent=False) == 0
    result = json.loads((read_job / "result.json").read_text())
    assert len(result["knowledge"]["graph"]["relations"]) == 4
    assert len(result["knowledge"]["graph"]["papers"]) == 2
    assert {path: path.read_bytes() for path in snapshots} == snapshots
    assert draft_path.read_bytes() == draft_before_read
    if output := os.environ.get("RESEARCH_RADAR_RELATION_QA_OUTPUT"):
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / "knowledge-wire.json").write_bytes((read_job / "result.json").read_bytes())
        (target / "article_draft.json").write_bytes(draft_path.read_bytes())


@pytest.mark.parametrize(
    "change", [{"api_key": "not-allowed"}, {"reports": "wrong"}, {"unknown": True}]
)
def test_organize_protocol_rejects_unknown_or_secret_fields(tmp_path: Path, change: dict) -> None:
    job, _ = setup_request(tmp_path)
    path = job / "request.json"
    value = json.loads(path.read_text())
    value["payload"].update(change)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_request(path, job_dir=job)


def test_python_projection_matches_shared_swift_fixture() -> None:
    from research_radar.app_bridge.knowledge_projection import knowledge_summary
    fixture = Path(__file__).parents[1] / (
        "apps/macos/ResearchRadar/Tests/Fixtures/Protocol/topic-knowledge-result.json"
    )
    expected = json.loads(fixture.read_text())["knowledge"]
    current = expected["current"]
    snapshot = {
        "snapshot_id": current["snapshot_id"],
        "created_at": current["created_at"],
        "input_fingerprint": current["input_fingerprint"],
        "provider": "offline",
        "model": "offline-model",
        "inputs": {"reports": [{"report_id": current["report_ids"][0]}]},
        "organization": {
            "papers": [{"features": [1, 2]}, {"features": [3, 4]}],
            "groups": [1],
            "relations": [1],
        },
    }
    assert knowledge_summary(snapshot) == expected["current"]


def test_full_bridge_success_can_be_read_again_without_a_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, config = setup_request(tmp_path)
    calls = []

    def resolve(*args, **kwargs):
        calls.append("model")
        return TaskModelRoute(OfflineModel(), "offline-model", "offline")

    monkeypatch.setattr(handlers, "resolve_task_route", resolve)
    deps = replace(
        BridgeDependencies.testing(),
        config_loader=lambda *_: config,
        organize_topic=handlers.handle_organize_topic,
        read_topic_knowledge=handlers.handle_read_topic_knowledge,
    )
    paths = dict(
        request_path=job / "request.json",
        events_path=job / "events.jsonl",
        result_path=job / "result.json",
        error_path=job / "error.json",
    )
    assert run_bridge(**paths, dependencies=deps, establish_session=False, watch_parent=False) == 0
    saved = json.loads((job / "result.json").read_text())["knowledge"]
    assert saved["current"]["provider"] == "offline"
    assert calls == ["model"]
    assert json.loads((job / "events.jsonl").read_text().splitlines()[1])["stage"] == "knowledge"
    read_job, _ = setup_request(tmp_path, "read_topic_knowledge")
    def no_credentials():
        raise AssertionError("Reading a saved graph must not construct a secret manager")

    assert (
        run_bridge(
            request_path=read_job / "request.json",
            events_path=read_job / "events.jsonl",
            result_path=read_job / "result.json",
            error_path=read_job / "error.json",
            dependencies=replace(deps, secret_manager_factory=no_credentials),
            establish_session=False,
            watch_parent=False,
        )
        == 0
    )
    assert json.loads((read_job / "result.json").read_text())["knowledge"] == saved
    assert calls == ["model"]


def test_cancel_before_commit_retains_prior_current_and_does_not_resolve_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, config = setup_request(tmp_path)
    monkeypatch.setattr(
        handlers,
        "resolve_task_route",
        lambda *args, **kwargs: TaskModelRoute(OfflineModel(), "offline-model", "offline"),
    )
    request = load_request(job / "request.json", job_dir=job)
    kwargs = dict(
        config=config,
        secrets=object(),
        events=EventWriter(job / "events.jsonl", request_id=job.name),
        pdf_helper_path=None,
    )
    old = handlers.handle_organize_topic(request, **kwargs)
    cancelled = Event()

    class CancellingModel(OfflineModel):
        def complete(self, *args, **kwargs):
            result = super().complete(*args, **kwargs)
            cancelled.set()
            return result

    monkeypatch.setattr(
        handlers,
        "resolve_task_route",
        lambda *args, **kwargs: TaskModelRoute(CancellingModel(), "offline-model", "offline"),
    )
    from research_radar.exceptions import OperationCancelled

    with pytest.raises(OperationCancelled):
        handlers.handle_organize_topic(request, **kwargs, cancellation_event=cancelled)
    read_job, _ = setup_request(tmp_path, "read_topic_knowledge")
    current = handlers.handle_read_topic_knowledge(
        load_request(read_job / "request.json", job_dir=read_job), **kwargs
    )
    assert current == old
