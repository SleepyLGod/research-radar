import plistlib
from pathlib import Path

import pytest

from research_radar.exceptions import ConfigError
from research_radar.scheduler.local import (
    DailyDraftScheduleSpec,
    build_daily_draft_runner,
    build_launchd_plist,
    launchd_label,
    parse_daily_time,
    write_daily_draft_schedule,
)


def test_launchd_label_uses_research_radar_name() -> None:
    label = launchd_label("Agent Memory", "daily_monitor")

    assert label == "ai.research-radar.daily-monitor.agent-memory"
    assert "researchpress" not in label


def test_parse_daily_time_validates_hh_mm() -> None:
    assert parse_daily_time("09:30") == (9, 30)

    with pytest.raises(ConfigError):
        parse_daily_time("9:30")

    with pytest.raises(ConfigError):
        parse_daily_time("25:00")


def test_daily_draft_runner_runs_daily_before_wechat_draft(tmp_path: Path) -> None:
    uv_path = tmp_path / "bin" / "uv"
    spec = DailyDraftScheduleSpec(
        topic_id="agent-memory",
        hour=9,
        minute=30,
        config_path=tmp_path / "config.yaml",
        root=tmp_path / "runs-root",
        thumb_media_id="thumb-media-id",
        title="ResearchRadar 日报：agent-memory",
        digest="今日精选 agent-memory 相关论文精读。",
        project_dir=tmp_path,
        output_dir=tmp_path / "schedule",
        uv_path=uv_path,
        language="zh",
        model_cache=True,
        publish_dry_run=True,
    )

    runner = build_daily_draft_runner(spec)

    assert "research-radar run daily" in runner
    assert "research-radar publish wechat-draft" in runner
    assert str(uv_path.resolve()) in runner
    assert "RUN_OUTPUT=\"$(uv run " not in runner
    assert runner.index("research-radar run daily") < runner.index(
        "research-radar publish wechat-draft"
    )
    assert "ResearchRadar daily run failed; not creating WeChat draft." in runner
    assert "--run-dir-output" in runner
    assert "last_run_dir.txt" in runner
    assert "sed -n 's/^Created run:" not in runner
    assert "--secret-source keychain" in runner
    assert "--verifier-provider codex" in runner
    assert "--verifier-model gpt-5.5" in runner
    assert "--dry-run" in runner
    assert "auto-publish" not in runner
    assert "API_KEY" not in runner
    assert "appsecret" not in runner.casefold()
    assert "access_token" not in runner.casefold()


def test_daily_draft_runner_passes_route_overrides(tmp_path: Path) -> None:
    spec = DailyDraftScheduleSpec(
        topic_id="agent-memory",
        hour=9,
        minute=30,
        config_path=tmp_path / "config.yaml",
        root=tmp_path / "runs-root",
        thumb_media_id="thumb-media-id",
        title="ResearchRadar 日报：agent-memory",
        digest="今日精选 agent-memory 相关论文精读。",
        project_dir=tmp_path,
        output_dir=tmp_path / "schedule",
        uv_path=tmp_path / "bin" / "uv",
        deepseek_provider="xiaomi",
        reader_provider="deepseek",
        reader_model="deepseek-v4-pro",
        verifier_provider="deepseek",
        verifier_model="deepseek-chat",
        anchor_repair_provider="xiaomi",
        anchor_repair_model="mimo-v2.5-pro",
        localization_provider="deepseek",
        localization_model="deepseek-chat",
        gist_provider="xiaomi",
        gist_model="mimo-v2.5-pro",
    )

    runner = build_daily_draft_runner(spec)

    assert "--deepseek-provider xiaomi" in runner
    assert "--reader-provider deepseek" in runner
    assert "--reader-model deepseek-v4-pro" in runner
    assert "--verifier-provider deepseek" in runner
    assert "--verifier-model deepseek-chat" in runner
    assert "--anchor-repair-provider xiaomi" in runner
    assert "--anchor-repair-model mimo-v2.5-pro" in runner
    assert "--localization-provider deepseek" in runner
    assert "--localization-model deepseek-chat" in runner
    assert "--gist-provider xiaomi" in runner
    assert "--gist-model mimo-v2.5-pro" in runner


def test_launchd_plist_does_not_contain_secrets_or_run_command(tmp_path: Path) -> None:
    plist_text = build_launchd_plist(
        label="ai.research-radar.daily-draft.agent-memory",
        runner_path=tmp_path / "runner.sh",
        hour=9,
        minute=30,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        working_directory=tmp_path,
    )
    payload = plistlib.loads(plist_text.encode("utf-8"))

    assert payload["Label"] == "ai.research-radar.daily-draft.agent-memory"
    assert payload["StartCalendarInterval"] == {"Hour": 9, "Minute": 30}
    assert payload["ProgramArguments"] == [str((tmp_path / "runner.sh").resolve())]
    assert "research-radar run daily" not in plist_text
    assert "wechat-draft" not in plist_text
    assert "API_KEY" not in plist_text
    assert "appsecret" not in plist_text.casefold()
    assert "access_token" not in plist_text.casefold()


def test_write_daily_draft_schedule_creates_runner_and_plist(tmp_path: Path) -> None:
    uv_path = tmp_path / "bin" / "uv"
    spec = DailyDraftScheduleSpec(
        topic_id="agent-memory",
        hour=9,
        minute=30,
        config_path=tmp_path / "config.yaml",
        root=tmp_path / "runs-root",
        thumb_media_id="thumb-media-id",
        title="ResearchRadar 日报：agent-memory",
        digest="今日精选 agent-memory 相关论文精读。",
        project_dir=tmp_path,
        output_dir=tmp_path / "schedule",
        uv_path=uv_path,
    )

    artifacts = write_daily_draft_schedule(spec)

    assert artifacts.runner_path.exists()
    assert artifacts.plist_path.exists()
    assert artifacts.log_dir.exists()
    assert artifacts.runner_path.stat().st_mode & 0o777 == 0o700
