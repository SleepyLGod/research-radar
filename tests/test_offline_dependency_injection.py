"""Regression checks for external dependency injection without replacing the pipeline."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from research_radar.analysis.routing import TaskModelRoute
from research_radar.application.daily import DailyRunOptions, run_daily_application
from research_radar.config import parse_config
from research_radar.exceptions import ConfigError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def test_daily_handler_reads_final_claim_count_not_timing_metadata(tmp_path: Path) -> None:
    """Runtime stage metrics are not the pipeline's top-level report summary."""
    from research_radar.app_bridge.handlers import handle_run_daily
    from research_radar.models import ArticleDraft
    from research_radar.storage.files import write_json

    write_json(
        tmp_path / "article_draft.json",
        ArticleDraft(
            title="Report",
            topic_id="memory",
            digest="Digest",
            lede="Lede",
            sections=[],
            metadata={"source_count": 1, "deep_read_count": 1},
        ),
    )
    write_json(tmp_path / "summary.json", {"publishable_claim_count": 6})
    write_json(
        tmp_path / "runtime_summary.json",
        {
            "stages": [{"stage": "verifier", "publishable_claim_count": 6}],
        },
    )
    payload = SimpleNamespace(
        topic_id="memory",
        limit=1,
        deep_limit=1,
        language="en",
        model_cache=False,
        model_cache_limit_bytes=None,
        report_date="2026-09-19",
    )
    result = handle_run_daily(
        SimpleNamespace(payload=payload),
        config=SimpleNamespace(workspace_root=tmp_path, research=object()),
        secrets=object(),
        events=object(),
        pdf_helper_path=Path("/usr/bin/true"),
        daily_runner=lambda *args, **kwargs: tmp_path,
    )
    assert result["deep_read_count"] == 1
    assert result["publishable_claim_count"] == 6


def test_daily_accepts_external_dependencies_and_runs_real_pipeline(tmp_path: Path) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    local = TaskModelRoute(provider=None, model=None, provider_name="local")
    run = run_daily_application(
        DailyRunOptions(root=tmp_path, topic_id="memory"),
        config,
        SecretManager(InMemorySecretBackend()),
        connectors=[],
        task_routes={
            task: local
            for task in (
                "source_gist",
                "deep_reading",
                "anchor_repair",
                "report_localization",
                "verifier",
            )
        },
    )
    assert (run / "article_draft.json").is_file()
    assert (run / "wechat.html").is_file()


def test_incomplete_injected_routes_never_fall_back_to_real_models(tmp_path: Path) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    with pytest.raises(ConfigError, match="every daily task"):
        run_daily_application(
            DailyRunOptions(root=tmp_path, topic_id="memory"),
            config,
            SecretManager(InMemorySecretBackend()),
            connectors=[],
            task_routes={},
        )
    assert not (tmp_path / "runs").exists()
