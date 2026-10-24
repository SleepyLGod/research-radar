"""Build and verify a separate offline engine; never stage it in the production app."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image

from research_radar.app_bridge.configuration import load_app_configuration
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.wechat import render_wechat_html, wechat_publish_html_issues

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    """Write private test requests/configuration and verification evidence only."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def prepare_config(root: Path) -> Path:
    """Prepare synthetic settings validated by the production configuration loader."""
    config = {
        "schema_version": 1,
        "project_name": "ResearchRadar",
        "ui_language": "en",
        "workspace_root": str(root / "workspace"),
        "providers": [],
        "routes": [],
        "topics": [
            {
                "id": "memory",
                "display_name": "Agent Memory",
                "research_focus": "Agent memory evidence",
                "queries": ["agent memory"],
                "paper_queries": ["agent memory benchmark"],
                "web_queries": [],
                "exclusion_terms": [],
                "required_phrases": [],
                "negative_phrases": [],
                "concept_groups": {},
                "priority_sources": [],
                "source_intent": "research_brief",
                "report_language": "en",
            }
        ],
        "discovery": {
            "trusted_domains": [],
            "web_search_provider": None,
            "web_search_secret": "web_search.api_key",
            "web_search_endpoint": None,
            "web_search_max_results": 5,
            "web_search_depth": "advanced",
            "web_search_timeout_seconds": 30,
        },
        "delivery": {
            "wechat": {
                "enabled": True,
                "author": "Offline Fixture",
                "thumb_media_id": "offline-thumb",
                "app_id_secret": "wechat.app_id",
                "app_secret_secret": "wechat.app_secret",
            },
            "email": {
                "enabled": True,
                "smtp_host": "smtp.invalid",
                "smtp_port": 465,
                "security": "tls",
                "username": "offline@example.com",
                "password_secret": "email.smtp_password",
                "from_address": "offline@example.com",
                "to_address": "offline@example.com",
                "timeout_seconds": 30,
            },
        },
        "storage": {"model_cache_limit_bytes": None},
        "start_at_login": False,
    }
    path = root / "config" / "app-config.json"
    write_json(path, config)
    load_app_configuration(path)
    return path


