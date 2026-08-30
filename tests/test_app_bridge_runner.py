import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from research_radar.app_bridge.runner import run_bridge


def _bridge_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    root = tmp_path / "ResearchRadar-Dev"
    root.mkdir(mode=0o700)
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700)
    job = jobs / str(uuid4())
    job.mkdir(mode=0o700)
    request = job / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": job.name,
                "command": "preflight",
                "created_at": "2026-08-30T10:00:00Z",
                "app_support_root": str(root),
                "config_path": None,
                "payload": {"live_probe": False},
            }
        ),
        encoding="utf-8",
    )
    return job, request, job / "events.jsonl", job / "result.json", job / "error.json"


def test_run_bridge_writes_dependency_preflight_result(tmp_path: Path) -> None:
    job, request, events, result, error = _bridge_paths(tmp_path)

    exit_code = run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        establish_session=False,
        watch_parent=False,
    )

    assert exit_code == 0
    assert result.exists()
    assert not error.exists()
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["request_id"] == job.name
    assert payload["status"] == "succeeded"
    dependencies = payload["preflight"]["dependencies"]
    assert set(dependencies) == {
        "cryptography",
        "keyring",
        "PIL",
        "pypdf",
        "yaml",
        "research_radar.app_bridge",
    }
    assert all(item["available"] for item in dependencies.values())
    assert dependencies["keyring"]["backend"]
    event_payloads = [
        json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()
    ]
    assert event_payloads[0]["kind"] == "started"
    assert event_payloads[-1]["kind"] == "completed"
    assert result.stat().st_mode & 0o777 == 0o600


def test_run_bridge_writes_only_error_for_invalid_request(tmp_path: Path) -> None:
    _, request, events, result, error = _bridge_paths(tmp_path)
    request.write_text("{}", encoding="utf-8")

    exit_code = run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        establish_session=False,
        watch_parent=False,
    )

    assert exit_code == 2
    assert error.exists()
    assert not result.exists()
    payload = json.loads(error.read_text(encoding="utf-8"))
    assert payload["code"] == "invalid_request"
    assert "/" + "Users/" not in payload["message"]


def test_run_bridge_refuses_existing_terminal_artifact(tmp_path: Path) -> None:
    _, request, events, result, error = _bridge_paths(tmp_path)
    result.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Terminal artifact already exists"):
        run_bridge(
            request_path=request,
            events_path=events,
            result_path=result,
            error_path=error,
            establish_session=False,
            watch_parent=False,
        )


def test_run_bridge_rejects_terminal_path_outside_job(tmp_path: Path) -> None:
    _, request, events, result, _ = _bridge_paths(tmp_path)

    with pytest.raises(RuntimeError, match="must stay within the job directory"):
        run_bridge(
            request_path=request,
            events_path=events,
            result_path=result,
            error_path=tmp_path / "outside-error.json",
            establish_session=False,
            watch_parent=False,
        )


def test_run_bridge_writes_process_identity_in_started_event(tmp_path: Path) -> None:
    _, request, events, result, error = _bridge_paths(tmp_path)

    exit_code = run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        establish_session=False,
        watch_parent=False,
    )

    assert exit_code == 0
    first = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
    assert first["kind"] == "started"
    assert first["process_id"] == os.getpid()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS kqueue")
def test_parent_loss_writes_error_and_leaves_no_engine_process(tmp_path: Path) -> None:
    _, request, events, result, error = _bridge_paths(tmp_path)
    child_pid_path = tmp_path / "engine.pid"
    fixture = Path("tests/fixtures/app_bridge_parent_fixture.py").resolve(strict=True)
    parent = subprocess.Popen(
        [
            sys.executable,
            str(fixture),
            "parent",
            str(child_pid_path),
            str(request),
            str(events),
            str(result),
            str(error),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_path(child_pid_path)
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        _wait_for_path(events)
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)
        _wait_for_path(error)
        _wait_for_process_exit(child_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)

    payload = json.loads(error.read_text(encoding="utf-8"))
    assert payload["code"] == "parent_lost"
    assert not result.exists()


def _wait_for_path(path: Path) -> None:
    for _ in range(200):
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {path.name}")


def _wait_for_process_exit(pid: int) -> None:
    for _ in range(200):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    raise AssertionError(f"Process {pid} remained alive after parent loss")
