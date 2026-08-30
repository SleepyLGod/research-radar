#!/usr/bin/env python3
"""Run a frozen foundation preflight with a private project-local test root."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def main() -> int:
    """Execute and validate one frozen preflight."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    jobs = root / "jobs"
    jobs.mkdir(exist_ok=True, mode=0o700)
    os.chmod(jobs, 0o700)
    request_id = str(uuid4())
    job = jobs / request_id
    job.mkdir(mode=0o700)
    paths = {
        "request": job / "request.json",
        "events": job / "events.jsonl",
        "result": job / "result.json",
        "error": job / "error.json",
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
    result = subprocess.run(
        [
            str(args.engine),
            "--request",
            str(paths["request"]),
            "--events",
            str(paths["events"]),
            "--result",
            str(paths["result"]),
            "--error",
            str(paths["error"]),
        ],
        env={"HOME": str(root), "LANG": "en_US.UTF-8", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        if not detail and paths["error"].is_file():
            detail = paths["error"].read_text(encoding="utf-8").strip()
        if not detail:
            detail = "The engine did not write an error artifact."
        raise SystemExit(f"Frozen engine exited with code {result.returncode}: {detail}")
    payload = json.loads(paths["result"].read_text(encoding="utf-8"))
    dependencies = payload["preflight"]["dependencies"]
    if not all(item["available"] for item in dependencies.values()):
        raise SystemExit("Frozen preflight reported a missing dependency.")
    print(json.dumps({"duration_seconds": round(time.monotonic() - started, 3), **payload}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
