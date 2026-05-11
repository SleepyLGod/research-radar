"""Daily monitoring pipeline."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from research_radar.analysis.paper_reading import (
    model_paper_reading,
    reading_to_dict,
    render_deep_reading_report,
    validate_paper_reading,
)
from research_radar.analysis.providers import LLMProvider
from research_radar.analysis.review import model_review, rule_based_review
from research_radar.analysis.triage import heuristic_claims
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.wechat import render_wechat_html
from research_radar.config import AppConfig
from research_radar.discovery.base import DiscoveryConnector, DiscoveryContext
from research_radar.discovery.dedupe import dedupe_candidates
from research_radar.discovery.relevance import gate_relevant_sources
from research_radar.discovery.source_role import classify_source_role
from research_radar.discovery.source_selection import (
    select_deep_candidates,
    source_selection_score,
)
from research_radar.evidence.ledger import write_claims, write_evidence
from research_radar.exceptions import AnalysisError, DiscoveryError, IngestionError
from research_radar.ingestion.router import ingest_source
from research_radar.models import Artifact, ReviewFinding, SourceCandidate, dataclass_to_dict
from research_radar.pipeline.reporting import render_review_report
from research_radar.storage.files import write_json, write_jsonl, write_text
from research_radar.storage.runs import create_run_dir, update_manifest


def run_daily(
    root: Path,
    config: AppConfig,
    topic_id: str,
    connectors: list[DiscoveryConnector],
    *,
    verifier: LLMProvider | None = None,
    verifier_model: str | None = None,
    limit: int = 10,
    deep_reader: LLMProvider | None = None,
    deep_model: str | None = None,
    deep_limit: int = 0,
) -> Path:
    """Run the daily monitoring pipeline and return the run directory."""

    topic = config.topic(topic_id)
    run_dir, manifest = create_run_dir(root, topic_id, "daily")
    context = DiscoveryContext(topic=topic, limit=limit)
    findings: list[ReviewFinding] = []
    candidates: list[SourceCandidate] = []

    for connector in connectors:
        try:
            candidates.extend(connector.discover(context))
        except DiscoveryError as exc:
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message=f"{connector.name} discovery failed: {exc}",
                )
            )

    candidates = dedupe_candidates(candidates)
    candidates, relevant_candidates, relevance_findings = gate_relevant_sources(candidates, topic)
    candidates = [classify_source_role(candidate) for candidate in candidates]
    relevant_candidates = [
        candidate
        for candidate in candidates
        if candidate.metadata.get("relevance", {}).get("status") == "relevant"
    ]
    findings.extend(relevance_findings)
    summary_artifacts = [
        Artifact(
            source=candidate,
            text=candidate.summary or candidate.title,
            content_type="discovery-summary",
        )
        for candidate in relevant_candidates
    ]
    deep_artifacts: list[Artifact] = []
    readings = []
    deep_claims = []
    if deep_reader is not None and deep_limit > 0:
        selected_deep_candidates = select_deep_candidates(
            relevant_candidates,
            deep_limit,
            source_intent=topic.source_intent,
        )
        findings.extend(
            _deep_selection_findings(
                relevant_candidates,
                selected_deep_candidates,
                source_intent=topic.source_intent,
            )
        )
        for candidate in selected_deep_candidates:
            try:
                artifact = ingest_source(candidate, run_dir / "artifacts")
                deep_artifacts.append(artifact)
            except IngestionError as exc:
                findings.append(
                    ReviewFinding(
                        severity="warning",
                        message=f"Deep ingestion failed: {exc}",
                        claim_text=candidate.title,
                        metadata={"kind": "deep_ingestion_failed", "source_url": candidate.url},
                    )
                )
                continue
            try:
                reading = model_paper_reading(
                    artifact,
                    deep_reader,
                    model=deep_model or config.models.analyst,
                )
            except AnalysisError as exc:
                findings.append(
                    ReviewFinding(
                        severity="error",
                        message=f"Deep reading failed: {exc}",
                        claim_text=candidate.title,
                        metadata={"kind": "deep_reading_failed", "source_url": candidate.url},
                    )
                )
                continue
            readings.append(reading)
            reading_claims, reading_findings = validate_paper_reading(reading)
            deep_claims.extend(reading_claims)
            findings.extend(reading_findings)

    claims = deep_claims if deep_claims else heuristic_claims(summary_artifacts)
    claims, policy_findings = rule_based_review(claims)
    findings.extend(policy_findings)

    model_feedback = None
    if verifier is not None and claims and not deep_claims:
        claims, model_findings, model_feedback = model_review(
            claims,
            verifier,
            model=verifier_model or config.models.verifier,
            topic_id=topic.id,
            queries=topic.queries,
        )
        findings.extend(model_findings)
        claims, post_model_policy_findings = rule_based_review(claims)
        findings.extend(post_model_policy_findings)

    manifest = replace(
        manifest,
        source_count=len(candidates),
        claim_count=len(claims),
        publishable_claim_count=sum(1 for claim in claims if claim.is_publishable()),
        metadata={
            **manifest.metadata,
            "relevance": {
                "relevant_count": len(relevant_candidates),
                "needs_review_count": _relevance_count(candidates, "needs_review"),
                "irrelevant_count": _relevance_count(candidates, "irrelevant"),
            },
            "deep_reading": {
                "source_intent": topic.source_intent,
                "selected_count": len(selected_deep_candidates)
                if deep_reader is not None and deep_limit > 0
                else 0,
                "reading_count": len(readings),
                "deep_claim_count": len(deep_claims),
            },
        },
    )
    update_manifest(run_dir, manifest)
    write_jsonl(run_dir / "sources.jsonl", candidates)
    artifacts = _merge_artifacts(summary_artifacts, deep_artifacts)
    write_jsonl(
        run_dir / "artifacts.jsonl",
        [dataclass_to_dict(artifact) for artifact in artifacts],
    )
    write_jsonl(run_dir / "readings.jsonl", [reading_to_dict(reading) for reading in readings])
    write_claims(run_dir / "deep_claims.jsonl", deep_claims)
    write_claims(run_dir / "claims.jsonl", claims)
    write_evidence(run_dir / "evidence.jsonl", claims)
    write_jsonl(run_dir / "review_findings.jsonl", findings)
    draft = build_daily_draft(topic_id, relevant_candidates, claims)
    write_json(run_dir / "article_draft.json", dataclass_to_dict(draft))
    write_text(run_dir / "daily.md", render_markdown(draft))
    write_text(run_dir / "wechat.html", render_wechat_html(draft))
    write_text(run_dir / "deep_reading.md", render_deep_reading_report(readings))
    write_text(
        run_dir / "review_report.md",
        render_review_report(findings, model_feedback=model_feedback),
    )
    write_json(
        run_dir / "summary.json",
        {
            "run_dir": str(run_dir),
            "source_count": len(candidates),
            "relevant_source_count": len(relevant_candidates),
            "publishable_claim_count": sum(1 for claim in claims if claim.is_publishable()),
        },
    )
    return run_dir


def _relevance_count(candidates: list[SourceCandidate], status: str) -> int:
    return sum(
        1
        for candidate in candidates
        if candidate.metadata.get("relevance", {}).get("status") == status
    )


def _deep_selection_findings(
    candidates: list[SourceCandidate],
    selected: list[SourceCandidate],
    *,
    source_intent: str,
) -> list[ReviewFinding]:
    selected_urls = {candidate.url for candidate in selected}
    findings: list[ReviewFinding] = []
    for candidate in candidates:
        source_role = candidate.metadata.get("source_role", {})
        selected_text = "selected" if candidate.url in selected_urls else "not selected"
        severity = "info"
        if selected_text == "selected" and source_role.get("role") == "survey_or_list":
            severity = "warning"
        findings.append(
            ReviewFinding(
                severity=severity,
                message=(
                    "Deep-read source selection "
                    f"{selected_text}: role={source_role.get('role')}, "
                    f"priority={source_role.get('deep_read_priority')}, "
                    f"score={source_selection_score(candidate, source_intent=source_intent):.3f}, "
                    f"intent={source_intent}, "
                    f"reason={source_role.get('reason')}"
                ),
                claim_text=candidate.title,
                metadata={
                    "kind": "deep_source_selection",
                    "source_url": candidate.url,
                    "selected": candidate.url in selected_urls,
                    "role": source_role.get("role"),
                    "deep_read_priority": source_role.get("deep_read_priority"),
                    "selection_score": source_selection_score(
                        candidate,
                        source_intent=source_intent,
                    ),
                    "source_intent": source_intent,
                },
            )
        )
    return findings


def _merge_artifacts(
    summary_artifacts: list[Artifact],
    deep_artifacts: list[Artifact],
) -> list[Artifact]:
    deep_urls = {artifact.source.url for artifact in deep_artifacts}
    return [
        *deep_artifacts,
        *[artifact for artifact in summary_artifacts if artifact.source.url not in deep_urls],
    ]
