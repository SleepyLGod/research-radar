"""Real bridge/daily orchestration with offline external IO and fake credentials."""

from __future__ import annotations

import io
import json
import signal
import socket
import subprocess
from datetime import datetime
from http.client import IncompleteRead
from pathlib import Path
from urllib.request import Request
from uuid import uuid4

import keyring
import pytest
from fixtures.offline_frozen.inputs import FrozenDiscovery, FrozenModel
from keyring.errors import KeyringLocked

from research_radar.analysis import openai_compatible
from research_radar.analysis.providers import Message
from research_radar.app_bridge.pdf_helper import PDFHelperClient
from research_radar.app_bridge.runner import run_bridge
from research_radar.discovery.arxiv import ArxivConnector
from research_radar.discovery.github import GitHubRepoConnector
from research_radar.discovery.openalex import OpenAlexConnector
from research_radar.discovery.semantic_scholar import SemanticScholarConnector

FIXTURES = Path(__file__).parent / "fixtures" / "offline_frozen"
ACCOUNT = "research-radar-authorization-test-offline"


@pytest.mark.parametrize("outcome", ["recover", "exhaust", "cancel"])
def test_daily_transport_recovery_and_cancellation_use_real_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    offline_io: list[tuple[str, str]], outcome: str,
) -> None:
    credential_reads: list[str] = []

    def credential(service: str, account: str) -> str:
        assert account == ACCOUNT
        credential_reads.append(account)
        return "fake-recovery-key"

    monkeypatch.setattr(keyring, "get_password", credential)
    job = _job(tmp_path / "recovery")
    config_path = job.parent.parent / "app-config.json"
    config = json.loads(config_path.read_text())
    config["providers"][0]["timeout_seconds"] = 10
    config_path.write_text(json.dumps(config))
    original = openai_compatible.urlopen
    attempts: list[str] = []

    def request(req: Request, *, timeout: float):
        model = json.loads(req.data)["model"]
        if model == "fixture-gist":
            attempts.append(model)
            if outcome == "cancel":
                signal.raise_signal(signal.SIGTERM)
            if len(attempts) == 1 or outcome != "recover":
                raise IncompleteRead(b"")
        return original(req, timeout=timeout)

    monkeypatch.setattr(openai_compatible, "urlopen", request)
    code = _run(job)
    assert credential_reads == [ACCOUNT]
    if outcome == "recover":
        assert code == 0
        _assert_report(job, offline_io, "fake-recovery-key")
    else:
        assert code == (130 if outcome == "cancel" else 1)
        terminal = json.loads((job / "error.json").read_text())
        assert terminal["stage"] == "source_gist"
        assert terminal["code"] == (
            "cancelled" if outcome == "cancel" else "model_response_retry_exhausted"
        )
        assert not (job / "result.json").exists()
        assert not list((job.parent.parent / "workspace").rglob("article_draft.json"))
    assert len(attempts) == (1 if outcome == "cancel" else 2)


@pytest.fixture
def offline_io(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[str, str]]:
    """Replace only discovery, HTTP, and PDFKit IO; forbid all other external IO."""
    requests: list[tuple[str, str]] = []
    discovery = FrozenDiscovery(tmp_path)
    monkeypatch.setattr(
        ArxivConnector, "discover", lambda self, context: discovery.discover(context)
    )
    for connector in (SemanticScholarConnector, OpenAlexConnector, GitHubRepoConnector):
        monkeypatch.setattr(connector, "discover", lambda self, context: [])

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Unexpected network or subprocess IO in offline bridge regression")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    def pdf_response(self: PDFHelperClient, request: dict[str, object]) -> dict[str, object]:
        assert request["operation"] == "page_text"
        return {
            "schema_version": 1,
            "operation": "page_text",
            "page": {"page_box": {"x": 0, "y": 0, "width": 612, "height": 792}, "words": []},
        }

    monkeypatch.setattr(PDFHelperClient, "_call", pdf_response)

    def transport(request: Request, *, timeout: int) -> io.BytesIO:
        assert request.full_url == "https://offline.invalid/chat/completions"
        assert request.data is not None
        payload = json.loads(request.data)
        model = payload["model"]
        requests.append((model, request.get_header("Authorization")))
        if model == "fixture-gist":
            content = json.dumps({"gists": [{"index": 1, "gist": "A grounded memory benchmark."}]})
        else:
            content = FrozenModel().complete(
                [Message(**message) for message in payload["messages"]], model=model
            ).content
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setattr(openai_compatible, "urlopen", transport)
    return requests


