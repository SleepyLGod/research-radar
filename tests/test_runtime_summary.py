from research_radar.pipeline.runtime import build_runtime_summary


def test_runtime_summary_marks_slow_stages_and_counts_cache() -> None:
    summary = build_runtime_summary(
        [
            {"stage": "run", "status": "created", "elapsed_seconds": 0.0},
            {
                "stage": "reader",
                "status": "succeeded",
                "elapsed_seconds": 310.0,
                "duration_seconds": 305.0,
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "cache_hit_count": 1,
                "cache_miss_count": 0,
            },
            {
                "stage": "verifier",
                "status": "succeeded",
                "elapsed_seconds": 330.0,
                "duration_seconds": 20.0,
                "provider": "codex",
                "model": "gpt-5.4",
                "cache_hit_count": 0,
                "cache_miss_count": 1,
            },
        ]
    )

    assert summary["total_elapsed_seconds"] == 330.0
    assert summary["slow_stage_count"] == 1
    assert summary["cache"] == {"hit_count": 1, "miss_count": 1}
    assert summary["stages"][0]["slow"] is True
    assert summary["stages"][1]["slow"] is False
