"""Exercise the actual native App with a separate, network-blocked test engine bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import signal
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from research_radar.compose.draft_io import load_article_draft


def write_json(path: Path, value: object) -> None:
    """Write synthetic private state, never real credentials or production state."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def app_pid(executable: Path) -> int | None:
    """Locate only this test checkout's App executable, not other ResearchRadar instances."""
    output = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1] == str(executable):
            return int(parts[0])
    return None


def wait_for[T](predicate: Callable[[], T], description: str, timeout: float = 90) -> T:
    """Bound the test observer; this polling is not App runtime behavior."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise TimeoutError(description)


def stop_app(executable: Path) -> None:
    """Stop only the test App; never target by a global process name."""
    pid = app_pid(executable)
    if pid is None:
        return
    os.kill(pid, signal.SIGTERM)
    wait_for(lambda: app_pid(executable) is None, "Test App did not stop", timeout=10)


def main() -> int:
    """Stage an isolated App copy, run its scheduled offline workflow, and reopen it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-app", type=Path, required=True)
    parser.add_argument("--offline-engine-app", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if output.exists():
        raise FileExistsError("Use a fresh test output; existing files are never replaced.")
    output.mkdir(parents=True, mode=0o700)
    source = args.production_app.resolve(strict=True)
    offline = args.offline_engine_app.resolve(strict=True)
    if not (offline / "Contents/MacOS/research-radar-offline-test").is_file():
        raise ValueError("Expected the separately bundled offline test engine App")
    source_main = source / "Contents/MacOS/ResearchRadar"
    source_hash = hashlib.sha256(source_main.read_bytes()).hexdigest()
    app = output / "ResearchRadarOffline.app"
    subprocess.run(["/usr/bin/ditto", str(source), str(app)], check=True)
    nested = app / "Contents/Helpers/ResearchRadarEngine.app"
    subprocess.run(["/usr/bin/trash", str(nested)], check=True)
    subprocess.run(["/usr/bin/ditto", str(offline), str(nested)], check=True)
    binary_dir = nested / "Contents/MacOS"
    # Preserve the production native executable's expected engine location.
    (binary_dir / "research-radar-offline-test").rename(binary_dir / "research-radar-engine")
    nested_info = plistlib.loads((nested / "Contents/Info.plist").read_bytes())
    nested_info["CFBundleExecutable"] = "research-radar-engine"
    (nested / "Contents/Info.plist").write_bytes(plistlib.dumps(nested_info))
    info_path = app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["CFBundleIdentifier"] = "ai.research-radar.offline-acceptance"
    info["ResearchRadarDevelopmentBuild"] = True
    info_path.write_bytes(plistlib.dumps(info))
    subprocess.run([".venv/bin/python", "script/sign_macos_bundle.py", str(app)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)

    root = output / "app-data"
    configuration = json.loads(args.configuration.read_text())
    configuration["workspace_root"] = str(root / "workspace")
    configuration["start_at_login"] = False
    configuration["ui_language"] = "zh-Hans"
    topic = configuration["topics"][0]
    configuration["topics"] = [topic]
    topic["is_paused"] = False
    write_json(root / "config/app-config.json", configuration)
    write_json(root / "state/schedules.json", {
        "schema_version": 1,
        "schedules": [{
            "id": str(uuid4()), "topic_id": topic["id"], "hour": 0, "minute": 0,
            "is_enabled": True, "delivery_channels": ["wechat", "email"],
        }],
        "last_evaluated_at": None,
    })
    executable = app / "Contents/MacOS/ResearchRadar"
    index_path = root / "state/report-index.json"
    queue_path = root / "state/queue.json"

    def finished() -> bool:
        if not index_path.is_file() or not queue_path.is_file():
            return False
        jobs = json.loads(queue_path.read_text())["jobs"]
        return len(jobs) >= 3 and all(
            job["state"] not in {"pending", "running", "cancelling"} for job in jobs
        )

    started = time.monotonic()
    try:
        subprocess.run([
            "/usr/bin/open", "-n", "--env", f"RESEARCH_RADAR_DEV_ROOT={root}", str(app),
        ], check=True)
        wait_for(lambda: app_pid(executable), "Native test App did not launch")
        wait_for(finished, "Native scheduled offline workflow did not complete")
        elapsed = time.monotonic() - started
        index = index_path.read_bytes()
        reports = json.loads(index)["reports"]
        assert len(reports) == 1
        report = reports[0]
        draft = load_article_draft(Path(report["article_draft_path"]))
        assert draft.sections and report["publishable_claim_count"] > 0
        statuses = {item["channel"]: item["state"] for item in report["deliveries"]}
        assert statuses == {"wechat": "unknown", "email": "sent"}, statuses
        stop_app(executable)
        previous_queue_write = queue_path.stat().st_mtime_ns
        subprocess.run([
            "/usr/bin/open", "-n", "--env", f"RESEARCH_RADAR_DEV_ROOT={root}", str(app),
        ], check=True)
        pid = wait_for(lambda: app_pid(executable), "Native test App did not reopen")
        wait_for(
            lambda: queue_path.stat().st_mtime_ns > previous_queue_write,
            "Restart did not reconcile terminal artifacts",
        )
        time.sleep(3)
        assert app_pid(executable) == pid, "Restarted App exited before acceptance"
        assert index_path.read_bytes() == index
        assert len(json.loads(queue_path.read_text())["jobs"]) == 3
        children = subprocess.run(
            ["/usr/bin/pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
        )
        assert children.returncode == 1, children.stdout
        assert hashlib.sha256(source_main.read_bytes()).hexdigest() == source_hash
        write_json(output / "verification.json", {
            "measured_at": datetime.now(UTC).isoformat(),
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "working_tree_modified": bool(subprocess.check_output(
                ["git", "status", "--porcelain"], text=True
            ).strip()),
            "scope": "staged native App, scheduled frozen offline pipeline, restart",
            "elapsed_seconds": elapsed, "delivery_states": statuses,
            "report_count": len(reports), "restart_index_unchanged": True,
            "idle_children": [], "production_executable_unchanged": True,
        })
        print(output / "verification.json")
    finally:
        stop_app(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
