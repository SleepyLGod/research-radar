"""Separate frozen test engine; production entrypoint never imports this module."""

from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import patch

from offline_frozen.inputs import FrozenDiscovery, FrozenModel
from research_radar.analysis.routing import TaskModelRoute
from research_radar.app_bridge.handlers import handle_retry_delivery, handle_run_daily
from research_radar.app_bridge.runner import BridgeDependencies, run_bridge
from research_radar.application.daily import run_daily_application
from research_radar.exceptions import PublishError
from research_radar.publishers.wechat.client import WeChatDraftClient
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def block_external_io(pdf_helper: Path | None) -> None:
    """Deny sockets and child programs other than the explicitly supplied PDF helper."""
    allowed = str(pdf_helper.resolve(strict=True)) if pdf_helper else None

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event in {
            "socket.connect",
            "socket.connect_ex",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.sendto",
            "socket.bind",
        }:
            raise RuntimeError("OFFLINE_NETWORK_BLOCKED")
        if event == "subprocess.Popen":
            if allowed is None or str(Path(str(args[0])).resolve()) != allowed:
                raise RuntimeError("OFFLINE_PROCESS_BLOCKED")
        if event in {"os.system", "os.posix_spawn", "os.exec", "os.spawn"}:
            raise RuntimeError("OFFLINE_PROCESS_BLOCKED")

    sys.addaudithook(audit)
    # Prove the guard before running any production handler; no packet is sent.
    with socket.socket() as client:
        try:
            client.connect(("203.0.113.1", 443))
        except RuntimeError as exc:
            if str(exc) != "OFFLINE_NETWORK_BLOCKED":
                raise
        else:
            raise AssertionError("Offline network guard did not run")


class FailedWeChat(WeChatDraftClient):
    """Fake remote client fails after the real service prepares safe publish HTML."""

    def upload_article_image(self, path: Path) -> str:
        """Accept a real pipeline PNG without uploading it."""
        if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise AssertionError("Expected real figure PNG")
        return "https://mmbiz.qpic.cn/offline-fixture/figure.png"

    def add_draft(self, article: object) -> dict[str, object]:
        """Simulate a known channel failure, never send a message."""
        raise PublishError("OFFLINE_WECHAT_DELIVERY_FAILURE")


class OfflineSMTP:
    """Fake only the SMTP transport, leaving MIME construction and journal real."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> OfflineSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def login(self, username: str, password: str) -> None:
        """Require test credentials rather than reading the real keychain."""
        if password != "offline-placeholder":
            raise AssertionError("Unexpected SMTP secret")

    def send_message(self, message: object) -> dict[str, object]:
        """Require the real renderer's image-bearing MIME message."""
        if "image/png" not in message.as_string():
            raise AssertionError("Expected the pipeline figure in email MIME")
        return {}


def dependencies(root: Path) -> BridgeDependencies:
    """Reuse production handlers and application service with external IO overrides."""
    local = TaskModelRoute(provider=None, model=None, provider_name="local")
    model = FrozenModel()
    routes = {
        task: local
        for task in (
            "source_gist",
            "deep_reading",
            "anchor_repair",
            "report_localization",
            "verifier",
        )
    }
    for task, name in (("deep_reading", "fixture-reader"), ("verifier", "fixture-verifier")):
        routes[task] = TaskModelRoute(provider=model, model=name, provider_name=model.name)
    backend = InMemorySecretBackend()
    for name in ("email.smtp_password", "wechat.app_id", "wechat.app_secret"):
        backend.set_secret(name, "offline-placeholder")
    return replace(
        BridgeDependencies.production(),
        run_daily=partial(
            handle_run_daily,
            daily_runner=partial(
                run_daily_application,
                connectors=[FrozenDiscovery(root)],
                task_routes=routes,
            ),
        ),
        retry_delivery=partial(handle_retry_delivery, wechat_client_factory=FailedWeChat),
        secret_manager_factory=lambda: SecretManager(backend),
    )


def main() -> int:
    """Execute the production file protocol in a network-blocked test process."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("request", "events", "result", "error"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--pdf-helper", type=Path)
    args = parser.parse_args()
    block_external_io(args.pdf_helper)
    root = args.request.resolve().parent.parent.parent / "workspace"
    with patch("smtplib.SMTP_SSL", OfflineSMTP), patch("smtplib.SMTP", OfflineSMTP):
        return run_bridge(
            request_path=args.request,
            events_path=args.events,
            result_path=args.result,
            error_path=args.error,
            pdf_helper_path=args.pdf_helper,
            dependencies=dependencies(root),
        )


if __name__ == "__main__":
    raise SystemExit(main())
