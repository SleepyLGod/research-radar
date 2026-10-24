"""Test-only parent process used to exercise the bridge parent-loss contract."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _run_parent() -> int:
    child_pid_path = Path(sys.argv[2])
    child = subprocess.Popen(
        [sys.executable, __file__, "engine", *sys.argv[3:]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    temporary = child_pid_path.with_suffix(".tmp")
    temporary.write_text(str(child.pid), encoding="utf-8")
    temporary.replace(child_pid_path)
    while True:
        time.sleep(1)


def _run_engine() -> int:
    from research_radar.app_bridge import runner

    request, events, result, error = (Path(value) for value in sys.argv[2:6])

    def slow_dependency_report() -> dict[str, dict[str, object]]:
        time.sleep(60)
        return {}

    runner._dependency_report = slow_dependency_report
    return runner.run_bridge(
        request_path=request,
        events_path=events,
        result_path=result,
        error_path=error,
        parent_loss_grace_seconds=0.1,
    )


if __name__ == "__main__":
    if sys.argv[1] == "parent":
        raise SystemExit(_run_parent())
    if sys.argv[1] == "engine":
        raise SystemExit(_run_engine())
    os._exit(2)
