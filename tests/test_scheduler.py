import fcntl
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

from research_radar.exceptions import ConfigError
from research_radar.scheduler import local as scheduler_local
from research_radar.scheduler.local import (
    DailyDraftScheduleSpec,
    build_daily_draft_runner,
    build_launchd_plist,
    execute_daily_draft_schedule,
    install_daily_draft_schedule,
    launchd_label,
    parse_daily_time,
    run_daily_draft_schedule_now,
    status_daily_draft_schedule,
    uninstall_daily_draft_schedule,
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

    assert "research-radar schedule execute" in runner
    assert str(uv_path.resolve()) in runner
    assert "schedule.json" in runner
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
        verifier_model="deepseek-v4-flash",
        anchor_repair_provider="xiaomi",
        anchor_repair_model="mimo-v2.5-pro",
        localization_provider="deepseek",
        localization_model="deepseek-v4-flash",
        gist_provider="xiaomi",
        gist_model="mimo-v2.5-pro",
    )

    artifacts = write_daily_draft_schedule(spec)
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    daily_command = " ".join(schedule["daily_command"])

    assert "--deepseek-provider xiaomi" in daily_command
    assert "--reader-provider deepseek" in daily_command
    assert "--reader-model deepseek-v4-pro" in daily_command
    assert "--verifier-provider deepseek" in daily_command
    assert "--verifier-model deepseek-v4-flash" in daily_command
    assert "--anchor-repair-provider xiaomi" in daily_command
    assert "--anchor-repair-model mimo-v2.5-pro" in daily_command
    assert "--localization-provider deepseek" in daily_command
    assert "--localization-model deepseek-v4-flash" in daily_command
    assert "--gist-provider xiaomi" in daily_command
    assert "--gist-model mimo-v2.5-pro" in daily_command


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
    assert artifacts.schedule_path.exists()
    assert artifacts.state_path.exists()
    assert artifacts.log_dir.exists()
    assert artifacts.runner_path.stat().st_mode & 0o777 == 0o700
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    assert schedule["label"] == artifacts.label
    assert "research-radar" in schedule["daily_command"]
    assert "run" in schedule["daily_command"]
    assert "daily" in schedule["daily_command"]
    assert "wechat-draft" in schedule["publish_command"]
    assert schedule["schema_version"] == 2
    assert schedule["daily_timeout_seconds"] == 21_600
    assert schedule["publish_timeout_seconds"] == 600
    serialized = json.dumps(schedule)
    assert "API_KEY" not in serialized
    assert "appsecret" not in serialized.casefold()
    assert "access_token" not in serialized.casefold()


def test_execute_schedule_runs_daily_then_publish_and_records_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "daily" in command:
            run_dir = tmp_path / "runs-root" / "runs" / "attempt"
            run_dir.mkdir(parents=True)
            (run_dir / "article_draft.json").write_text("{}", encoding="utf-8")
            Path(schedule["run_dir_output"]).write_text(
                str(run_dir), encoding="utf-8"
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(scheduler_local, "_run_command", fake_run)

    result = execute_daily_draft_schedule(artifacts.schedule_path)
    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))

    assert result["status"] == "succeeded"
    assert "daily" in calls[0]
    assert "wechat-draft" in calls[1]
    assert state["stage"] == "completed"
    assert state["wechat_draft_status"] == "created"
    assert state["last_success_at"]


