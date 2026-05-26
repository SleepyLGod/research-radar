"""Single-paper golden-smoke pipeline."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from research_radar.analysis.anchor_repair import AnchorRepairAttempt
from research_radar.analysis.deep_reading import run_artifact_deep_reading
from research_radar.analysis.model_cache import (
    merge_cache_deltas,
    provider_cache_delta,
    provider_cache_stats,
)
from research_radar.analysis.paper_reading import (
    reading_to_dict,
    render_deep_reading_report,
)
from research_radar.analysis.paper_sections import (
    build_paper_sections,
    build_reading_packet,
    render_reading_packet,
)
from research_radar.analysis.providers import LLMProvider
from research_radar.analysis.review import model_review_publishable_claims, rule_based_review
from research_radar.compose.paper import render_paper_brief
from research_radar.config import AppConfig, TopicConfig
from research_radar.evidence.ledger import write_claims, write_evidence
from research_radar.exceptions import ResearchRadarError
from research_radar.ingestion.router import ingest_source
from research_radar.models import RunManifest, SourceCandidate, SourceType
from research_radar.pipeline.progress import ProgressWriter
from research_radar.pipeline.reporting import render_review_report
from research_radar.pipeline.runtime import build_runtime_summary
from research_radar.storage.files import ensure_dir, write_json, write_jsonl, write_text
from research_radar.storage.runs import make_run_id


def run_paper(
    root: Path,
    config: AppConfig,
    topic_id: str,
    url: str,
    reader: LLMProvider,
    *,
    model: str,
    verifier: LLMProvider | None = None,
    verifier_model: str | None = None,
    anchor_repair_provider: LLMProvider | None = None,
    anchor_repair_model: str | None = None,
    language: str | None = None,
) -> Path:
    """Run the single-paper pipeline and return the run directory."""

    topic = config.topic(topic_id)
    report_language = language or topic.report_language
    source = build_direct_paper_source(url)
    run_dir, manifest = _create_paper_run_dir(root, topic, source)
    progress = ProgressWriter(run_dir / "run_progress.jsonl")
    progress.record("run", "created", topic_id=topic_id, mode="paper")
    progress.record("ingestion", "started", source_title=source.title, source_url=source.url)
    try:
        artifact = ingest_source(source, run_dir / "artifacts")
    except ResearchRadarError as exc:
        progress.record("ingestion", "failed", error_type=type(exc).__name__, error=str(exc))
        _write_failed_run(run_dir, manifest, "ingestion", None, None, exc)
        raise
    progress.record(
        "ingestion",
        "succeeded",
        source_title=source.title,
        source_url=source.url,
        content_type=artifact.content_type,
    )
    paper_sections = build_paper_sections(artifact)
    reading_packet = build_reading_packet(artifact, sections=paper_sections)
    progress.record(
        "reader",
        "started",
        source_title=source.title,
        source_url=source.url,
        provider=reader.name,
        model=model,
    )
    reader_cache_before = provider_cache_stats(reader)
    repair_cache_before = provider_cache_stats(anchor_repair_provider)
    try:
        deep_result = run_artifact_deep_reading(
            artifact,
            reader,
            model=model,
            area_context=_area_context(topic),
            language=report_language,
            packet=reading_packet,
            anchor_repair_provider=anchor_repair_provider,
            anchor_repair_model=anchor_repair_model,
        )
    except ResearchRadarError as exc:
        progress.record(
            "reader",
            "failed",
            source_title=source.title,
            source_url=source.url,
            provider=reader.name,
            model=model,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        _write_failed_run(run_dir, manifest, "reader", reader.name, model, exc)
        raise
    reader_cache_delta = merge_cache_deltas(
        provider_cache_delta(reader_cache_before, reader),
        provider_cache_delta(repair_cache_before, anchor_repair_provider),
    )
    progress.record(
        "reader",
        "succeeded",
        source_title=source.title,
        source_url=source.url,
        provider=reader.name,
        model=model,
        claim_count=len(deep_result.claims),
        anchor_repair_target_count=_anchor_repair_target_count(deep_result.anchor_repairs),
        anchor_repair_skipped_count=_anchor_repair_skipped_count(deep_result.anchor_repairs),
        **reader_cache_delta,
    )
    reading = deep_result.reading
    claims = deep_result.claims
    findings = deep_result.findings
    model_feedback = None
    verification_actions = []
    review_provider = verifier or reader
    review_model = verifier_model or model
    if claims and review_provider is not None:
        progress.record(
            "verifier",
            "started",
            provider=review_provider.name,
            model=review_model,
            claim_count=len(claims),
            verifier_input_count=sum(1 for claim in claims if claim.is_publishable()),
            verifier_skipped_claim_count=sum(1 for claim in claims if not claim.is_publishable()),
        )
        verifier_cache_before = provider_cache_stats(review_provider)
        try:
            review_result = model_review_publishable_claims(
                claims,
                review_provider,
                model=review_model,
                topic_id=topic.id,
                queries=topic.queries,
            )
            claims = review_result.claims
            model_findings = review_result.findings
            model_feedback = review_result.raw_feedback
            verification_actions = review_result.actions
        except ResearchRadarError as exc:
            progress.record(
                "verifier",
                "failed",
                provider=review_provider.name,
                model=review_model,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            _write_failed_run(
                run_dir,
                manifest,
                "verifier",
                review_provider.name,
                review_model,
                exc,
            )
            raise
        findings.extend(model_findings)
        claims, post_model_findings = rule_based_review(claims)
        findings.extend(post_model_findings)
        progress.record(
            "verifier",
            "succeeded",
            provider=review_provider.name,
            model=review_model,
            publishable_claim_count=sum(1 for claim in claims if claim.is_publishable()),
            action_count=len(verification_actions),
            verifier_input_count=review_result.reviewed_count,
            verifier_skipped_claim_count=review_result.skipped_count,
            **provider_cache_delta(verifier_cache_before, review_provider),
        )
    manifest = RunManifest(
        run_id=manifest.run_id,
        topic_id=topic_id,
        mode="paper",
        created_at=manifest.created_at,
        source_count=1,
        claim_count=len(claims),
        publishable_claim_count=sum(1 for claim in claims if claim.is_publishable()),
        metadata={
            "paper_url": source.url,
            "canonical_id": source.canonical_id,
            "reading_count": 1,
            "report_language": report_language,
            "paper_reading_packet": {
                "chunk_count": len(reading_packet.chunks),
                "warnings": reading_packet.warnings,
            },
            "anchor_repair": {
                "resolution_count": len(deep_result.anchor_resolutions),
                "repair_attempt_count": len(deep_result.anchor_repairs),
                "accepted_count": sum(
                    1 for repair in deep_result.anchor_repairs if repair.status == "accepted"
                ),
            },
        },
    )

    progress.record("artifacts", "started")
    write_json(run_dir / "manifest.json", manifest)
    write_jsonl(run_dir / "sources.jsonl", [source])
    write_jsonl(run_dir / "artifacts.jsonl", [artifact])
    write_jsonl(run_dir / "paper_sections.jsonl", paper_sections)
    write_text(run_dir / "paper_reading_input.md", render_reading_packet(reading_packet))
    write_jsonl(run_dir / "reader_attempts.jsonl", deep_result.reader_attempts)
    write_jsonl(run_dir / "readings.jsonl", [reading_to_dict(reading)])
    write_jsonl(run_dir / "anchor_resolution.jsonl", deep_result.anchor_resolutions)
    write_jsonl(run_dir / "anchor_repair.jsonl", deep_result.anchor_repairs)
    write_claims(run_dir / "claims.jsonl", claims)
    write_evidence(run_dir / "evidence.jsonl", claims)
    write_jsonl(run_dir / "review_findings.jsonl", findings)
    write_jsonl(run_dir / "verification_actions.jsonl", verification_actions)
    write_text(
        run_dir / "deep_reading.md",
        render_deep_reading_report([reading], claims, language=report_language),
    )
    write_text(run_dir / "paper.md", render_paper_brief(reading, claims, language=report_language))
    write_text(
        run_dir / "review_report.md",
        render_review_report(
            findings,
            model_feedback=model_feedback,
            verification_actions=verification_actions,
            reader_attempts=deep_result.reader_attempts,
        ),
    )
    progress.record(
        "artifacts",
        "completed",
        source_count=1,
        publishable_claim_count=sum(1 for claim in claims if claim.is_publishable()),
    )
    progress.record("run", "completed")
    write_json(run_dir / "runtime_summary.json", build_runtime_summary(progress.events))
    return run_dir


def build_direct_paper_source(url: str) -> SourceCandidate:
    """Build a normalized paper candidate from a direct paper URL."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ResearchRadarError("Paper URL must be an absolute http(s) URL.")
    canonical_id = _paper_id(parsed.path)
    title = f"arXiv {canonical_id}" if canonical_id else "Direct paper"
    return SourceCandidate(
        title=title,
        url=url,
        canonical_id=canonical_id,
        source_type=SourceType.PAPER,
        source_name="direct",
        summary="Direct paper URL supplied for a single-paper run.",
        score=1.0,
        metadata={"input_url": url},
    )


