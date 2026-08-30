#!/usr/bin/env python3
"""Measure the staged Task 1 App without adding runtime instrumentation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


def directory_size(path: Path) -> dict[str, int]:
    """Return logical and allocated bytes without following symlinks."""

    logical = 0
    disk = 0
    for item in path.rglob("*"):
        if item.is_symlink() or not item.is_file():
            continue
        metadata = item.stat()
        logical += metadata.st_size
        disk += metadata.st_blocks * 512
    return {"logical_bytes": logical, "disk_bytes": disk}


def main() -> int:
    """Measure one staged local-beta App and write the ignored JSON report."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idle-seconds", type=int, default=300)
    parser.add_argument("--cycles", type=int, default=20)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    engine = args.engine.resolve(strict=True)
    root = Path(".build/macos-resource-measurement").resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    (root / "jobs").mkdir(exist_ok=True, mode=0o700)
    os.chmod(root / "jobs", 0o700)
    probe = _build_window_probe(root)
    app_report, cycles = _measure_app(
        app,
        engine,
        probe,
        root,
        idle_seconds=args.idle_seconds,
        cycle_count=args.cycles,
    )
    report = {
        "schema_version": 1,
        "platform": _platform_report(),
        "sizes": {
            "swift_build": directory_size(Path(".build")),
            "pyinstaller_work": directory_size(Path("build/macos-engine")),
            "frozen_engine": directory_size(engine.parents[2]),
            "staged_app": directory_size(app),
        },
        "engine_cycles": {
            "count": len(cycles),
            "successful": sum(item["status"] == "succeeded" for item in cycles),
            "cancelled": sum(item["status"] == "cancelled" for item in cycles),
            "residual_process_groups": [
                item["process_group_id"] for item in cycles if item["process_group_alive"]
            ],
            "durations_seconds": [item["duration_seconds"] for item in cycles],
        },
        "app": app_report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


def _platform_report() -> dict[str, str]:
    return {
        "macos": _run(["/usr/bin/sw_vers", "-productVersion"]),
        "architecture": platform.machine(),
        "swift": _run(["/usr/bin/xcrun", "swift", "--version"]).splitlines()[0],
        "sdk": _run(["/usr/bin/xcrun", "--show-sdk-version"]),
        "python": platform.python_version(),
        "pyinstaller": _run([sys.executable, "-m", "PyInstaller", "--version"]),
    }


def _build_window_probe(root: Path) -> Path:
    output = root / "macos-window-probe"
    module_cache = root / "swift-module-cache"
    module_cache.mkdir(exist_ok=True)
    _run(
        [
            "/usr/bin/xcrun",
            "swiftc",
            "-module-cache-path",
            str(module_cache),
            "script/macos_window_probe.swift",
            "-o",
            str(output),
        ]
    )
    return output


def _run_engine_cycle(engine: Path, root: Path, *, cancel: bool) -> dict[str, Any]:
    request_id = str(uuid4())
    job = root / "jobs" / request_id
    job.mkdir(parents=True, mode=0o700)
    paths = {
        name: job / filename
        for name, filename in {
            "request": "request.json",
            "events": "events.jsonl",
            "result": "result.json",
            "error": "error.json",
        }.items()
    }
    paths["request"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": request_id,
                "command": "preflight",
                "created_at": "2026-08-30T00:00:00Z",
                "app_support_root": str(root),
                "config_path": None,
                "payload": {"live_probe": False},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(paths["request"], 0o600)
    started = time.monotonic()
    process = subprocess.Popen(
        [
            str(engine),
            "--request",
            str(paths["request"]),
            "--events",
            str(paths["events"]),
            "--result",
            str(paths["result"]),
            "--error",
            str(paths["error"]),
        ],
        env={
            "HOME": str(root),
            "LANG": "en_US.UTF-8",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(root),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process_group = _wait_for_process_group(process, paths["events"])
    try:
        if cancel and process.poll() is None:
            os.killpg(process_group, signal.SIGTERM)
        process.wait(timeout=30)
    except BaseException:
        if process.poll() is None:
            os.killpg(process_group, signal.SIGKILL)
            process.wait(timeout=5)
        raise
    status = "cancelled" if cancel else "succeeded"
    terminal_path = paths["error"] if cancel else paths["result"]
    if not terminal_path.exists():
        raise RuntimeError(f"Engine cycle did not write {terminal_path.name}.")
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    if terminal["status"] != ("failed" if cancel else "succeeded"):
        raise RuntimeError("Engine cycle wrote an unexpected terminal status.")
    if cancel and terminal.get("code") != "cancelled":
        raise RuntimeError("Cancelled engine cycle wrote an unexpected error code.")
    return {
        "status": status,
        "duration_seconds": round(time.monotonic() - started, 4),
        "process_group_id": process_group,
        "process_group_alive": _process_group_alive(process_group),
    }


def _wait_for_process_group(process: subprocess.Popen[Any], events: Path) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if events.exists():
            try:
                lines = events.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                lines = []
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "started":
                    process_group = process.pid
                    if os.getpgid(process.pid) != process_group:
                        raise RuntimeError("Engine started without its isolated process group.")
                    return process_group
        if process.poll() is not None:
            raise RuntimeError("Engine exited before its started event.")
        time.sleep(0.005)
    raise RuntimeError("Engine did not establish its process group.")


def _process_group_alive(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _measure_app(
    app: Path,
    engine: Path,
    probe: Path,
    root: Path,
    *,
    idle_seconds: int,
    cycle_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    executable = app / "Contents/MacOS/ResearchRadar"
    stdout = (root / "app.stdout").open("wb")
    stderr = (root / "app.stderr").open("wb")
    launched = time.monotonic()
    process = subprocess.Popen(
        [str(executable)],
        env={
            "HOME": str(root),
            "LANG": "en_US.UTF-8",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(root),
        },
        stdout=stdout,
        stderr=stderr,
    )
    try:
        observed = json.loads(_run([str(probe), str(process.pid), "15"]))
        first_window = round(time.monotonic() - launched, 4)
        screenshot = root / "foundation-window.png"
        subprocess.run(
            [
                "/usr/sbin/screencapture",
                "-x",
                "-l",
                str(observed["window_id"]),
                str(screenshot),
            ],
            capture_output=True,
            check=False,
        )
        cycles: list[dict[str, Any]] = []
        quiescent_rss: list[int] = []
        for index in range(cycle_count):
            cycles.append(_run_engine_cycle(engine, root, cancel=index % 2 == 1))
            quiescent_rss.append(_process_sample(process.pid)[0])
        samples: list[dict[str, float | int]] = []
        interval = 5
        sample_count = max(1, idle_seconds // interval + 1)
        for index in range(sample_count):
            rss, cpu = _process_sample(process.pid)
            samples.append(
                {"elapsed_seconds": index * interval, "rss_bytes": rss, "cpu_percent": cpu}
            )
            if index + 1 < sample_count:
                time.sleep(interval)
        children = _descendants(process.pid)
        leaks = _leaks_summary(process.pid)
        return (
            {
                "first_window_observed_seconds": first_window,
                "window_id": observed["window_id"],
                "quiescent_rss_after_cycles_bytes": quiescent_rss,
                "idle_duration_seconds": idle_seconds,
                "idle_samples": samples,
                "idle_descendants": children,
                "leaks_summary": leaks,
                "screenshot": str(screenshot.relative_to(Path.cwd())),
            },
            cycles,
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        stdout.close()
        stderr.close()


def _process_sample(pid: int) -> tuple[int, float]:
    output = _run(["/bin/ps", "-o", "rss=,%cpu=", "-p", str(pid)])
    rss_kib, cpu = output.split()
    return int(rss_kib) * 1024, float(cpu)


def _descendants(pid: int) -> list[int]:
    result: list[int] = []
    pending = [pid]
    while pending:
        parent = pending.pop()
        output = _run(["/usr/bin/pgrep", "-P", str(parent)], check=False)
        children = [int(value) for value in output.split()] if output else []
        result.extend(children)
        pending.extend(children)
    return result


def _leaks_summary(pid: int) -> str:
    result = subprocess.run(
        ["/usr/bin/leaks", str(pid)], capture_output=True, text=True, check=False, timeout=120
    )
    lines = (result.stdout + result.stderr).splitlines()
    return "\n".join(lines[-12:])


def _run(command: list[str], *, check: bool = True) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout).strip() or f"Command failed: {command[0]}"
        )
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
