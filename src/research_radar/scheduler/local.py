"""Local scheduler helpers."""

from __future__ import annotations

import fcntl
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from research_radar.exceptions import ConfigError
from research_radar.security.redaction import redact_text
from research_radar.storage.files import read_json, write_json, write_text

SCHEDULE_SCHEMA_VERSION = 2
SCHEDULE_ERROR_LIMIT = 500
DAILY_TIMEOUT_SECONDS = 21_600
PUBLISH_TIMEOUT_SECONDS = 600
TERMINATION_GRACE_SECONDS = 5
LIFECYCLE_COMMAND_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class DailyDraftScheduleSpec:
    """Inputs needed to create a local daily WeChat draft schedule."""

    topic_id: str
    hour: int
    minute: int
    config_path: Path
    root: Path
    thumb_media_id: str
    title: str
    digest: str
    project_dir: Path
    output_dir: Path
    uv_path: Path | None = None
    limit: int = 5
    deep_limit: int = 1
    language: str | None = None
    model_cache: bool = False
    publish_dry_run: bool = False
    deepseek_provider: str | None = None
    gist_provider: str | None = None
    gist_model: str | None = None
    reader_provider: str | None = None
    reader_model: str | None = None
    verifier_provider: str | None = "codex"
    verifier_model: str | None = "gpt-5.6-terra"
    anchor_repair_provider: str | None = None
    anchor_repair_model: str | None = None
    localization_provider: str | None = None
    localization_model: str | None = None


@dataclass(frozen=True)
class ScheduleArtifacts:
    """Paths written for a generated local schedule."""

    label: str
    runner_path: Path
    plist_path: Path
    schedule_path: Path
    state_path: Path
    log_dir: Path


def cron_line(command: str, *, minute: int, hour: int) -> str:
    """Return a cron line for a daily command."""

    return f"{minute} {hour} * * * {command}"


def launchd_label(topic_id: str, mode: str) -> str:
    """Return a stable launchd label."""

    return f"ai.research-radar.{_slug(mode)}.{_slug(topic_id)}"


def parse_daily_time(value: str) -> tuple[int, int]:
    """Parse an HH:MM daily wall-clock time."""

    if not re.fullmatch(r"\d{2}:\d{2}", value.strip()):
        raise ConfigError("--time must use HH:MM format.")
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ConfigError("--time must be a valid 24-hour HH:MM value.")
    return hour, minute


def write_daily_draft_schedule(spec: DailyDraftScheduleSpec) -> ScheduleArtifacts:
    """Write a launchd plist and runner script for a daily WeChat draft job."""

    label = launchd_label(spec.topic_id, "daily-draft")
    output_dir = spec.output_dir.resolve()
    log_dir = output_dir / "logs"
    runner_path = output_dir / f"{label}.sh"
    plist_path = output_dir / f"{label}.plist"
    schedule_path = output_dir / "schedule.json"
    state_path = output_dir / "schedule_state.json"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    write_json(schedule_path, _daily_draft_schedule_payload(spec, label=label))
    if not state_path.exists():
        write_json(state_path, _initial_schedule_state(label))
    write_text(runner_path, build_daily_draft_runner(spec))
    os.chmod(runner_path, 0o700)
    write_text(
        plist_path,
        build_launchd_plist(
            label=label,
            runner_path=runner_path,
            hour=spec.hour,
            minute=spec.minute,
            stdout_path=log_dir / "stdout.log",
            stderr_path=log_dir / "stderr.log",
            working_directory=spec.project_dir,
        ),
    )
    return ScheduleArtifacts(
        label=label,
        runner_path=runner_path,
        plist_path=plist_path,
        schedule_path=schedule_path,
        state_path=state_path,
        log_dir=log_dir,
    )


def build_daily_draft_runner(spec: DailyDraftScheduleSpec) -> str:
    """Return the shell entrypoint shared by launchd and manual execution."""

    uv_path = str(_resolve_uv_path(spec.uv_path))
    schedule_path = spec.output_dir.resolve() / "schedule.json"
    command = [
        uv_path,
        "run",
        "research-radar",
        "schedule",
        "execute",
        "--schedule",
        str(schedule_path),
    ]
    return "\n".join(
        [
            "#!/bin/zsh",
            "set -euo pipefail",
            f"cd {_quote(spec.project_dir.resolve())}",
            f"exec {_command(command)}",
            "",
        ]
    )


