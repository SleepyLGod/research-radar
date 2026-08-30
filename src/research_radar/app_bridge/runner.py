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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any, Protocol, cast

from research_radar.app_bridge import BRIDGE_SCHEMA_VERSION
from research_radar.app_bridge.configuration import (
    AppConfigurationError,
    LoadedAppConfigurationV1,
    load_app_configuration,
)
from research_radar.app_bridge.events import EventWriter
from research_radar.app_bridge.protocol import (
    EngineCommand,
    EngineRequestV1,
    ProtocolError,
    RetryDeliveryPayloadV1,
    RunDailyPayloadV1,
    load_request,
)
from research_radar.exceptions import ResearchRadarError
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import KeychainSecretBackend, SecretManager

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


class CommandHandler(Protocol):
    """One injected bridge command implementation."""

    def __call__(
        self,
        request: EngineRequestV1,
        *,
        config: LoadedAppConfigurationV1 | None,
        secrets: object,
        events: EventWriter,
        pdf_helper_path: Path | None,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class BridgeDependencies:
    """Injected command handlers and deterministic boundary services."""

    preflight: CommandHandler
    bootstrap_topic: CommandHandler
    run_daily: CommandHandler
    retry_delivery: CommandHandler
    clock: Callable[[], datetime]
    config_loader: Callable[[Path, bool], object]
    secret_manager_factory: Callable[[], object]

    @classmethod
    def production(cls) -> BridgeDependencies:
        """Build production handlers without exposing CLI presentation logic."""

        from research_radar.app_bridge.handlers import (
            handle_bootstrap_topic,
            handle_preflight,
            handle_retry_delivery,
            handle_run_daily,
        )

        return cls(
            preflight=handle_preflight,
            bootstrap_topic=handle_bootstrap_topic,
            run_daily=handle_run_daily,
            retry_delivery=handle_retry_delivery,
            clock=lambda: datetime.now(UTC),
            config_loader=lambda path, require_topics: load_app_configuration(
                path, require_topics=require_topics
            ),
            secret_manager_factory=lambda: SecretManager(KeychainSecretBackend()),
        )

    @classmethod
    def testing(cls) -> BridgeDependencies:
        """Return inert handlers suitable for selective dependency replacement."""

        def unexpected(*args: object, **kwargs: object) -> dict[str, object]:
            raise AssertionError("Unexpected bridge handler call")

        return cls(
            preflight=unexpected,
            bootstrap_topic=unexpected,
            run_daily=unexpected,
            retry_delivery=unexpected,
            clock=lambda: datetime.now(UTC),
            config_loader=lambda path, require_topics: object(),
            secret_manager_factory=lambda: object(),
        )


@dataclass(frozen=True, slots=True)
class BridgeExecutionError(ResearchRadarError):
    """Stable, redacted error returned through the bridge protocol."""

    code: str
    stage: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


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
    pdf_helper_path: Path | None = None,
    dependencies: BridgeDependencies | None = None,
) -> int:
    """Validate and execute one bridge request, writing one terminal artifact."""

    job_dir = request_path.parent.resolve(strict=True)
    _validate_artifact_paths(job_dir, events_path, result_path, error_path)
    if result_path.exists() or error_path.exists():
        raise RuntimeError("Terminal artifact already exists for this request.")

    request_id = job_dir.name
    active_dependencies = dependencies or BridgeDependencies.production()
    writer = EventWriter(
        events_path,
        request_id=request_id,
        clock=active_dependencies.clock,
    )
    cancelled = threading.Event()
    parent_lost = threading.Event()
    session_established = threading.Event()
    watcher: _ParentWatcher | None = None
    previous_handlers: dict[int, Any] = {}
    terminal_lock = threading.Lock()
    current_stage = "preflight"
    request: EngineRequestV1 | None = None

    def write_result_once(value: dict[str, Any]) -> bool:
        with terminal_lock:
            if result_path.exists() or error_path.exists():
                return False
            _write_private_json(result_path, value)
            return True

    def write_error_once(
        *,
        code: str,
        message: str,
        stage: str = "preflight",
        retryable: bool = False,
    ) -> bool:
        with terminal_lock:
            if result_path.exists() or error_path.exists():
                return False
            _write_error(
                error_path,
                request_id=request_id,
                code=code,
                message=message,
                stage=stage,
                retryable=retryable,
                completed_at=active_dependencies.clock(),
            )
            return True

    def write_failure_event(code: str, message: str, *, retryable: bool) -> None:
        writer.write(
            "failed",
            stage=current_stage,
            status="failed",
            message=message,
            error={"code": code, "message": message, "retryable": retryable},
        )

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        cancelled.set()

    def handle_parent_lost() -> None:
        parent_lost.set()
        cancelled.set()
        message = "The supervising App exited while a task was running."
        write_error_once(code="parent_lost", message=message, stage=current_stage)
        _terminate_after_parent_loss(
            isolated=session_established.is_set(),
            grace_seconds=parent_loss_grace_seconds,
        )

    try:
        request = load_request(request_path, job_dir=job_dir)
        current_stage = _stage_for_request(request)
        parent_pid = os.getppid()
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, handle_signal)
        if watch_parent:
            watcher = _ParentWatcher(parent_pid, handle_parent_lost)
            watcher.start()
        if establish_session:
            _establish_isolated_process_group()
            session_established.set()
        writer.write("started", stage=None, message="ResearchRadar engine started.")
        if cancelled.is_set():
            raise _Cancelled
        config = _load_request_configuration(request, active_dependencies)
        if isinstance(request.payload, RunDailyPayloadV1):
            current_date = active_dependencies.clock().astimezone().date().isoformat()
            if request.payload.report_date != current_date:
                raise BridgeExecutionError(
                    code="invalid_report_date",
                    stage="discovery",
                    message="The requested report date is not today.",
                )
        handler = _handler_for(request.command, active_dependencies)
        output = handler(
            request,
            config=config,
            secrets=active_dependencies.secret_manager_factory(),
            events=writer,
            pdf_helper_path=pdf_helper_path,
        )
        if cancelled.is_set():
            raise _Cancelled
        terminal = _result_envelope(request, output, completed_at=active_dependencies.clock())
        if not write_result_once(terminal):
            if cancelled.is_set():
                raise _Cancelled
            raise RuntimeError("A terminal artifact already exists for this request.")
        writer.write(
            "completed",
            stage="complete",
            status="succeeded",
            message="ResearchRadar engine completed.",
            run_dir=str(output.get("run_dir")) if output.get("run_dir") else None,
        )
        return 0
    except _Cancelled:
        code = "parent_lost" if parent_lost.is_set() else "cancelled"
        message = (
            "The supervising App exited while a task was running."
            if parent_lost.is_set()
            else "The task was cancelled."
        )
        write_error_once(code=code, message=message, stage=current_stage)
        writer.write(
            "cancelled" if code == "cancelled" else "failed",
            stage=current_stage,
            status="failed",
            message=message,
            error={"code": code, "message": message, "retryable": False}
            if code != "cancelled"
            else None,
        )
        return 75 if parent_lost.is_set() else 130
    except BridgeExecutionError as exc:
        message = redact_text(exc.message)
        write_error_once(
            code=exc.code,
            message=message,
            stage=exc.stage,
            retryable=exc.retryable,
        )
        writer.write(
            "failed",
            stage=exc.stage,
            status="failed",
            message=message,
            error={"code": exc.code, "message": message, "retryable": exc.retryable},
        )
        return 2 if exc.code.startswith("invalid_") else 1
    except (ProtocolError, AppConfigurationError) as exc:
        message = redact_text(str(exc))
        code = (
            "invalid_configuration"
            if isinstance(exc, AppConfigurationError)
            else "invalid_request"
        )
        write_error_once(code=code, message=message, stage=current_stage)
        write_failure_event(code, message, retryable=False)
        return 2
    except ValueError as exc:
        message = redact_text(str(exc)) or "The request could not be completed."
        write_error_once(
            code="invalid_configuration",
            message=message,
            stage=current_stage,
        )
        write_failure_event("invalid_configuration", message, retryable=False)
        return 2
    except ResearchRadarError as exc:
        message = redact_text(str(exc)) or "The task could not be completed."
        code = (
            "delivery_failed"
            if request is not None and request.command is EngineCommand.RETRY_DELIVERY
            else "research_failed"
        )
        write_error_once(
            code=code,
            message=message,
            stage=current_stage,
            retryable=True,
        )
        write_failure_event(code, message, retryable=True)
        return 1
    except (ImportError, OSError, RuntimeError) as exc:
        message = redact_text(str(exc)) or "The engine stopped unexpectedly."
        write_error_once(
            code="engine_crashed",
            message=message,
            stage=current_stage,
            retryable=True,
        )
        write_failure_event("engine_crashed", message, retryable=True)
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


