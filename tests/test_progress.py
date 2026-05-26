from pathlib import Path

from research_radar.pipeline.progress import ProgressWriter
from research_radar.storage.files import read_jsonl


def test_progress_writer_redacts_and_truncates_sensitive_metadata(tmp_path: Path) -> None:
    progress_path = tmp_path / "run_progress.jsonl"
    writer = ProgressWriter(progress_path)
    long_prompt = "PROMPT: " + ("x" * 900)

    writer.record(
        "reader",
        "failed",
        error=(
            'app_secret="fake-secret-value-12345" token=fake-token-value-12345 '
            "/private/tmp/research-radar-smoke/run prompt follows: "
            f"{long_prompt}"
        ),
    )

    events = read_jsonl(progress_path)
    rendered = str(events[0])
    assert "fake-secret-value-12345" not in rendered
    assert "fake-token-value-12345" not in rendered
    assert "/private/tmp/research-radar-smoke" not in rendered
    assert "[REDACTED]" in rendered
    assert "[LOCAL_PATH]" in rendered
    assert "[truncated]" in rendered
    assert len(events[0]["error"]) <= 514


def test_progress_writer_write_failure_is_best_effort(
    monkeypatch,
    tmp_path: Path,
) -> None:
    writer = ProgressWriter(tmp_path / "run_progress.jsonl")

    def fail_open(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "open", fail_open)

    writer.record("artifacts", "failed", error="write failed")


def test_progress_writer_metadata_cannot_override_core_fields(tmp_path: Path) -> None:
    progress_path = tmp_path / "run_progress.jsonl"
    writer = ProgressWriter(progress_path)

    writer.record(
        "reader",
        "failed",
        elapsed_seconds=999,
    )

    events = read_jsonl(progress_path)
    assert events[0]["stage"] == "reader"
    assert events[0]["status"] == "failed"
    assert events[0]["elapsed_seconds"] != 999