def invoke(
    engine: list[str],
    root: Path,
    command: str,
    payload: dict[str, object],
    *,
    helper: Path,
    config: Path | None,
    expected_code: int = 0,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run a real child and sample its RSS; this is not App queue/UI execution."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    (root / "jobs").mkdir(exist_ok=True, mode=0o700)
    job = root / "jobs" / str(uuid4())
    job.mkdir(parents=True, mode=0o700)
    write_json(
        job / "request.json",
        {
            "schema_version": 1,
            "request_id": job.name,
            "command": command,
            "created_at": datetime.now(UTC).isoformat(),
            "app_support_root": str(root),
            "config_path": str(config) if config else None,
            "payload": payload,
        },
    )
    arguments = list(engine)
    for flag, name in (
        ("request", "request.json"),
        ("events", "events.jsonl"),
        ("result", "result.json"),
        ("error", "error.json"),
    ):
        arguments += [f"--{flag}", str(job / name)]
    arguments += ["--pdf-helper", str(helper)]
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        "HOME": str(root),
    }
    start = time.monotonic()
    samples = []
    with (job / "stdout.log").open("wb") as stdout, (job / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(arguments, stdout=stdout, stderr=stderr, env=env)
        try:
            while process.poll() is None:
                if time.monotonic() - start > 120:
                    raise TimeoutError(f"Offline engine timed out: {job}")
                result = subprocess.run(
                    ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.stdout.strip().isdigit():
                    samples.append(int(result.stdout.strip()) * 1024)
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    measurement = {
        "command": command,
        "job_dir": str(job),
        "exit_code": process.returncode,
        "elapsed_seconds": time.monotonic() - start,
        "engine_sampled_peak_rss_bytes": max(samples, default=None),
        "engine_rss_sample_count": len(samples),
        "scope": "direct child engine only; excludes PDF helper; not App queue or GUI",
    }
    write_json(job / "measurement.json", measurement)
    if process.returncode != expected_code:
        error_detail = (job / "error.json").read_text() if (job / "error.json").exists() else ""
        raise AssertionError(
            f"Unexpected engine exit: {measurement}; "
            f"stderr={(job / 'stderr.log').read_text()}; "
            f"error={error_detail}"
        )
    terminal = job / ("result.json" if expected_code == 0 else "error.json")
    opposite = job / ("error.json" if expected_code == 0 else "result.json")
    assert terminal.is_file() and not opposite.exists()
    events = [json.loads(line) for line in (job / "events.jsonl").read_text().splitlines()]
    assert events[0]["type"] == "started"
    assert events[-1]["type"] == ("completed" if expected_code == 0 else "failed")
    return json.loads(terminal.read_text()), measurement


def verify_rendered_bytes(actual: bytes, rendered: str) -> None:
    """Compare exact UTF-8 bytes including the production storage writer's newline."""
    expected = rendered if rendered.endswith("\n") else rendered + "\n"
    assert actual == expected.encode("utf-8")


def verify_report(run: Path) -> dict[str, object]:
    """Check full draft reload, renderer bytes and actual crop pixels, not mere existence."""
    draft = load_article_draft(run / "article_draft.json")
    html = (run / "wechat.html").read_bytes()
    verify_rendered_bytes(html, render_wechat_html(draft))
    assert draft.sections and draft.lede and draft.title
    assert draft.metadata["deep_read_count"] == 1
    figures = [json.loads(line) for line in (run / "figures.jsonl").read_text().splitlines()]
    assert figures, "Production pipeline did not produce a safe figure"
    hashes = {}
    for figure in figures:
        path = (run / figure["relative_path"]).resolve(strict=True)
        assert path.is_relative_to(run.resolve())
        assert figure["renderable"] and figure["reuse_status"] == "allowed_public_domain"
        assert figure["relative_path"].encode() in html
        with Image.open(path) as image:
            assert image.width >= 180 and image.height >= 120
            low, high = image.convert("L").getextrema()
            assert low < high, "Blank figure"
        hashes[figure["relative_path"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("article_draft.json", "wechat.html", "claims.jsonl", "evidence.jsonl"):
        hashes[name] = hashlib.sha256((run / name).read_bytes()).hexdigest()
    return {
        "run_dir": str(run),
        "title": draft.title,
        "figure_count": len(figures),
        "report_bytes": len(html),
        "sha256": hashes,
    }


def verify(engine: list[str], root: Path, helper: Path) -> dict[str, object]:
    """Exercise production preflight, run, failed WeChat and successful SMTP service."""
    config = prepare_config(root)
    preflight, first = invoke(
        engine, root, "preflight", {"live_probe": False}, helper=helper, config=None
    )
    assert preflight["preflight"]["ready"]
    daily, second = invoke(
        engine,
        root,
        "run_daily",
        {
            "topic_id": "memory",
            "report_date": datetime.now().date().isoformat(),
            "limit": 1,
            "deep_limit": 1,
            "language": "en",
            "model_cache": False,
            "model_cache_limit_bytes": None,
        },
        helper=helper,
        config=config,
    )
    report = daily["report"]
    assert report["deep_read_count"] == 1 and report["publishable_claim_count"] > 0
    run = Path(report["run_dir"])
    assert json.loads((run / "manifest.json").read_text())["report_date"] == report["report_date"]
    evidence = verify_report(run)
    failed, third = invoke(
        engine,
        root,
        "retry_delivery",
        {
            "run_dir": str(run),
            "channel": "wechat",
            "allow_resend": False,
            "acknowledge_unknown_outcome": False,
        },
        helper=helper,
        config=config,
        expected_code=1,
    )
    assert failed["code"] == "delivery_failed"
    assert failed["message"] == "OFFLINE_WECHAT_DELIVERY_FAILURE"
    assert not wechat_publish_html_issues((run / "wechat_publish.html").read_text())
    sent, fourth = invoke(
        engine,
        root,
        "retry_delivery",
        {
            "run_dir": str(run),
            "channel": "email",
            "allow_resend": False,
            "acknowledge_unknown_outcome": False,
        },
        helper=helper,
        config=config,
    )
    assert sent["delivery"]["status"] == "sent"
    assert json.loads((run / "email_send_result.json").read_text())["image_count"] > 0
    # Independent engine processes have restarted between each delivery; report bytes persist.
    assert verify_report(run) == evidence
    return {
        "report": evidence,
        "measurements": [first, second, third, fourth],
        "config_loader": "production",
        "network_guard": "socket/process audit hook",
        "verification_scope": "frozen file protocol and pipeline; not App index or GUI",
    }


def assert_production_excludes_fixture(engine: Path) -> None:
    """Inspect nested PyInstaller archives and bundle data for test-only content."""
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(engine))
    names = list(archive.toc)
    for name in archive.toc:
        if name.endswith(".pyz"):
            names.extend(archive.open_embedded_archive(name).toc)
    assert not any("offline_frozen" in name or "offline-test" in name for name in names)
    bundle = next((parent for parent in engine.parents if parent.suffix == ".app"), engine.parent)
    assert not any(
        "offline_frozen" in path.parts or "offline-test" in path.name for path in bundle.rglob("*")
    )


def main() -> int:
    """Build with the existing venv, retain all outputs, and print exact evidence location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--pdf-helper", type=Path, required=True)
    parser.add_argument("--production-engine", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output = (args.output_root or Path(tempfile.mkdtemp(prefix="radar-offline-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    engine = args.engine
    if args.build:
        work, dist = output / "build", output / "dist"
        if work.exists() or dist.exists():
            raise FileExistsError("Use a fresh output root; existing builds are never deleted.")
        subprocess.run(
            [
                str(ROOT / ".venv/bin/python"),
                "-m",
                "PyInstaller",
                "--workpath",
                str(work),
                "--distpath",
                str(dist),
                str(ROOT / "packaging/macos/research-radar-offline-test.spec"),
            ],
            check=True,
        )
        engine = dist / "research-radar-offline-test/research-radar-offline-test"
    if engine is None:
        parser.error("Specify --build or --engine")
    engine = engine.resolve(strict=True)
    helper = args.pdf_helper.resolve(strict=True)
    if not os.access(engine, os.X_OK) or not os.access(helper, os.X_OK):
        raise ValueError("Engine and PDF helper must be executable")
    evidence = verify([str(engine)], output / "ResearchRadar", helper)
    evidence["engine"] = str(engine)
    evidence["engine_sha256"] = hashlib.sha256(engine.read_bytes()).hexdigest()
    evidence["pdf_helper"] = str(helper)
    evidence["pdf_helper_sha256"] = hashlib.sha256(helper.read_bytes()).hexdigest()
    if args.production_engine:
        production = args.production_engine.resolve(strict=True)
        assert_production_excludes_fixture(production)
        result, measurement = invoke(
            [str(production)],
            output / "ProductionPreflight",
            "preflight",
            {"live_probe": False},
            helper=helper,
            config=None,
        )
        assert result["preflight"]["ready"]
        evidence["production_preflight"] = measurement
        evidence["production_excludes_fixture"] = True
    write_json(output / "verification.json", evidence)
    print(output / "verification.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