def dependency_report() -> dict[str, dict[str, Any]]:
    """Return the frozen dependency report used by local preflight."""

    return _dependency_report()


def _load_request_configuration(
    request: EngineRequestV1,
    dependencies: BridgeDependencies,
) -> LoadedAppConfigurationV1 | None:
    if request.config_path is None:
        return None
    require_topics = request.command in {EngineCommand.RUN_DAILY, EngineCommand.RETRY_DELIVERY}
    loaded = dependencies.config_loader(request.config_path, require_topics)
    # Injected tests may use an opaque configuration sentinel.
    return cast(LoadedAppConfigurationV1, loaded)


def _handler_for(command: EngineCommand, dependencies: BridgeDependencies) -> CommandHandler:
    return {
        EngineCommand.PREFLIGHT: dependencies.preflight,
        EngineCommand.BOOTSTRAP_TOPIC: dependencies.bootstrap_topic,
        EngineCommand.RUN_DAILY: dependencies.run_daily,
        EngineCommand.RETRY_DELIVERY: dependencies.retry_delivery,
    }[command]


def _stage_for_request(request: EngineRequestV1) -> str:
    if isinstance(request.payload, RetryDeliveryPayloadV1):
        return "wechat_draft" if request.payload.channel == "wechat" else "email"
    return {
        EngineCommand.PREFLIGHT: "preflight",
        EngineCommand.BOOTSTRAP_TOPIC: "topic_bootstrap",
        EngineCommand.RUN_DAILY: "discovery",
    }[request.command]