def execute_daily_draft_schedule(schedule_path: Path) -> dict[str, Any]:
    """Execute one generated daily schedule with locking and state audit."""

    schedule = _load_schedule(schedule_path)
    state_path = schedule_path.resolve().parent / "schedule_state.json"
    lock_path = schedule_path.resolve().parent / "schedule.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError(f"Schedule is already running: {schedule['label']}") from exc
        return _execute_locked_schedule(schedule, state_path)


def install_daily_draft_schedule(
    root: Path,
    topic_id: str,
    *,
    launch_agents_dir: Path | None = None,
) -> Path:
    """Install a generated plist into the current user's launchd domain."""

    artifacts = _existing_schedule_artifacts(root, topic_id)
    destination_dir = launch_agents_dir or Path.home() / "Library" / "LaunchAgents"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / artifacts.plist_path.name
    shutil.copy2(artifacts.plist_path, destination)
    try:
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)],
            capture_output=True,
            text=True,
            check=False,
            timeout=LIFECYCLE_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = redact_text(str(exc))[:SCHEDULE_ERROR_LIMIT]
        raise ConfigError(f"launchctl bootstrap could not complete: {detail}") from exc
    if result.returncode != 0:
        raise ConfigError(f"launchctl bootstrap failed: {_process_error(result)}")
    return destination


def status_daily_draft_schedule(
    root: Path,
    topic_id: str,
    *,
    launch_agents_dir: Path | None = None,
) -> dict[str, Any]:
    """Return generated, installed, loaded, and last-run schedule status."""

    artifacts = _existing_schedule_artifacts(root, topic_id)
    destination_dir = launch_agents_dir or Path.home() / "Library" / "LaunchAgents"
    installed_path = destination_dir / artifacts.plist_path.name
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{artifacts.label}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=LIFECYCLE_COMMAND_TIMEOUT_SECONDS,
        )
        loaded = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        loaded = False
    state = _read_schedule_state(artifacts.state_path, artifacts.label)
    return {
        "label": artifacts.label,
        "generated": True,
        "installed": installed_path.exists(),
        "loaded": loaded,
        "runner_path": str(artifacts.runner_path),
        "plist_path": str(artifacts.plist_path),
        "installed_plist_path": str(installed_path),
        "state": state,
    }


def run_daily_draft_schedule_now(root: Path, topic_id: str) -> dict[str, Any]:
    """Run the same generated schedule executor used by launchd."""

    artifacts = _existing_schedule_artifacts(root, topic_id)
    return execute_daily_draft_schedule(artifacts.schedule_path)


