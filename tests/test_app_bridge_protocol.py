import json
from pathlib import Path
from uuid import uuid4

import pytest

from research_radar.app_bridge.protocol import ProtocolError, load_request


def _write_request(job_dir: Path, **overrides: object) -> Path:
    request_id = job_dir.name
    payload: dict[str, object] = {
        "schema_version": 1,
        "request_id": request_id,
        "command": "preflight",
        "created_at": "2026-08-30T10:00:00Z",
        "app_support_root": str(job_dir.parent.parent),
        "config_path": None,
        "payload": {"live_probe": False},
    }
    payload.update(overrides)
    path = job_dir / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _private_job(tmp_path: Path) -> Path:
    root = tmp_path / "ResearchRadar-Dev"
    root.mkdir(mode=0o700)
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700)
    job = jobs / str(uuid4())
    job.mkdir(mode=0o700)
    return job


def test_load_request_accepts_local_preflight(tmp_path: Path) -> None:
    job_dir = _private_job(tmp_path)

    request = load_request(_write_request(job_dir), job_dir=job_dir)

    assert request.schema_version == 1
    assert request.command == "preflight"
    assert request.payload.live_probe is False
    assert request.config_path is None


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"schema_version": 2}, "Unsupported schema version"),
        ({"command": "run_daily"}, "Unsupported command"),
        ({"request_id": str(uuid4())}, "must match the job directory"),
        ({"payload": {"live_probe": True}}, "must not perform a live probe"),
        ({"unexpected": True}, "Unknown request field"),
    ],
)
def test_load_request_rejects_invalid_envelope(
    tmp_path: Path, override: dict[str, object], message: str
) -> None:
    job_dir = _private_job(tmp_path)

    with pytest.raises(ProtocolError, match=message):
        load_request(_write_request(job_dir, **override), job_dir=job_dir)


@pytest.mark.parametrize(
    "secret_field",
    [
        "api_key",
        "password",
        "secret_value",
        "token",
        "api_key_value",
        "token_value",
        "authorization",
        "cookie",
    ],
)
def test_load_request_rejects_secret_value_fields(tmp_path: Path, secret_field: str) -> None:
    job_dir = _private_job(tmp_path)

    with pytest.raises(ProtocolError, match="Secret values are not allowed"):
        load_request(
            _write_request(job_dir, payload={"live_probe": False, secret_field: "hidden"}),
            job_dir=job_dir,
        )


def test_load_request_rejects_config_path_outside_app_root(tmp_path: Path) -> None:
    job_dir = _private_job(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ProtocolError, match="config_path must stay within app_support_root"):
        load_request(
            _write_request(job_dir, config_path=str(outside)),
            job_dir=job_dir,
        )


def test_load_request_rejects_non_private_job_directory(tmp_path: Path) -> None:
    job_dir = _private_job(tmp_path)
    job_dir.chmod(0o755)

    with pytest.raises(ProtocolError, match="owner-only"):
        load_request(_write_request(job_dir), job_dir=job_dir)


def test_load_request_rejects_non_writable_job_directory(tmp_path: Path) -> None:
    job_dir = _private_job(tmp_path)
    request_path = _write_request(job_dir)
    job_dir.chmod(0o500)

    with pytest.raises(ProtocolError, match="must be writable"):
        load_request(request_path, job_dir=job_dir)
