"""Task 1 execution boundary for the bundled macOS engine."""

from __future__ import annotations

import errno
import importlib
import importlib.metadata
import json
import os
import select
import signal
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import Any

from research_radar import __version__
from research_radar.app_bridge import BRIDGE_SCHEMA_VERSION
from research_radar.app_bridge.events import EventWriter
from research_radar.app_bridge.protocol import ProtocolError, load_request
from research_radar.security.redaction import redact_text

_DEPENDENCIES = {
    "cryptography": "cryptography",
    "keyring": "keyring",
    "PIL": "Pillow",
    "pypdf": "pypdf",
    "yaml": "PyYAML",
    "research_radar.app_bridge": "research-radar",
}


class _Cancelled(Exception):
    pass


class _ParentWatcher:
    def __init__(self, parent_pid: int, on_lost: Any) -> None:
        self._parent_pid = parent_pid
        self._on_lost = on_lost
        self._queue: Any | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if sys.platform != "darwin" or not hasattr(select, "kqueue"):
            raise RuntimeError("Parent process monitoring requires macOS kqueue.")
        if self._parent_pid <= 1:
            raise RuntimeError("The App parent process is unavailable.")
        queue = select.kqueue()
        event = select.kevent(
            self._parent_pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT,
        )
        queue.control([event], 0, 0)
        self._queue = queue
        self._thread = threading.Thread(target=self._wait, name="parent-exit-watch")
        self._thread.start()

    def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
            self._queue = None
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
            self._thread = None

    def _wait(self) -> None:
        queue = self._queue
        if queue is None:
            return
        try:
            events = queue.control(None, 1, None)
        except OSError:
            return
        if events:
            self._on_lost()


def run_bridge(
    *,
    request_path: Path,
    events_path: Path,
    result_path: Path,
    error_path: Path,
    establish_session: bool = True,
    watch_parent: bool = True,
    parent_loss_grace_seconds: float = 5.0,
) -> int:
    """Validate and execute one preflight request, writing one terminal artifact."""

    job_dir = request_path.parent.resolve(strict=True)
    _validate_artifact_paths(job_dir, events_path, result_path, error_path)
    if result_path.exists() or error_path.exists():
        raise RuntimeError("Terminal artifact already exists for this request.")

    request_id = job_dir.name
    writer = EventWriter(events_path, request_id=request_id)
    cancelled = threading.Event()
    parent_lost = threading.Event()
    session_established = threading.Event()
    watcher: _ParentWatcher | None = None
    previous_handlers: dict[int, Any] = {}
    terminal_lock = threading.Lock()

    def write_result_once(value: dict[str, Any]) -> bool:
        with terminal_lock:
            if result_path.exists() or error_path.exists():
                return False
            _write_private_json(result_path, value)
            return True

    def write_error_once(*, code: str, message: str) -> bool:
        with terminal_lock:
            if result_path.exists() or error_path.exists():
                return False
            _write_error(error_path, request_id=request_id, code=code, message=message)
            return True

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        cancelled.set()

    def handle_parent_lost() -> None:
        parent_lost.set()
        cancelled.set()
        message = "The supervising App exited while preflight was running."
        write_error_once(code="parent_lost", message=message)
        _terminate_after_parent_loss(
            isolated=session_established.is_set(),
            grace_seconds=parent_loss_grace_seconds,
        )

    try:
        request = load_request(request_path, job_dir=job_dir)
        parent_pid = os.getppid()
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, handle_signal)
        if watch_parent:
            watcher = _ParentWatcher(parent_pid, handle_parent_lost)
            watcher.start()
        if establish_session:
            _establish_isolated_process_group()
            session_established.set()
        writer.write(
            "started",
            stage="preflight",
            message="Local preflight started.",
            process_id=os.getpid(),
            process_group_id=os.getpgrp(),
        )
        if cancelled.is_set():
            raise _Cancelled
        dependencies = _dependency_report()
        if cancelled.is_set():
            raise _Cancelled
        terminal = {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "request_id": request.request_id,
            "status": "succeeded",
            "preflight": {
                "engine_version": __version__,
                "python_version": ".".join(str(item) for item in sys.version_info[:3]),
                "dependencies": dependencies,
            },
        }
        if not write_result_once(terminal):
            if cancelled.is_set():
                raise _Cancelled
            raise RuntimeError("A terminal artifact already exists for this request.")
        writer.write("completed", stage="preflight", message="Local preflight completed.")
        return 0
    except _Cancelled:
        code = "parent_lost" if parent_lost.is_set() else "cancelled"
        message = (
            "The supervising App exited while preflight was running."
            if parent_lost.is_set()
            else "Preflight was cancelled."
        )
        write_error_once(code=code, message=message)
        writer.write("failed", stage="preflight", message=message, error_code=code)
        return 75 if parent_lost.is_set() else 130
    except ProtocolError as exc:
        message = redact_text(str(exc))
        write_error_once(code="invalid_request", message=message)
        return 2
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        message = redact_text(str(exc)) or "Preflight failed."
        write_error_once(code="engine_crashed", message=message)
        return 1
    finally:
        if watcher is not None:
            watcher.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _dependency_report() -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for module_name, distribution_name in _DEPENDENCIES.items():
        module = importlib.import_module(module_name)
        try:
            version = importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            version = str(getattr(module, "__version__", "bundled"))
        report[module_name] = {"available": True, "version": version}
    import keyring

    report["keyring"]["backend"] = type(keyring.get_keyring()).__name__
    return report


def _establish_isolated_process_group() -> None:
    """Create a session, or accept Foundation.Process's isolated process group."""

    try:
        os.setsid()
    except OSError as exc:
        if exc.errno != errno.EPERM or os.getpgrp() != os.getpid():
            raise


def _terminate_after_parent_loss(*, isolated: bool, grace_seconds: float) -> None:
    target = -os.getpgrp() if isolated and os.getpgrp() == os.getpid() else os.getpid()
    os.kill(target, signal.SIGTERM)
    time.sleep(grace_seconds)
    os.kill(target, signal.SIGKILL)


def _validate_artifact_paths(job_dir: Path, *paths: Path) -> None:
    for path in paths:
        try:
            path.resolve(strict=False).relative_to(job_dir)
        except ValueError as exc:
            raise RuntimeError("Bridge artifact paths must stay within the job directory.") from exc


def _write_error(path: Path, *, request_id: str, code: str, message: str) -> None:
    _write_private_json(
        path,
        {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "request_id": request_id,
            "status": "failed",
            "code": code,
            "message": redact_text(message),
        },
    )


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