def uninstall_daily_draft_schedule(
    root: Path,
    topic_id: str,
    *,
    launch_agents_dir: Path | None = None,
) -> None:
    """Unload a schedule and move its installed plist to Trash."""

    artifacts = _existing_schedule_artifacts(root, topic_id)
    destination_dir = launch_agents_dir or Path.home() / "Library" / "LaunchAgents"
    installed_path = destination_dir / artifacts.plist_path.name
    try:
        result = subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(installed_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=LIFECYCLE_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = redact_text(str(exc))[:SCHEDULE_ERROR_LIMIT]
        raise ConfigError(f"launchctl bootout could not complete: {detail}") from exc
    if result.returncode != 0 and installed_path.exists():
        raise ConfigError(f"launchctl bootout failed: {_process_error(result)}")
    if installed_path.exists():
        try:
            trash_result = subprocess.run(
                ["/usr/bin/trash", str(installed_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=LIFECYCLE_COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            detail = redact_text(str(exc))[:SCHEDULE_ERROR_LIMIT]
            raise ConfigError(f"Could not move installed plist to Trash: {detail}") from exc
        if trash_result.returncode != 0:
            detail = _process_error(trash_result)
            raise ConfigError(f"Could not move installed plist to Trash: {detail}")


def build_launchd_plist(
    *,
    label: str,
    runner_path: Path,
    hour: int,
    minute: int,
    stdout_path: Path,
    stderr_path: Path,
    working_directory: Path,
) -> str:
    """Return a launchd plist for a generated runner script."""

    payload = {
        "Label": label,
        "ProgramArguments": [str(runner_path.resolve())],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(stdout_path.resolve()),
        "StandardErrorPath": str(stderr_path.resolve()),
        "WorkingDirectory": str(working_directory.resolve()),
        "RunAtLoad": False,
    }
    return plistlib.dumps(payload, sort_keys=True).decode("utf-8")


def _daily_draft_schedule_payload(
    spec: DailyDraftScheduleSpec,
    *,
    label: str,
) -> dict[str, Any]:
    uv_path = str(_resolve_uv_path(spec.uv_path))
    run_dir_file = spec.output_dir.resolve() / "last_run_dir.txt"
    daily_command = [
        uv_path,
        "run",
        "research-radar",
        "run",
        "daily",
        "--topic",
        spec.topic_id,
        "--config",
        str(spec.config_path.resolve()),
        "--root",
        str(spec.root.resolve()),
        "--limit",
        str(spec.limit),
        "--deep-limit",
        str(spec.deep_limit),
        "--secret-source",
        "keychain",
        "--run-dir-output",
        str(run_dir_file),
    ]
    if spec.language is not None:
        daily_command.extend(["--language", spec.language])
    if spec.model_cache:
        daily_command.append("--model-cache")
    _extend_optional_arg(daily_command, "--deepseek-provider", spec.deepseek_provider)
    _extend_optional_arg(daily_command, "--gist-provider", spec.gist_provider)
    _extend_optional_arg(daily_command, "--gist-model", spec.gist_model)
    _extend_optional_arg(daily_command, "--reader-provider", spec.reader_provider)
    _extend_optional_arg(daily_command, "--reader-model", spec.reader_model)
    _extend_optional_arg(daily_command, "--verifier-provider", spec.verifier_provider)
    _extend_optional_arg(daily_command, "--verifier-model", spec.verifier_model)
    _extend_optional_arg(daily_command, "--anchor-repair-provider", spec.anchor_repair_provider)
    _extend_optional_arg(daily_command, "--anchor-repair-model", spec.anchor_repair_model)
    _extend_optional_arg(daily_command, "--localization-provider", spec.localization_provider)
    _extend_optional_arg(daily_command, "--localization-model", spec.localization_model)

    publish_command = [
        uv_path,
        "run",
        "research-radar",
        "publish",
        "wechat-draft",
        "--run",
        "$RUN_DIR",
        "--title",
        spec.title,
        "--digest",
        spec.digest,
        "--thumb-media-id",
        spec.thumb_media_id,
    ]
    if spec.publish_dry_run:
        publish_command.append("--dry-run")
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "label": label,
        "topic_id": spec.topic_id,
        "project_dir": str(spec.project_dir.resolve()),
        "root": str(spec.root.resolve()),
        "run_dir_output": str(run_dir_file),
        "daily_command": daily_command,
        "publish_command": publish_command,
        "daily_timeout_seconds": DAILY_TIMEOUT_SECONDS,
        "publish_timeout_seconds": PUBLISH_TIMEOUT_SECONDS,
        "publish_dry_run": spec.publish_dry_run,
    }


def _load_schedule(schedule_path: Path) -> dict[str, Any]:
    if not schedule_path.is_file():
        raise ConfigError(f"Schedule metadata not found: {schedule_path}")
    payload = read_json(schedule_path)
    if not isinstance(payload, dict):
        raise ConfigError(f"Unsupported schedule metadata: {schedule_path}")
    if payload.get("schema_version") != SCHEDULE_SCHEMA_VERSION:
        raise ConfigError(
            "Schedule snapshot is outdated. Regenerate it with 'schedule daily-draft'."
        )
    for key in (
        "label",
        "project_dir",
        "root",
        "run_dir_output",
        "daily_command",
        "publish_command",
    ):
        if not payload.get(key):
            raise ConfigError(f"Schedule metadata is missing {key}: {schedule_path}")
    if not isinstance(payload["daily_command"], list) or not isinstance(
        payload["publish_command"], list
    ):
        raise ConfigError(f"Schedule commands are invalid: {schedule_path}")
    for key in ("daily_timeout_seconds", "publish_timeout_seconds"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"Schedule metadata has an invalid {key}: {schedule_path}")
    return payload


def _execute_locked_schedule(
    schedule: dict[str, Any],
    state_path: Path,
) -> dict[str, Any]:
    attempt_at = _utc_now()
    state = _read_schedule_state(state_path, str(schedule["label"]))
    run_dir_file = Path(str(schedule["run_dir_output"]))
    write_text(run_dir_file, "")
    _write_schedule_state(
        state_path,
        state,
        last_attempt_at=attempt_at,
        status="running",
        stage="daily",
        run_dir=None,
        wechat_draft_status="not_attempted",
        error=None,
    )

    daily_timeout = int(schedule["daily_timeout_seconds"])
    try:
        daily_result = _run_command(
            schedule["daily_command"],
            schedule,
            timeout_seconds=daily_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        error = f"Daily run timed out after {daily_timeout} seconds."
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="daily",
            run_dir=None,
            wechat_draft_status="not_attempted",
            error=error,
        )
        raise ConfigError(error) from exc
    except OSError as exc:
        error = redact_text(str(exc))[:SCHEDULE_ERROR_LIMIT]
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="daily",
            run_dir=None,
            wechat_draft_status="not_attempted",
            error=error,
        )
        raise ConfigError(f"Daily run could not start: {error}") from exc
    if daily_result.returncode != 0:
        error = _process_error(daily_result)
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="daily",
            run_dir=None,
            wechat_draft_status="not_attempted",
            error=error,
        )
        raise ConfigError(f"Daily run failed; WeChat draft was not created: {error}")

    try:
        run_dir = str(_validated_run_dir(schedule, run_dir_file))
    except ConfigError as exc:
        error = redact_text(str(exc))[:SCHEDULE_ERROR_LIMIT]
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="daily",
            run_dir=None,
            wechat_draft_status="not_attempted",
            error=error,
        )
        raise

    _write_schedule_state(
        state_path,
        state,
        last_attempt_at=attempt_at,
        status="running",
        stage="wechat_draft",
        run_dir=run_dir,
        wechat_draft_status="running",
        error=None,
    )
    publish_command = [
        run_dir if part == "$RUN_DIR" else str(part)
        for part in schedule["publish_command"]
    ]
    publish_timeout = int(schedule["publish_timeout_seconds"])
    try:
        publish_result = _run_command(
            publish_command,
            schedule,
            timeout_seconds=publish_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        error = f"WeChat draft timed out after {publish_timeout} seconds."
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="wechat_draft",
            run_dir=run_dir,
            wechat_draft_status="failed",
            error=error,
        )
        raise ConfigError(error) from exc
    except OSError as exc:
        error = redact_text(str(exc))[:SCHEDULE_ERROR_LIMIT]
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="wechat_draft",
            run_dir=run_dir,
            wechat_draft_status="failed",
            error=error,
        )
        raise ConfigError(f"WeChat draft command could not start: {error}") from exc
    if publish_result.returncode != 0:
        error = _process_error(publish_result)
        _write_schedule_state(
            state_path,
            state,
            last_attempt_at=attempt_at,
            status="failed",
            stage="wechat_draft",
            run_dir=run_dir,
            wechat_draft_status="failed",
            error=error,
        )
        raise ConfigError(f"WeChat draft creation failed: {error}")

    completed_at = _utc_now()
    draft_status = "dry_run" if schedule.get("publish_dry_run") else "created"
    result = _write_schedule_state(
        state_path,
        state,
        last_attempt_at=attempt_at,
        last_success_at=completed_at,
        status="succeeded",
        stage="completed",
        run_dir=run_dir,
        wechat_draft_status=draft_status,
        error=None,
    )
    return result


