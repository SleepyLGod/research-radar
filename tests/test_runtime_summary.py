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
                "anchor_repair_target_count": 2,
                "anchor_repair_skipped_count": 1,
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
                "verifier_input_count": 7,
                "verifier_skipped_claim_count": 3,
                "cache_hit_count": 0,
                "cache_miss_count": 1,
            },
            {
                "stage": "localization",
                "status": "completed",
                "elapsed_seconds": 344.0,
                "duration_seconds": 14.0,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "status_detail": "failed",
                "cache_hit_count": 1,
                "cache_miss_count": 0,
            },
            {
                "stage": "explanation_policy",
                "status": "warning",
                "elapsed_seconds": 345.0,
                "paragraph_count": 8,
                "kept_count": 5,
                "dropped_count": 3,
                "fallback_section_count": 2,
            },
        ]
    )

    assert summary["total_elapsed_seconds"] == 345.0
    assert summary["slow_stage_count"] == 1
    assert summary["cache"] == {"hit_count": 2, "miss_count": 1}
    assert summary["stages"][0]["slow"] is True
    assert summary["stages"][0]["anchor_repair_target_count"] == 2
    assert summary["stages"][0]["anchor_repair_skipped_count"] == 1
    assert summary["stages"][1]["slow"] is False
    assert summary["stages"][1]["verifier_input_count"] == 7
    assert summary["stages"][1]["verifier_skipped_claim_count"] == 3
    assert summary["stages"][2]["stage"] == "localization"
    assert summary["stages"][2]["slow"] is False
    assert summary["stages"][2]["status_detail"] == "failed"
    assert summary["explanation_policy"] == {
        "paragraph_count": 8,
        "kept_count": 5,
        "dropped_count": 3,
        "fallback_section_count": 2,
    }
