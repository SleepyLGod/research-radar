from pathlib import Path

from research_radar.exceptions import AnalysisError
from research_radar.models import ReviewFinding, RunManifest, VerificationAction
from research_radar.pipeline.reporting import render_review_report, write_failed_run
from research_radar.storage.files import read_json


def test_failed_run_preserves_existing_manifest_fields(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id="daily-run", topic_id="memory", mode="daily",
        report_date="2026-11-06", attempt_id="attempt-2",
        source_count=7, claim_count=9, publishable_claim_count=4,
        metadata={"report_language": "zh"},
    )

    write_failed_run(tmp_path, manifest, "verifier", "offline", "offline-model",
                     AnalysisError("Final review failed."))

    saved = read_json(tmp_path / "manifest.json")
    assert saved["run_id"] == "daily-run"
    assert saved["topic_id"] == "memory"
    assert saved["mode"] == "daily"
    assert saved["report_date"] == "2026-11-06"
    assert saved["attempt_id"] == "attempt-2"
    assert saved["created_at"] == manifest.created_at.isoformat()
    assert saved["source_count"] == 7
    assert saved["claim_count"] == 9
    assert saved["publishable_claim_count"] == 4
    assert saved["metadata"]["report_language"] == "zh"
    assert saved["metadata"]["failure"] == read_json(tmp_path / "run_error.json")
    assert manifest.metadata == {"report_language": "zh"}


def test_review_report_groups_filtered_candidates_separately() -> None:
    report = render_review_report(
        [
            ReviewFinding(
                severity="info",
                message="Daily report gate suppressed source: list source",
                claim_text="Awesome Agent Memory",
                metadata={"kind": "daily_report_gate"},
            ),
            ReviewFinding(
                severity="warning",
                message="Source relevance gate marked candidate as needs_review.",
                claim_text="Generic LLM Benchmark",
                metadata={"kind": "source_relevance", "source_status": "needs_review"},
            ),
            ReviewFinding(
                severity="warning",
                message="Some evidence anchors were not found in the ingested text.",
                claim_text="Unsupported claim",
                metadata={"kind": "evidence_anchor_unmatched"},
            ),
            ReviewFinding(
                severity="info",
                message="Deep-read source selection selected.",
                claim_text="Memory Paper",
                metadata={"kind": "deep_source_selection"},
            ),
        ]
    )

    assert "## Filtered Candidates" in report
    assert "## Needs Review" in report
    assert "## Evidence Issues" in report
    assert "## Deep Selection" in report
    assert report.index("## Evidence Issues") < report.index("## Needs Review")
    assert report.index("## Filtered Candidates") < report.index("## Deep Selection")


def test_review_report_renders_verification_actions() -> None:
    report = render_review_report(
        [],
        verification_actions=[
            VerificationAction(
                action_type="needs_primary_source",
                reason="Check the benchmark claim against the original paper.",
                claim_index=2,
                query="LongMemEval original benchmark",
                source_url="https://example.com/paper",
            )
        ],
    )

    assert "## Verification Actions" in report
    assert "**needs_primary_source** (claim 2)" in report
    assert "LongMemEval original benchmark" in report


def test_review_report_groups_anchor_resolution_and_repair() -> None:
    report = render_review_report(
        [
            ReviewFinding(
                severity="error",
                message="Anchor resolution failed: missing evidence",
                claim_text="Experiment claim",
                metadata={"kind": "anchor_resolution"},
            ),
            ReviewFinding(
                severity="warning",
                message="Anchor repair rejected: quote not found",
                claim_text="Experiment claim",
                metadata={"kind": "anchor_repair_rejected"},
            ),
        ]
    )

    assert "## Anchor Resolution" in report
    assert "## Anchor Repair" in report
    assert report.index("## Anchor Resolution") < report.index("## Anchor Repair")