def _run_command(
    command: list[object],
    schedule: dict[str, Any],
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    args = [str(part) for part in command]
    process = subprocess.Popen(
        args,
        cwd=str(schedule["project_dir"]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_tail: deque[str] = deque()
    stderr_tail: deque[str] = deque()
    output_threads = (
        threading.Thread(
            target=_stream_process_output,
            args=(process.stdout, sys.stdout, stdout_tail),
            daemon=True,
        ),
        threading.Thread(
            target=_stream_process_output,
            args=(process.stderr, sys.stderr, stderr_tail),
            daemon=True,
        ),
    )
    for thread in output_threads:
        thread.start()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        for thread in output_threads:
            thread.join()
        raise subprocess.TimeoutExpired(
            args,
            timeout_seconds,
            output="".join(stdout_tail),
            stderr="".join(stderr_tail),
        ) from exc
    for thread in output_threads:
        thread.join()
    return subprocess.CompletedProcess(
        args=args,
        returncode=process.returncode,
        stdout="".join(stdout_tail),
        stderr="".join(stderr_tail),
    )


def _stream_process_output(
    stream: TextIO,
    destination: TextIO,
    tail: deque[str],
) -> None:
    try:
        for chunk in iter(stream.readline, ""):
            try:
                destination.write(chunk)
                destination.flush()
            except (OSError, ValueError):
                pass
            _append_output_tail(tail, chunk)
    finally:
        stream.close()


def _append_output_tail(tail: deque[str], chunk: str) -> None:
    tail.append(chunk)
    joined = "".join(tail)
    if len(joined) > SCHEDULE_ERROR_LIMIT:
        tail.clear()
        tail.append(joined[-SCHEDULE_ERROR_LIMIT:])


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _validated_run_dir(
    schedule: dict[str, Any],
    run_dir_file: Path,
) -> Path:
    error = "Daily run did not write a usable run directory."
    try:
        raw_run_dir = run_dir_file.read_text(encoding="utf-8").strip()
        if not raw_run_dir:
            raise ConfigError(error)
        run_dir = Path(raw_run_dir).resolve(strict=True)
        runs_root = (Path(str(schedule["root"])).resolve(strict=True) / "runs").resolve(
            strict=True
        )
    except ConfigError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ConfigError(error) from exc
    if not run_dir.is_dir() or runs_root not in run_dir.parents:
        raise ConfigError(error)
    if not (run_dir / "article_draft.json").is_file():
        raise ConfigError(error)
    return run_dir


def _initial_schedule_state(label: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "label": label,
        "status": "never_run",
        "stage": "idle",
        "last_attempt_at": None,
        "last_success_at": None,
        "run_dir": None,
        "wechat_draft_status": "not_attempted",
        "error": None,
    }


def _read_schedule_state(state_path: Path, label: str) -> dict[str, Any]:
    if not state_path.exists():
        return _initial_schedule_state(label)
    try:
        state = read_json(state_path)
    except (OSError, ValueError):
        return _initial_schedule_state(label)
    return state if isinstance(state, dict) else _initial_schedule_state(label)


def _write_schedule_state(
    state_path: Path,
    previous: dict[str, Any],
    **updates: Any,
) -> dict[str, Any]:
    state = {**previous, **updates}
    write_json(state_path, state)
    return state


def _process_error(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
    return redact_text(message)[:SCHEDULE_ERROR_LIMIT]


def _existing_schedule_artifacts(root: Path, topic_id: str) -> ScheduleArtifacts:
    label = launchd_label(topic_id, "daily-draft")
    output_dir = root.resolve() / "schedules" / f"daily-draft-{topic_id}"
    artifacts = ScheduleArtifacts(
        label=label,
        runner_path=output_dir / f"{label}.sh",
        plist_path=output_dir / f"{label}.plist",
        schedule_path=output_dir / "schedule.json",
        state_path=output_dir / "schedule_state.json",
        log_dir=output_dir / "logs",
    )
    for path in (artifacts.runner_path, artifacts.plist_path, artifacts.schedule_path):
        if not path.is_file():
            raise ConfigError(f"Generated schedule artifact not found: {path}")
    return artifacts


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", value.strip()).strip("-").lower()


def _command(parts: list[str]) -> str:
    return " ".join(_quote(part) if part != "$RUN_DIR" else '"$RUN_DIR"' for part in parts)


def _extend_optional_arg(parts: list[str], flag: str, value: str | None) -> None:
    if value is not None:
        parts.extend([flag, value])


def _quote(value: object) -> str:
    return shlex.quote(str(value))


def _resolve_uv_path(path: Path | None) -> Path:
    if path is not None:
        return path.resolve()
    resolved = shutil.which("uv")
    if resolved is None:
        raise ConfigError(
            "Could not find `uv` on PATH. Run schedule generation from an environment "
            "where `uv` is available."
        )
    return Path(resolved).resolve()
