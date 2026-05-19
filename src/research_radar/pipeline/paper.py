"""Single-paper golden-smoke pipeline."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from research_radar.analysis.paper_reading import (
    model_paper_reading,
    reading_to_dict,
    render_deep_reading_report,
    validate_paper_reading,
)
from research_radar.analysis.providers import LLMProvider
from research_radar.analysis.review import model_review
from research_radar.compose.paper import render_paper_brief
from research_radar.config import AppConfig, TopicConfig
from research_radar.evidence.ledger import write_claims, write_evidence
from research_radar.exceptions import ResearchRadarError
from research_radar.ingestion.router import ingest_source
from research_radar.models import RunManifest, SourceCandidate, SourceType
from research_radar.pipeline.reporting import render_review_report
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
    language: str | None = None,
) -> Path:
    """Run the single-paper pipeline and return the run directory."""

    topic = config.topic(topic_id)
    report_language = language or topic.report_language
    source = build_direct_paper_source(url)
    run_dir, manifest = _create_paper_run_dir(root, topic, source)
    artifact = ingest_source(source, run_dir / "artifacts")
    reading = model_paper_reading(
        artifact,
        reader,
        model=model,
        area_context=_area_context(topic),
        language=report_language,
    )
    claims, findings = validate_paper_reading(reading, artifact)
    model_feedback = None
    review_provider = verifier or reader
    review_model = verifier_model or model
    if claims and review_provider is not None:
        claims, model_findings, model_feedback = model_review(
            claims,
            review_provider,
            model=review_model,
            topic_id=topic.id,
            queries=topic.queries,
        )
        findings.extend(model_findings)
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
        },
    )

    write_json(run_dir / "manifest.json", manifest)
    write_jsonl(run_dir / "sources.jsonl", [source])
    write_jsonl(run_dir / "artifacts.jsonl", [artifact])
    write_jsonl(run_dir / "readings.jsonl", [reading_to_dict(reading)])
    write_claims(run_dir / "claims.jsonl", claims)
    write_evidence(run_dir / "evidence.jsonl", claims)
    write_jsonl(run_dir / "review_findings.jsonl", findings)
    write_text(
        run_dir / "deep_reading.md",
        render_deep_reading_report([reading], claims, language=report_language),
    )
    write_text(run_dir / "paper.md", render_paper_brief(reading, claims, language=report_language))
    write_text(
        run_dir / "review_report.md",
        render_review_report(findings, model_feedback=model_feedback),
    )
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