def _create_paper_run_dir(
    root: Path,
    topic: TopicConfig,
    source: SourceCandidate,
) -> tuple[Path, RunManifest]:
    suffix = source.canonical_id or "direct-paper"
    run_id = make_run_id(f"{topic.id}-paper-{suffix}")
    run_dir = ensure_dir(root / "runs" / run_id)
    manifest = RunManifest(run_id=run_id, topic_id=topic.id, mode="paper")
    write_json(run_dir / "manifest.json", manifest)
    return run_dir, manifest


def _write_failed_run(
    run_dir: Path,
    manifest: RunManifest,
    stage: str,
    provider: str | None,
    model: str | None,
    exc: ResearchRadarError,
) -> None:
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
    failed_manifest = RunManifest(
        run_id=manifest.run_id,
        topic_id=manifest.topic_id,
        mode=manifest.mode,
        created_at=manifest.created_at,
        metadata={**manifest.metadata, "failure": failure},
    )
    write_json(run_dir / "manifest.json", failed_manifest)
    write_json(run_dir / "run_error.json", failure)


def _paper_id(path: str) -> str | None:
    match = re.search(r"/(?:pdf|abs)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", path)
    if match:
        return match.group(1)
    filename = Path(path).name
    if filename.lower().endswith(".pdf") and filename[:-4]:
        return filename[:-4]
    return None


def _area_context(topic: TopicConfig) -> str:
    queries = ", ".join(topic.queries)
    return f"Topic: {topic.id}. User queries: {queries}."


def _anchor_repair_target_count(repairs: list[AnchorRepairAttempt]) -> int:
    return sum(1 for repair in repairs if repair.status != "skipped")


def _anchor_repair_skipped_count(repairs: list[AnchorRepairAttempt]) -> int:
    return sum(1 for repair in repairs if repair.status == "skipped")
