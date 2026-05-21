from research_radar.models import ReviewFinding, VerificationAction
from research_radar.pipeline.reporting import render_review_report


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