def _job(root: Path) -> Path:
    """Create actual AppJSON configuration and a run_daily bridge request."""
    root.mkdir(parents=True, mode=0o700)
    job = root / "jobs" / str(uuid4())
    job.mkdir(parents=True, mode=0o700)
    config = json.loads((FIXTURES / "swift-app-config-omitted-optionals.json").read_text())
    # Separate workspaces keep discovery history from suppressing the second report.
    config["workspace_root"] = str(root / "workspace")
    for channel in config["delivery"].values():
        channel["enabled"] = False
    config["providers"] = [{
        "id": "offline", "kind": "openai_compatible",
        "base_url": "https://offline.invalid/chat/completions",
        "api_key_secret": ACCOUNT, "timeout_seconds": 1,
    }]
    config["routes"] = [
        {"task": task, "provider_id": "offline", "model": model}
        for task, model in (
            ("source_gist", "fixture-gist"),
            ("deep_reading", "fixture-reader"),
            ("verifier", "fixture-verifier"),
        )
    ]
    config_path = root / "app-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    now = datetime.now().astimezone()
    (job / "request.json").write_text(json.dumps({
        "schema_version": 1, "request_id": job.name, "command": "run_daily",
        "created_at": now.isoformat(), "app_support_root": str(root),
        "config_path": str(config_path),
        "payload": {
            "topic_id": "memory", "report_date": now.date().isoformat(),
            "limit": 1, "deep_limit": 1, "language": "en", "model_cache": False,
            "model_cache_limit_bytes": None,
        },
    }), encoding="utf-8")
    return job


def _run(job: Path) -> int:
    return run_bridge(
        request_path=job / "request.json", events_path=job / "events.jsonl",
        result_path=job / "result.json", error_path=job / "error.json",
        pdf_helper_path=Path("/usr/bin/true"), establish_session=False, watch_parent=False,
    )


def _assert_report(job: Path, requests: list[tuple[str, str]], value: str) -> None:
    result = json.loads((job / "result.json").read_text())
    assert result["status"] == "succeeded"
    assert not (job / "error.json").exists()
    assert requests == [
        ("fixture-gist", f"Bearer {value}"),
        ("fixture-reader", f"Bearer {value}"),
        ("fixture-verifier", f"Bearer {value}"),
    ]
    reports = list((job.parent.parent / "workspace").rglob("article_draft.json"))
    assert len(reports) == 1
    report = reports[0].parent
    assert (report / "wechat.html").is_file()
    assert json.loads((report / "summary.json").read_text())["publishable_claim_count"] > 0
    events = [json.loads(line) for line in (job / "events.jsonl").read_text().splitlines()]
    assert events[0]["type"] == "started"
    assert events[-1]["type"] == "completed"
    assert value not in (job / "result.json").read_text()
    assert value not in (job / "events.jsonl").read_text()


def test_daily_reads_success_once_and_next_bridge_job_reads_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, offline_io: list[tuple[str, str]],
) -> None:
    calls: list[tuple[str, str]] = []
    value = "fake-first-job"

    def get_password(service: str, account: str) -> str:
        calls.append((service, account))
        assert account == ACCOUNT  # No optional/global credentials may be touched.
        return value

    monkeypatch.setattr(keyring, "get_password", get_password)
    for index, value in enumerate(("fake-first-job", "fake-next-job"), start=1):
        offline_io.clear()
        job = _job(tmp_path / f"app-{index}")
        assert _run(job) == 0
        _assert_report(job, offline_io, value)
        assert calls == [("ResearchRadar", ACCOUNT)] * index


@pytest.mark.parametrize("denied", [False, True], ids=["missing", "denied"])
def test_daily_failed_read_is_retried_by_next_bridge_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    offline_io: list[tuple[str, str]], denied: bool,
) -> None:
    calls: list[tuple[str, str]] = []

    def get_password(service: str, account: str) -> str | None:
        calls.append((service, account))
        assert account == ACCOUNT
        if len(calls) == 1:
            if denied:
                raise KeyringLocked("Synthetic denial containing fake-sensitive-value")
            return None
        return "fake-retry-job"

    monkeypatch.setattr(keyring, "get_password", get_password)
    first = _job(tmp_path / "failed-app")
    assert _run(first) == 1
    error_text = (first / "error.json").read_text()
    error = json.loads(error_text)
    assert error["retryable"] is True
    assert error["code"] == "research_failed"
    assert "fake-sensitive-value" not in error_text
    assert "fake-sensitive-value" not in (first / "events.jsonl").read_text()
    if denied:
        assert error["message"] == "Keychain secret access failed."
    assert not (first / "result.json").exists()
    assert offline_io == []
    assert calls == [("ResearchRadar", ACCOUNT)]
    retry = _job(tmp_path / "retry-app")
    assert _run(retry) == 0
    _assert_report(retry, offline_io, "fake-retry-job")
    assert calls == [("ResearchRadar", ACCOUNT)] * 2
