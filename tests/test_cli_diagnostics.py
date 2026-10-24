"""Offline regressions for bounded command-provider failure diagnostics."""

import json
import shlex
import subprocess
import sys
import traceback
from pathlib import Path

import pytest

from research_radar.analysis.cli_providers import CodexCliProvider
from research_radar.analysis.providers import Message
from research_radar.app_bridge.events import safe_message
from research_radar.application.provider_probe import probe_excerpt
from research_radar.exceptions import AnalysisError
from research_radar.pipeline.progress import ProgressWriter


def _codex_failure(
    monkeypatch: pytest.MonkeyPatch, *, stderr: str = "", stdout: str = "",
) -> str:
    calls = []

    def fail(command: list[str], **kwargs: object) -> None:
        calls.append(command)

        def echo(output: str) -> str:
            return output.replace("<PROMPT>", command[-1]).replace(
                "<CRLF_PROMPT>", command[-1].replace("\n", "\r\n"),
            )

        raise subprocess.CalledProcessError(
            17, command, output=echo(stdout), stderr=echo(stderr),
        )

    monkeypatch.setattr(subprocess, "run", fail)
    provider = CodexCliProvider(name="codex", command=shlex.quote(sys.executable))
    private_prompt = "PRIVATE_READING_PACKET " * 1000
    with pytest.raises(AnalysisError) as caught:
        provider.complete(
            [Message(role="user", content=private_prompt)],
            model="offline-model",
        )
    assert len(calls) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert "PRIVATE_READING_PACKET" not in "".join(traceback.format_exception(caught.value))
    return str(caught.value)


def test_codex_failure_tail_survives_progress_and_wire_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    message = _codex_failure(
        monkeypatch,
        stderr="Reading input\nuser\n<PROMPT>\n" + "startup chatter\n" * 200
        + "ERROR: OFFLINE_TERMINAL_REASON",
    )
    writer = ProgressWriter(tmp_path / "progress.jsonl")
    writer.record("verifier", "failed", error=message)
    stored = json.loads(writer.path.read_text())["error"]

    assert "OFFLINE_TERMINAL_REASON" in stored
    assert "PRIVATE_READING_PACKET" not in message
    assert "exit 17" in message
    assert "[truncated]" in message
    assert 0 < len(message) <= 500
    assert stored == message == safe_message(message)
    assert probe_excerpt(message).endswith("OFFLINE_TERMINAL_REASON")


@pytest.mark.parametrize("failure", ["timeout", "missing"])
def test_codex_launch_errors_do_not_chain_raw_command_or_prompt(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    def fail(command: list[str], **kwargs: object) -> None:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        raise FileNotFoundError(2, "not found", command[0])

    monkeypatch.setattr(subprocess, "run", fail)
    provider = CodexCliProvider(name="codex", command=shlex.quote(sys.executable))
    private_prompt = "PRIVATE_READING_PACKET " * 1000
    with pytest.raises(AnalysisError) as caught:
        provider.complete(
            [Message(role="user", content=private_prompt)], model="offline",
        )

    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert "PRIVATE_READING_PACKET" not in "".join(traceback.format_exception(caught.value))


def test_codex_failure_redacts_both_streams_before_bounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "sk-" + "Q" * 1000
    local_path = "/" + "Users/offline/private-file"
    local_url = "http://" + "localhost" + ":12345"
    message = _codex_failure(
        monkeypatch,
        stderr=f"{token}\n<PROMPT>\n" + "progress\n" * 200 + f"token={token}",
        stdout=f"app_secret=offline-private-canary\n{local_path}\n{local_url}\n"
        "ERROR: OFFLINE_STDOUT_REASON",
    )
    for private in (token, "Q" * 20, "offline-private-canary", local_path, local_url,
                    "PRIVATE_READING_PACKET"):
        assert private not in message
    assert "OFFLINE_STDOUT_REASON" in message
    assert "stderr:" in message and "stdout:" in message
    assert len(message) <= 500


@pytest.mark.parametrize("stream", ["stderr", "stdout"])
def test_codex_failure_handles_empty_or_short_output(
    monkeypatch: pytest.MonkeyPatch, stream: str,
) -> None:
    message = _codex_failure(monkeypatch, **{stream: "OFFLINE_SHORT_REASON"})
    assert "OFFLINE_SHORT_REASON" in message
    assert "exit 17" in message
    assert "[truncated]" not in message
    assert len(message) <= 500


def test_codex_failure_with_no_output_still_records_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _codex_failure(monkeypatch)
    assert "exit 17" in message
    assert len(message) <= 500


def test_codex_failure_omits_full_path_with_spaces_from_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _codex_failure(
        monkeypatch, stderr="warning",
        stdout="cwd: /" + "Users/offline/Private Project/secret.txt\nERROR: OFFLINE_FINAL_REASON",
    )

    assert "Private" not in message and "Project/secret.txt" not in message
    assert "OFFLINE_FINAL_REASON" in message
    assert len(message) <= 500


@pytest.mark.parametrize("length", [1, 450, 500, 501, 20000])
def test_codex_failure_bounds_unicode_and_omits_crlf_prompt_echo(
    monkeypatch: pytest.MonkeyPatch, length: int,
) -> None:
    message = _codex_failure(
        monkeypatch, stderr="<CRLF_PROMPT>\r\n" + "诊断" * length + "\nOFFLINE_FINAL_REASON",
    )
    assert "PRIVATE_READING_PACKET" not in message
    assert "OFFLINE_FINAL_REASON" in message
    assert len(message) <= 500
