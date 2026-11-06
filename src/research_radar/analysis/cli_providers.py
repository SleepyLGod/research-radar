"""Command-backed model providers."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import AnalysisError
from research_radar.security.redaction import redact_text

_MAX_COMMAND_ERROR_CHARS = 500


class CodexCliProvider:
    """Provider backed by `codex exec` in read-only ephemeral mode."""

    supports_response_schema: bool = True

    def __init__(
        self,
        *,
        name: str,
        command: str,
        timeout_seconds: int = 120,
        reasoning_effort: str | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self._timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.cache_identity = (
            f"reasoning_effort={reasoning_effort}" if reasoning_effort is not None else ""
        )

    def health_check(self) -> None:
        """Fail if the configured command cannot be executed."""

        _codex_command_parts(self.command)

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Run `codex exec` and return its last message."""

        return self._complete(messages, model=model, response_schema=None)

    def complete_with_schema(
        self, messages: list[Message], *, model: str, response_schema: dict[str, object],
    ) -> ModelResponse:
        """Request a final-response shape for this call only, never a provider-wide mode."""

        return self._complete(messages, model=model, response_schema=response_schema)

    def _complete(
        self, messages: list[Message], *, model: str, response_schema: dict[str, object] | None,
    ) -> ModelResponse:

        parts = _codex_command_parts(self.command)
        prompt = messages_to_prompt(messages)
        schema_json = (json.dumps(response_schema, ensure_ascii=False,
                                 sort_keys=True, allow_nan=False)
                       if response_schema is not None else None)
        with tempfile.TemporaryDirectory(prefix="research-radar-codex-") as tmpdir:
            output_path = Path(tmpdir) / "last-message.txt"
            command = [
                *parts,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
                "-m",
                model,
            ]
            if self.reasoning_effort is not None:
                command.extend(
                    ["-c", f'model_reasoning_effort="{self.reasoning_effort}"']
                )
            if schema_json is not None:
                schema_path = Path(tmpdir) / "response-schema.json"
                with os.fdopen(os.open(schema_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                               "w", encoding="utf-8") as stream:
                    stream.write(schema_json)
                command.extend(["--output-schema", str(schema_path)])
            command.append("-")
            _run_command(
                command, self.name, timeout_seconds=self._timeout_seconds,
                prompt=prompt, stdin_text=prompt,
            )
            if not output_path.exists():
                raise AnalysisError(f"{self.name} did not write an output message.")
            content = output_path.read_text(encoding="utf-8").strip()
        if not content:
            raise AnalysisError(f"{self.name} returned an empty response.")
        if schema_json is not None:
            try:
                result = json.loads(content)
            except json.JSONDecodeError as exc:
                raise AnalysisError(
                    f"{self.name} constrained response was not complete JSON "
                    f"(line {exc.lineno}, column {exc.colno})."
                ) from None
            if not isinstance(result, dict):
                raise AnalysisError(f"{self.name} constrained JSON root must be an object.")
        return ModelResponse(
            content=content,
            model=model,
            metadata={
                "provider": self.name,
                "reasoning_effort": self.reasoning_effort or "inherited",
                **({"response_schema_requested": True, "response_schema_sha256":
                    hashlib.sha256(schema_json.encode()).hexdigest()}
                   if schema_json is not None else {}),
            },
        )


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


def _codex_command_parts(command: str) -> list[str]:
    """Resolve a standard npm launcher without widening the engine's PATH."""

    parts = _command_parts(command)
    executable = Path(_resolve_command(command))
    try:
        with executable.open("rb") as stream:
            shebang = stream.readline(128).strip()
    except OSError as exc:
        raise AnalysisError("Could not inspect the configured Codex executable.") from exc
    if shebang != b"#!/usr/bin/env node":
        return parts

    launcher = executable.resolve(strict=True)
    node = shutil.which("node")
    if node is None:
        # npm links may already be resolved by the App's native file picker.
        directories = [executable.parent, launcher.parent]
        for parent in launcher.parents:
            if parent.name == "node_modules" and parent.parent.name == "lib":
                directories.append(parent.parent.parent / "bin")
                break
        directories.extend([
            Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path.home() / ".local/bin",
        ])
        node = shutil.which("node", path=":".join(str(path) for path in directories))
    if node is None:
        raise AnalysisError(
            "The npm-installed Codex launcher requires Node.js. "
            "Use a matching Node installation or select a native Codex executable."
        )
    return [node, str(launcher), *parts[1:]]


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
    prompt: str | None = None,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=stdin_text,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        raise AnalysisError(
            redact_text(f"{provider_name} command not found: {command[0]}")
        ) from None
    except subprocess.TimeoutExpired:
        raise AnalysisError(
            redact_text(f"{provider_name} command timed out after {timeout_seconds} seconds.")
        ) from None
    except subprocess.CalledProcessError as exc:
        raise AnalysisError(_command_error_message(provider_name, exc, prompt=prompt)) from None


def _command_error_message(
    provider_name: str, error: subprocess.CalledProcessError, *, prompt: str | None,
) -> str:
    """Keep redacted exit diagnostics useful under downstream prefix limits."""
    header = f"{redact_text(provider_name)[:80]} command failed (exit {error.returncode})"
    echoed = prompt.replace("\r\n", "\n").strip() if prompt else None
    streams = []
    for name, output in (("stderr", error.stderr), ("stdout", error.stdout)):
        cleaned = (output or "").replace("\r\n", "\n")
        if echoed:
            cleaned = cleaned.replace(echoed, "[input omitted]")
        cleaned = redact_text(cleaned).strip()
        if cleaned:
            streams.append((name, cleaned))
    if not streams:
        return header
    budget = (
        _MAX_COMMAND_ERROR_CHARS - len(header) - sum(len(name) + 3 for name, _ in streams)
    ) // len(streams)
    parts = [header]
    for name, output in streams:
        if len(output) > budget:
            marker = "\n...[truncated]...\n"
            head = budget // 3
            tail = budget - head - len(marker)
            output = output[:head] + marker + output[-tail:]
        parts.append(f"\n{name}: {output}")
    return "".join(parts)