def test_execute_schedule_daily_failure_does_not_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 3, stdout="", stderr="daily failed")

    monkeypatch.setattr(scheduler_local, "_run_command", fake_run)

    with pytest.raises(ConfigError, match="Daily run failed"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert state["status"] == "failed"
    assert state["stage"] == "daily"
    assert state["wechat_draft_status"] == "not_attempted"


def test_execute_schedule_records_daily_command_start_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))

    def fail_to_start(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        raise OSError("missing executable")

    monkeypatch.setattr(scheduler_local, "_run_command", fail_to_start)

    with pytest.raises(ConfigError, match="Daily run could not start"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["stage"] == "daily"
    assert state["wechat_draft_status"] == "not_attempted"


def test_execute_schedule_records_publish_command_start_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    calls = 0

    def fail_publish(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            run_dir = tmp_path / "runs-root" / "runs" / "attempt"
            run_dir.mkdir(parents=True)
            (run_dir / "article_draft.json").write_text("{}", encoding="utf-8")
            Path(schedule["run_dir_output"]).write_text(
                str(run_dir), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        raise OSError("missing publish executable")

    monkeypatch.setattr(scheduler_local, "_run_command", fail_publish)

    with pytest.raises(ConfigError, match="WeChat draft command could not start"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["stage"] == "wechat_draft"
    assert state["wechat_draft_status"] == "failed"


@pytest.mark.parametrize(
    "case",
    ["empty", "missing", "file", "outside_root", "missing_draft"],
)
def test_execute_schedule_rejects_unusable_run_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    calls = 0

    def fake_run(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        output_path = Path(schedule["run_dir_output"])
        if case == "missing":
            output_path.write_text(str(tmp_path / "runs-root" / "runs" / "missing"))
        elif case == "file":
            run_path = tmp_path / "runs-root" / "runs" / "not-a-directory"
            run_path.parent.mkdir(parents=True)
            run_path.write_text("not a run", encoding="utf-8")
            output_path.write_text(str(run_path), encoding="utf-8")
        elif case == "outside_root":
            run_path = tmp_path / "outside-run"
            run_path.mkdir()
            (run_path / "article_draft.json").write_text("{}", encoding="utf-8")
            output_path.write_text(str(run_path), encoding="utf-8")
        elif case == "missing_draft":
            run_path = tmp_path / "runs-root" / "runs" / "missing-draft"
            run_path.mkdir(parents=True)
            output_path.write_text(str(run_path), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(scheduler_local, "_run_command", fake_run)

    with pytest.raises(ConfigError, match="usable run directory"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
    assert calls == 1
    assert state["status"] == "failed"
    assert state["stage"] == "daily"
    assert state["run_dir"] is None
    assert state["wechat_draft_status"] == "not_attempted"


def test_execute_schedule_records_run_directory_read_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    run_dir_output = Path(schedule["run_dir_output"])
    original_read_text = Path.read_text

    def fake_run(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def fail_output_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == run_dir_output:
            raise OSError("fixture read failure")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(scheduler_local, "_run_command", fake_run)
    monkeypatch.setattr(Path, "read_text", fail_output_read)

    with pytest.raises(ConfigError, match="usable run directory"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(original_read_text(artifacts.state_path, encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["stage"] == "daily"


def test_execute_schedule_records_daily_timeout_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))

    def time_out(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    monkeypatch.setattr(scheduler_local, "_run_command", time_out)

    with pytest.raises(ConfigError, match="Daily run timed out after 21600 seconds"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["stage"] == "daily"
    assert state["wechat_draft_status"] == "not_attempted"

    with pytest.raises(ConfigError, match="Daily run timed out"):
        execute_daily_draft_schedule(artifacts.schedule_path)


def test_execute_schedule_records_publish_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    calls = 0

    def time_out_publish(
        command: list[str],
        schedule_payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            run_dir = tmp_path / "runs-root" / "runs" / "attempt"
            run_dir.mkdir(parents=True)
            (run_dir / "article_draft.json").write_text("{}", encoding="utf-8")
            Path(schedule["run_dir_output"]).write_text(str(run_dir), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    monkeypatch.setattr(scheduler_local, "_run_command", time_out_publish)

    with pytest.raises(ConfigError, match="WeChat draft timed out after 600 seconds"):
        execute_daily_draft_schedule(artifacts.schedule_path)

    state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["stage"] == "wechat_draft"
    assert state["wechat_draft_status"] == "failed"


def test_run_command_timeout_terminates_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    command = [
        "/bin/zsh",
        "-c",
        f"sleep 30 & echo $! > {child_pid_path}; wait",
    ]

    with pytest.raises(subprocess.TimeoutExpired):
        scheduler_local._run_command(
            command,
            {"project_dir": str(tmp_path)},
            timeout_seconds=1,
        )

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("watchdog left a child process running")


def test_run_command_streams_output_and_keeps_bounded_tail(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output = "x" * 1000

    result = scheduler_local._run_command(
        [sys.executable, "-c", f"print({output!r})"],
        {"project_dir": str(tmp_path)},
        timeout_seconds=10,
    )

    assert capsys.readouterr().out == f"{output}\n"
    assert result.stdout == f"{output}\n"[-scheduler_local.SCHEDULE_ERROR_LIMIT :]


def test_execute_schedule_rejects_old_snapshot_schema(tmp_path: Path) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    schedule = json.loads(artifacts.schedule_path.read_text(encoding="utf-8"))
    schedule["schema_version"] = 1
    artifacts.schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    with pytest.raises(ConfigError, match="Regenerate it with 'schedule daily-draft'"):
        execute_daily_draft_schedule(artifacts.schedule_path)


def test_execute_schedule_refuses_concurrent_run(tmp_path: Path) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    lock_path = artifacts.schedule_path.parent / "schedule.lock"
    lock_path.touch()
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ConfigError, match="already running"):
            execute_daily_draft_schedule(artifacts.schedule_path)


def test_schedule_lifecycle_uses_generated_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    launch_agents = tmp_path / "LaunchAgents"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="loaded", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    installed = install_daily_draft_schedule(
        tmp_path / "runs-root",
        "agent-memory",
        launch_agents_dir=launch_agents,
    )
    status = status_daily_draft_schedule(
        tmp_path / "runs-root",
        "agent-memory",
        launch_agents_dir=launch_agents,
    )
    monkeypatch.setattr(
        "research_radar.scheduler.local.execute_daily_draft_schedule",
        lambda path: {"status": "succeeded", "schedule": str(path)},
    )
    run_result = run_daily_draft_schedule_now(tmp_path / "runs-root", "agent-memory")
    uninstall_daily_draft_schedule(
        tmp_path / "runs-root",
        "agent-memory",
        launch_agents_dir=launch_agents,
    )

    assert installed == launch_agents / artifacts.plist_path.name
    assert status["installed"] is True
    assert status["loaded"] is True
    assert run_result["status"] == "succeeded"
    assert any("bootstrap" in command for command in calls)
    assert any("bootout" in command for command in calls)


def test_schedule_status_recovers_from_malformed_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    artifacts.state_path.write_text("{truncated", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="not loaded"
        ),
    )

    status = status_daily_draft_schedule(tmp_path / "runs-root", "agent-memory")

    assert status["state"]["status"] == "never_run"
    assert status["state"]["stage"] == "idle"


def test_schedule_install_reports_launchctl_start_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_daily_draft_schedule(_schedule_spec(tmp_path))

    def fail_launchctl(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise OSError("launchctl unavailable")

    monkeypatch.setattr(subprocess, "run", fail_launchctl)

    with pytest.raises(ConfigError, match="bootstrap could not complete"):
        install_daily_draft_schedule(
            tmp_path / "runs-root",
            "agent-memory",
            launch_agents_dir=tmp_path / "LaunchAgents",
        )


def test_schedule_uninstall_timeout_preserves_installed_plist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    installed = launch_agents / artifacts.plist_path.name
    installed.write_bytes(artifacts.plist_path.read_bytes())

    def time_out_launchctl(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == scheduler_local.LIFECYCLE_COMMAND_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(command, int(kwargs["timeout"]))

    monkeypatch.setattr(subprocess, "run", time_out_launchctl)

    with pytest.raises(ConfigError, match="bootout could not complete"):
        uninstall_daily_draft_schedule(
            tmp_path / "runs-root",
            "agent-memory",
            launch_agents_dir=launch_agents,
        )

    assert installed.exists()


def test_schedule_uninstall_does_not_delete_when_trash_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = write_daily_draft_schedule(_schedule_spec(tmp_path))
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    installed = launch_agents / artifacts.plist_path.name
    installed.write_bytes(artifacts.plist_path.read_bytes())

    def fail_trash(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "/usr/bin/trash":
            raise OSError("trash unavailable")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fail_trash)

    with pytest.raises(ConfigError, match="Could not move installed plist to Trash"):
        uninstall_daily_draft_schedule(
            tmp_path / "runs-root",
            "agent-memory",
            launch_agents_dir=launch_agents,
        )

    assert installed.exists()


def _schedule_spec(tmp_path: Path) -> DailyDraftScheduleSpec:
    return DailyDraftScheduleSpec(
        topic_id="agent-memory",
        hour=9,
        minute=30,
        config_path=tmp_path / "config.yaml",
        root=tmp_path / "runs-root",
        thumb_media_id="thumb-media-id",
        title="ResearchRadar 日报：agent-memory",
        digest="今日精选 agent-memory 相关论文精读。",
        project_dir=tmp_path,
        output_dir=tmp_path / "runs-root" / "schedules" / "daily-draft-agent-memory",
        uv_path=tmp_path / "bin" / "uv",
    )
