"""Shared deep-reading orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass

from research_radar.analysis.anchor_repair import (
    AnchorRepairAttempt,
    AnchorResolution,
    apply_anchor_repair,
)
from research_radar.analysis.paper_reading import (
    PaperReading,
    ReaderAttempt,
    model_paper_reading_with_attempts,
    validate_paper_reading,
)
from research_radar.analysis.paper_sections import PaperReadingPacket
from research_radar.analysis.providers import LLMProvider
from research_radar.models import Artifact, Claim, ReviewFinding


@dataclass(frozen=True)
class DeepReadingResult:
    """Result of running deep reading, validation, and anchor repair for one artifact."""

    reading: PaperReading
    claims: list[Claim]
    findings: list[ReviewFinding]
    anchor_resolutions: list[AnchorResolution]
    anchor_repairs: list[AnchorRepairAttempt]
    reader_attempts: list[ReaderAttempt]


def run_artifact_deep_reading(
    artifact: Artifact,
    reader: LLMProvider,
    *,
    model: str,
    language: str = "en",
    area_context: str | None = None,
    packet: PaperReadingPacket | None = None,
    anchor_repair_provider: LLMProvider | None = None,
    anchor_repair_model: str | None = None,
) -> DeepReadingResult:
    """Run model reading, claim validation, and quote-only anchor repair."""

    reading_result = model_paper_reading_with_attempts(
        artifact,
        reader,
        model=model,
        area_context=area_context,
        language=language,
        packet=packet,
    )
    claims, findings = validate_paper_reading(reading_result.reading, artifact)
    claims, anchor_resolutions, anchor_repairs, anchor_findings = apply_anchor_repair(
        claims,
        artifact,
        anchor_repair_provider,
        model=anchor_repair_model,
    )
    repaired_claim_texts = {
        repair.claim_text for repair in anchor_repairs if repair.status == "accepted"
    }
    findings = [
        finding
        for finding in findings
        if not (
            finding.metadata.get("kind") == "evidence_anchor_unmatched"
            and finding.claim_text in repaired_claim_texts
        )
    ]
    findings.extend(anchor_findings)
    return DeepReadingResult(
        reading=reading_result.reading,
        claims=claims,
        findings=findings,
        anchor_resolutions=anchor_resolutions,
        anchor_repairs=anchor_repairs,
        reader_attempts=reading_result.attempts,
    )
