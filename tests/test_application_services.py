"""Application-service contracts shared by the CLI and macOS bridge."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from research_radar.application.daily import DailyRunOptions, run_daily_application
from research_radar.application.email import EmailDeliveryOptions, publish_email_application
from research_radar.application.wechat import (
    WeChatDraftOptions,
    _draft_figures,
    _local_media_paths,
    article_draft_source_urls,
    publish_wechat_draft,
)
from research_radar.config import EmailPublishConfig, parse_config
from research_radar.exceptions import PublishError, ResearchRadarError
from research_radar.pipeline.progress import ProgressWriter
from research_radar.security.secrets import EnvSecretBackend, SecretManager
from research_radar.storage.files import read_json


def test_progress_writer_emits_the_same_redacted_event_to_listener(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    writer = ProgressWriter(tmp_path / "progress.jsonl", listener=events.append)

    writer.record("reading", "failed", error="token=secret-value")

    assert events == writer.events
    assert "secret-value" not in str(events)


def test_progress_listener_failure_does_not_interrupt_pipeline(tmp_path: Path) -> None:
    class ListenerFailure(Exception):
        pass

    def fail_listener(event: dict[str, object]) -> None:
        raise ListenerFailure("UI disconnected")

    writer = ProgressWriter(tmp_path / "progress.jsonl", listener=fail_listener)

    writer.record("reading", "started")

    assert writer.events[0]["stage"] == "reading"
    assert (tmp_path / "progress.jsonl").read_text(encoding="utf-8")


def test_daily_application_builds_routes_and_calls_pipeline(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    expected = tmp_path / "runs" / "result"
    captured: dict[str, object] = {}

    def fake_run_daily(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return expected

    result = run_daily_application(
        DailyRunOptions(
            root=tmp_path,
            topic_id="agent-memory",
            limit=5,
            deep_limit=0,
        ),
        config,
        SecretManager(EnvSecretBackend()),
        pipeline_runner=fake_run_daily,
    )

    assert result == expected
    assert captured["args"][:3] == (tmp_path, config, "agent-memory")
    assert captured["kwargs"]["limit"] == 5
    assert captured["kwargs"]["deep_limit"] == 0


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (DailyRunOptions(root=Path("."), topic_id="topic", limit=0), "limit must"),
        (
            DailyRunOptions(root=Path("."), topic_id="topic", deep_limit=-1),
            "deep_limit cannot",
        ),
    ],
)
def test_daily_application_validation_uses_service_field_names(
    options: DailyRunOptions,
    message: str,
) -> None:
    config = parse_config(
        {"project": {"name": "ResearchRadar"}, "topics": [{"id": "topic", "queries": ["q"]}]}
    )

    with pytest.raises(ResearchRadarError, match=message):
        run_daily_application(options, config, SecretManager(EnvSecretBackend()))


def test_wechat_media_rejects_paths_outside_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    draft = Namespace(
        sections=[
            Namespace(
                metadata={
                    "kind": "deep_reads",
                    "deep_reads": [{"figures": [{"relative_path": str(outside)}]}],
                }
            )
        ]
    )

    with pytest.raises(PublishError, match="escapes the run directory"):
        _local_media_paths(run_dir, draft)


def test_wechat_figure_metadata_ignores_invalid_deep_reads_type() -> None:
    draft = Namespace(
        sections=[Namespace(metadata={"kind": "deep_reads", "deep_reads": "invalid"})]
    )

    assert _draft_figures(draft) == []
    assert article_draft_source_urls(draft) == set()


def test_wechat_application_dry_run_uses_article_draft(tmp_path: Path) -> None:
    run_dir = _write_minimal_article_draft(tmp_path)

    result = publish_wechat_draft(
        WeChatDraftOptions(
            run_dir=run_dir,
            title="Daily title",
            digest="Digest",
            thumb_media_id="thumb123",
            dry_run=True,
        )
    )

    assert result["status"] == "dry_run"
    assert read_json(run_dir / "publish_wechat_draft.json")["draft_created"] is False
    assert (run_dir / "wechat_publish.html").exists()


def test_email_application_delegates_to_existing_publisher(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_publish(run_dir, settings, manager, **kwargs):
        captured.update(
            run_dir=run_dir,
            settings=settings,
            manager=manager,
            kwargs=kwargs,
        )
        return sentinel

    monkeypatch.setattr("research_radar.application.email.publish_email_run", fake_publish)
    settings = EmailPublishConfig()
    manager = SecretManager(EnvSecretBackend())

    result = publish_email_application(
        EmailDeliveryOptions(run_dir=tmp_path, dry_run=True),
        settings,
        manager,
    )

    assert result is sentinel
    assert captured["run_dir"] == tmp_path
    assert captured["kwargs"] == {"dry_run": True, "allow_resend": False}


def _write_minimal_article_draft(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "fixture"
    run_dir.mkdir(parents=True)
    (run_dir / "article_draft.json").write_text(
        """{
  "schema_version": 1,
  "run_id": "fixture",
  "topic_id": "agent-memory",
  "title": "Fixture report",
  "digest": "One verified report.",
  "lede": "One verified report.",
  "sections": [],
  "claims": [],
  "metadata": {}
}
""",
        encoding="utf-8",
    )
    return run_dir
