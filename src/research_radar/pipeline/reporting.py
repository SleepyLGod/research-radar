"""Pipeline report rendering and failure persistence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from research_radar.analysis.paper_reading import ReaderAttempt, reading_to_dict
from research_radar.analysis.review import PublicationReviewError
from research_radar.evidence.ledger import write_claims
from research_radar.exceptions import ResearchRadarError
from research_radar.models import ReviewFinding, RunManifest, VerificationAction
from research_radar.storage.files import write_json, write_jsonl, write_text


def write_failed_run(
    run_dir: Path,
    manifest: RunManifest,
    stage: str,
    provider: str | None,
    model: str | None,
    exc: ResearchRadarError,
) -> None:
    """Persist a failed-run envelope and any completed publication review evidence."""
    failure = {
        "stage": stage,
        "provider": provider,
        "model": model,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    diagnostics = getattr(exc, "diagnostics", None)
    if isinstance(diagnostics, dict):
        failure["transport"] = diagnostics
    failed_manifest = replace(
        manifest,
        metadata={**manifest.metadata, "failure": failure},
    )
    write_json(run_dir / "manifest.json", failed_manifest)
    write_json(run_dir / "run_error.json", failure)
    if isinstance(exc, PublicationReviewError):
        write_text(run_dir / "final_review.json", exc.raw_feedback)
        write_claims(run_dir / "final_review_claims.jsonl", exc.claims)
        write_jsonl(run_dir / "final_review_readings.jsonl",
                    [reading_to_dict(reading) for reading in exc.readings])


def render_review_report(
    findings: list[ReviewFinding],
    *,
    model_feedback: str | None = None,
    verification_actions: list[VerificationAction] | None = None,
    reader_attempts: list[ReaderAttempt] | None = None,
) -> str:
    """Render review findings as Markdown."""

    lines = ["# Review Report", ""]
    actions = verification_actions or []
    attempts = reader_attempts or []
    if not findings and not model_feedback and not actions and not attempts:
        lines.append("No review findings.")
    if attempts:
        lines.extend(["## Reader Attempts", ""])
        for attempt in attempts:
            detail = f": {attempt.error_message}" if attempt.error_message else ""
            lines.append(
                f"- **{attempt.status}** attempt {attempt.attempt_index} "
                f"({attempt.provider}/{attempt.model}){detail}"
            )
        lines.append("")
    groups = _group_findings(findings)
    rendered_sections = []
    for title, section_findings in groups:
        if not section_findings:
            continue
        rendered_sections.append(title)
        lines.extend([f"## {title}", ""])
        for finding in section_findings:
            target = f" ({finding.claim_text})" if finding.claim_text else ""
            lines.append(f"- **{finding.severity}**{target}: {finding.message}")
        lines.append("")
    if actions:
        lines.extend(["## Verification Actions", ""])
        for action in actions:
            target = f" (claim {action.claim_index})" if action.claim_index else ""
            query = f" query={action.query}" if action.query else ""
            source = f" source={action.source_url}" if action.source_url else ""
            lines.append(
                f"- **{action.action_type}**{target}: {action.reason}{query}{source}"
            )
        lines.append("")
    if model_feedback:
        heading = (
            "### Raw Model Feedback"
            if "Model Review" in rendered_sections
            else "## Model Review"
        )
        lines.extend([heading, "", model_feedback.strip()])
    return "\n".join(lines).strip() + "\n"


def _group_findings(
    findings: list[ReviewFinding],
) -> list[tuple[str, list[ReviewFinding]]]:
    groups = {
        "Anchor Resolution": [],
        "Anchor Repair": [],
        "Evidence Issues": [],
        "Needs Review": [],
        "Filtered Candidates": [],
        "Deep Selection": [],
        "Model Review": [],
    }
    for finding in findings:
        groups[_section_for(finding)].append(finding)
    return [(title, groups[title]) for title in groups]


def _section_for(finding: ReviewFinding) -> str:
    kind = str(finding.metadata.get("kind", ""))
    if kind == "anchor_resolution":
        return "Anchor Resolution"
    if kind.startswith("anchor_repair"):
        return "Anchor Repair"
    if kind.startswith("model_review"):
        return "Model Review"
    if kind == "deep_source_selection":
        return "Deep Selection"
    if kind == "daily_report_gate":
        return "Filtered Candidates"
    if kind == "source_relevance":
        if finding.metadata.get("source_status") == "needs_review":
            return "Needs Review"
        return "Filtered Candidates"
    if "evidence" in kind or finding.severity == "error":
        return "Evidence Issues"
    if finding.severity == "warning":
        return "Needs Review"
    return "Filtered Candidates"
