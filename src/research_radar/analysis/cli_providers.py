"""Command-backed model providers."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import AnalysisError


class CodexCliProvider:
    """Provider backed by `codex exec` in read-only ephemeral mode."""

    def __init__(self, *, name: str, command: str, timeout_seconds: int = 120) -> None:
        self.name = name
        self.command = command
        self._timeout_seconds = timeout_seconds

    def health_check(self) -> None:
        """Fail if the configured command cannot be executed."""

        _resolve_command(self.command)

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Run `codex exec` and return its last message."""

        self.health_check()
        prompt = messages_to_prompt(messages)
        with tempfile.TemporaryDirectory(prefix="research-radar-codex-") as tmpdir:
            output_path = Path(tmpdir) / "last-message.txt"
            command = [
                *_command_parts(self.command),
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
                "-m",
                model,
                prompt,
            ]
            _run_command(command, self.name, timeout_seconds=self._timeout_seconds)
            if not output_path.exists():
                raise AnalysisError(f"{self.name} did not write an output message.")
            content = output_path.read_text(encoding="utf-8").strip()
        if not content:
            raise AnalysisError(f"{self.name} returned an empty response.")
        return ModelResponse(content=content, model=model, metadata={"provider": self.name})


class ClaudeCodeCliProvider:
    """Provider backed by Claude Code compatible print mode."""

    def __init__(self, *, name: str, command: str, timeout_seconds: int = 120) -> None:
        self.name = name
        self.command = command
        self._timeout_seconds = timeout_seconds

    def health_check(self) -> None:
        """Fail if the configured command cannot be executed."""

        _resolve_command(self.command)

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Run Claude Code print mode and return stdout."""

        self.health_check()
        command = _claude_command(self.command, model, messages_to_prompt(messages))
        result = _run_command(command, self.name, timeout_seconds=self._timeout_seconds)
        content = result.stdout.strip()
        if not content:
            raise AnalysisError(f"{self.name} returned an empty response.")
        return ModelResponse(content=content, model=model, metadata={"provider": self.name})


def messages_to_prompt(messages: list[Message]) -> str:
    """Render chat messages into a CLI-safe prompt."""

    parts = []
    for message in messages:
        role = message.role.upper()
        parts.append(f"{role}:\n{message.content}")
    return "\n\n".join(parts)


def _claude_command(command: str, model: str, prompt: str) -> list[str]:
    parts = _command_parts(command)
    if "-p" not in parts and "--print" not in parts:
        parts.append("-p")
    parts.extend(
        [
            "--output-format",
            "text",
            "--no-session-persistence",
            "--tools",
            "",
            "--model",
            model,
            prompt,
        ]
    )
    return parts


def _command_parts(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        raise AnalysisError("Provider command cannot be empty.")
    return parts


def _resolve_command(command: str) -> str:
    executable = _command_parts(command)[0]
    if Path(executable).is_absolute():
        if not Path(executable).exists():
            raise AnalysisError(f"Provider command not found: {executable}")
        return executable
    resolved = shutil.which(executable)
    if resolved is None:
        raise AnalysisError(f"Provider command not found on PATH: {executable}")
    return resolved


def _run_command(
    command: list[str],
    provider_name: str,
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise AnalysisError(f"{provider_name} command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError(f"{provider_name} command timed out.") from exc
    except subprocess.CalledProcessError as exc:
        detail_text = exc.stderr.strip() or exc.stdout.strip()
        detail = f": {detail_text}" if detail_text else ""
        raise AnalysisError(f"{provider_name} command failed{detail}") from exc
