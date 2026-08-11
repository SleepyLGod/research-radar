from datetime import UTC, datetime

from research_radar.storage.runs import create_run_dir, make_run_id


def test_make_run_id_includes_unique_attempt_time() -> None:
    run_id = make_run_id(
        "agent memory",
        now=datetime(2026, 8, 10, 14, 30, 52, 123456, tzinfo=UTC),
    )

    assert run_id == "2026-08-10-143052123456-agent-memory"


def test_same_day_runs_use_different_directories(tmp_path) -> None:
    first_dir, first_manifest = create_run_dir(tmp_path, "agent-memory", "daily")
    second_dir, second_manifest = create_run_dir(tmp_path, "agent-memory", "daily")

    assert first_dir != second_dir
    assert first_manifest.run_id != second_manifest.run_id
    assert first_manifest.report_date == second_manifest.report_date
    assert first_manifest.run_id.startswith(f"{first_manifest.report_date}-")
    assert first_manifest.attempt_id != second_manifest.attempt_id
