"""Local scheduler helpers."""

from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

from research_radar.exceptions import ConfigError
from research_radar.storage.files import write_text


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
    log_dir.mkdir(parents=True, exist_ok=True)
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
        log_dir=log_dir,
    )


def build_daily_draft_runner(spec: DailyDraftScheduleSpec) -> str:
    """Return a shell runner that creates a daily run and then a WeChat draft."""

    run_dir_file = spec.output_dir.resolve() / "last_run_dir.txt"
    uv_path = str(_resolve_uv_path(spec.uv_path))
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

    missing_run_dir_message = (
        "  echo 'ResearchRadar daily run did not write a run directory; "
        "not creating WeChat draft.' >&2"
    )

    return "\n".join(
        [
            "#!/bin/zsh",
            "set -euo pipefail",
            f"cd {_quote(spec.project_dir.resolve())}",
            f"RUN_DIR_FILE={_quote(run_dir_file)}",
            "rm -f \"$RUN_DIR_FILE\"",
            "",
            "set +e",
            "RUN_OUTPUT=\"$(" + _command(daily_command) + " 2>&1)\"",
            "RUN_STATUS=$?",
            "set -e",
            "printf '%s\\n' \"$RUN_OUTPUT\"",
            "if [[ \"$RUN_STATUS\" -ne 0 ]]; then",
            "  echo 'ResearchRadar daily run failed; not creating WeChat draft.' >&2",
            "  exit \"$RUN_STATUS\"",
            "fi",
            "if [[ ! -s \"$RUN_DIR_FILE\" ]]; then",
            missing_run_dir_message,
            "  exit 1",
            "fi",
            "RUN_DIR=\"$(cat \"$RUN_DIR_FILE\")\"",
            "if [[ -z \"$RUN_DIR\" ]]; then",
            missing_run_dir_message,
            "  exit 1",
            "fi",
            "",
            _command(publish_command),
            "",
        ]
    )


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