def _result_envelope(
    request: EngineRequestV1,
    output: dict[str, object],
    *,
    completed_at: datetime,
) -> dict[str, object]:
    payload_key = {
        EngineCommand.PREFLIGHT: "preflight",
        EngineCommand.BOOTSTRAP_TOPIC: "topic_draft",
        EngineCommand.RUN_DAILY: "report",
        EngineCommand.RETRY_DELIVERY: "delivery",
    }[request.command]
    payloads: dict[str, object | None] = {
        "preflight": None,
        "topic_draft": None,
        "report": None,
        "delivery": None,
    }
    result_payload = dict(output)
    if request.command is EngineCommand.RETRY_DELIVERY:
        result_payload["completed_at"] = _timestamp(completed_at)
    payloads[payload_key] = result_payload
    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "request_id": request.request_id,
        "command": request.command.value,
        "status": "succeeded",
        "completed_at": _timestamp(completed_at),
        **payloads,
    }


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


def _write_error(
    path: Path,
    *,
    request_id: str,
    code: str,
    message: str,
    stage: str,
    retryable: bool,
    completed_at: datetime,
) -> None:
    _write_private_json(
        path,
        {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "request_id": request_id,
            "status": "failed",
            "stage": stage,
            "code": code,
            "message": redact_text(message),
            "retryable": retryable,
            "completed_at": _timestamp(completed_at),
        },
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
