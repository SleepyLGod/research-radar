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
from research_radar.analysis.research_plan import build_research_plan, research_plan_to_dict
from research_radar.analysis.review import model_review, rule_based_review
from research_radar.analysis.source_gist import attach_source_gists
from research_radar.analysis.triage import heuristic_claims
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.synthesis import render_synthesis_outline
from research_radar.compose.wechat import render_wechat_html
from research_radar.config import AppConfig, TopicConfig
from research_radar.discovery.base import DiscoveryConnector
from research_radar.discovery.orchestrator import DiscoveryOrchestrator
from research_radar.discovery.relevance import gate_relevant_sources
from research_radar.discovery.source_quality import (
    paper_coverage_diagnostics,
    score_source_quality,
)
from research_radar.discovery.source_role import classify_source_role
from research_radar.discovery.source_selection import (
    select_deep_candidates,
    source_selection_score,
)
from research_radar.discovery.wide_scan import (
    build_source_selection_report,
    build_wide_scan,
)
from research_radar.evidence.ledger import write_claims, write_evidence
from research_radar.exceptions import AnalysisError, IngestionError
from research_radar.ingestion.router import ingest_source
from research_radar.models import (
    Artifact,
    Claim,
    ReviewFinding,
    SourceCandidate,
    dataclass_to_dict,
)
from research_radar.pipeline.reporting import render_review_report
from research_radar.storage.files import write_json, write_jsonl, write_text
from research_radar.storage.runs import create_run_dir, update_manifest
from research_radar.storage.source_history import (
    annotate_source_history,
    is_reportable_source,
)


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
    language: str | None = None,
) -> Path:
    """Run the daily monitoring pipeline and return the run directory."""

    topic = config.topic(topic_id)
    report_language = language or topic.report_language
    run_dir, manifest = create_run_dir(root, topic_id, "daily")
    findings: list[ReviewFinding] = []
    research_plan = build_research_plan(topic, trusted_domains=config.discovery.trusted_domains)
    discovery = DiscoveryOrchestrator(connectors).discover(
        topic,
        limit=limit,
        trusted_domains=config.discovery.trusted_domains,
        research_plan=research_plan,
    )
    candidates = discovery.candidates
    findings.extend(discovery.findings)
    candidates, relevant_candidates, relevance_findings = gate_relevant_sources(candidates, topic)
    candidates = [score_source_quality(classify_source_role(candidate)) for candidate in candidates]
    candidates, history_report = annotate_source_history(
        root,
        topic.id,
        candidates,
        run_id=manifest.run_id,
    )
    candidates, daily_report_findings = _apply_daily_report_gate(candidates, topic)
    findings.extend(daily_report_findings)
    relevant_candidates = [
        candidate
        for candidate in candidates
        if candidate.metadata.get("relevance", {}).get("status") == "relevant"
    ]
    reportable_candidates = [
        candidate
        for candidate in relevant_candidates
        if is_reportable_source(candidate) and _passes_daily_report_gate(candidate)
    ]
    reportable_candidates = attach_source_gists(
        reportable_candidates,
        provider=verifier,
        model=verifier_model or config.models.scout,
        language=report_language,
    )
    candidates = _replace_candidates(candidates, reportable_candidates)
    relevant_candidates = [
        candidate
        for candidate in candidates
        if candidate.metadata.get("relevance", {}).get("status") == "relevant"
    ]
    reportable_candidates = [
        candidate
        for candidate in relevant_candidates
        if is_reportable_source(candidate) and _passes_daily_report_gate(candidate)
    ]
    findings.extend(relevance_findings)
    summary_artifacts = [
        Artifact(
            source=candidate,
            text=candidate.summary or candidate.title,
            content_type="discovery-summary",
        )
        for candidate in reportable_candidates
    ]
    deep_artifacts: list[Artifact] = []
    readings = []
    deep_claims = []
    selected_deep_candidates: list[SourceCandidate] = []
    deep_reading_status_by_url: dict[str, str] = {}
    deep_required = deep_reader is not None and deep_limit > 0
    if deep_required:
        deep_candidate_pool = select_deep_candidates(
            reportable_candidates,
            len(reportable_candidates),
            source_intent=topic.source_intent,
        )
        for candidate in deep_candidate_pool:
            if len(selected_deep_candidates) >= deep_limit:
                break
            try:
                artifact = ingest_source(candidate, run_dir / "artifacts")
                deep_artifacts.append(artifact)
            except IngestionError as exc:
                deep_reading_status_by_url[candidate.url] = "ingestion_failed"
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
                    language=report_language,
                )
            except AnalysisError as exc:
                deep_reading_status_by_url[candidate.url] = "reading_failed"
                findings.append(
                    ReviewFinding(
                        severity="error",
                        message=f"Deep reading failed: {exc}",
                        claim_text=candidate.title,
                        metadata={"kind": "deep_reading_failed", "source_url": candidate.url},
                    )
                )
                continue
            selected_deep_candidates.append(candidate)
            deep_reading_status_by_url[candidate.url] = "succeeded"
            readings.append(reading)
            reading_claims, reading_findings = validate_paper_reading(reading, artifact)
            deep_claims.extend(reading_claims)
            findings.extend(reading_findings)
        findings.extend(
            _deep_selection_findings(
                reportable_candidates,
                selected_deep_candidates,
                source_intent=topic.source_intent,
                deep_reading_status_by_url=deep_reading_status_by_url,
            )
        )

    paper_coverage = paper_coverage_diagnostics(candidates, source_intent=topic.source_intent)
    findings.extend(_quality_gate_findings(paper_coverage))
    claims, fallback_findings = _daily_claims(
        deep_required=deep_required,
        selected_deep_candidates=selected_deep_candidates,
        readings=readings,
        deep_claims=deep_claims,
        summary_artifacts=summary_artifacts,
    )
    findings.extend(fallback_findings)
    claims, policy_findings = rule_based_review(claims)
    findings.extend(policy_findings)

    model_feedback = None
    if verifier is not None and claims:
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
            "query_expansion": discovery.query_expansions,
            "research_plan": {
                "paper_query_count": len(research_plan.paper_queries),
                "web_query_count": len(research_plan.web_queries),
            },
            "discovery": {
                "stage_counts": discovery.stage_counts,
                "provider_counts": discovery.provider_counts,
                "trusted_domains": config.discovery.trusted_domains,
            },
            "relevance": {
                "relevant_count": len(relevant_candidates),
                "needs_review_count": _relevance_count(candidates, "needs_review"),
                "irrelevant_count": _relevance_count(candidates, "irrelevant"),
            },
            "source_history": {
                "counts": history_report["counts"],
                "reportable_count": len(reportable_candidates),
                "omitted_seen_count": len(history_report["omitted_seen_sources"]),
            },
            "quality_gate": paper_coverage,
            "deep_reading": {
                "source_intent": topic.source_intent,
                "selected_count": len(selected_deep_candidates),
                "reading_count": len(readings),
                "deep_claim_count": len(deep_claims),
            },
            "report_language": report_language,
        },
    )
    update_manifest(run_dir, manifest)
    write_json(run_dir / "research_plan.json", research_plan_to_dict(research_plan))
    write_jsonl(run_dir / "sources.jsonl", candidates)
    write_json(run_dir / "source_history_report.json", history_report)
    write_json(run_dir / "wide_scan.json", build_wide_scan(candidates))
    write_json(
        run_dir / "source_selection.json",
        build_source_selection_report(
            reportable_candidates,
            selected_deep_candidates,
            source_intent=topic.source_intent,
            deep_reading_status_by_url=deep_reading_status_by_url,
        ),
    )
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
    draft = build_daily_draft(topic_id, reportable_candidates, claims, language=report_language)
    write_json(run_dir / "article_draft.json", dataclass_to_dict(draft))
    write_text(
        run_dir / "synthesis_outline.md",
        render_synthesis_outline(topic_id, reportable_candidates, claims, readings),
    )
    write_text(run_dir / "daily.md", render_markdown(draft))
    write_text(run_dir / "wechat.html", render_wechat_html(draft))
    write_text(
        run_dir / "deep_reading.md",
        render_deep_reading_report(readings, claims, language=report_language),
    )
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
            "reportable_source_count": len(reportable_candidates),
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


def _apply_daily_report_gate(
    candidates: list[SourceCandidate],
    topic: TopicConfig,
) -> tuple[list[SourceCandidate], list[ReviewFinding]]:
    gated: list[SourceCandidate] = []
    findings: list[ReviewFinding] = []
    for candidate in candidates:
        reason = _daily_report_suppression_reason(candidate, topic)
        if reason is None:
            gated.append(candidate)
            continue
        gated_candidate = replace(
            candidate,
            metadata={
                **candidate.metadata,
                "daily_report_gate": {
                    "status": "suppressed",
                    "reason": reason,
                },
            },
        )
        gated.append(gated_candidate)
        if (
            candidate.metadata.get("relevance", {}).get("status") == "relevant"
            and is_reportable_source(candidate)
        ):
            findings.append(
                ReviewFinding(
                    severity="info",
                    message=f"Daily report gate suppressed source: {reason}",
                    claim_text=candidate.title,
                    metadata={
                        "kind": "daily_report_gate",
                        "source_url": candidate.url,
                        "reason": reason,
                    },
                )
            )
    return gated, findings


def _daily_report_suppression_reason(
    candidate: SourceCandidate,
    topic: TopicConfig,
) -> str | None:
    if topic.source_intent != "research_brief":
        return None
    role = candidate.metadata.get("source_role", {}).get("role")
    if candidate.source_type.value == "repository" and role == "survey_or_list":
        return "research brief excludes repository resource lists"
    return None


def _passes_daily_report_gate(candidate: SourceCandidate) -> bool:
    return candidate.metadata.get("daily_report_gate", {}).get("status") != "suppressed"


def _deep_selection_findings(
    candidates: list[SourceCandidate],
    selected: list[SourceCandidate],
    *,
    source_intent: str,
    deep_reading_status_by_url: dict[str, str] | None = None,
) -> list[ReviewFinding]:
    selected_urls = {candidate.url for candidate in selected}
    status_map = deep_reading_status_by_url or {}
    findings: list[ReviewFinding] = []
    for candidate in candidates:
        source_role = candidate.metadata.get("source_role", {})
        selected_text = "selected" if candidate.url in selected_urls else "not selected"
        deep_status = status_map.get(candidate.url, "not_attempted")
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
                    f"deep_status={deep_status}, "
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
                    "attempted_for_deep_reading": deep_status != "not_attempted",
                    "deep_reading_status": deep_status,
                },
            )
        )
    return findings


def _quality_gate_findings(paper_coverage: dict[str, object]) -> list[ReviewFinding]:
    if paper_coverage.get("status") == "pass":
        return []
    return [
        ReviewFinding(
            severity="warning",
            message=f"Research quality gate degraded run: {paper_coverage.get('reason')}",
            metadata={
                "kind": "research_quality_gate",
                "status": paper_coverage.get("status"),
                "reason": paper_coverage.get("reason"),
            },
        )
    ]


def _replace_candidates(
    candidates: list[SourceCandidate],
    replacements: list[SourceCandidate],
) -> list[SourceCandidate]:
    by_url = {candidate.url: candidate for candidate in replacements}
    return [by_url.get(candidate.url, candidate) for candidate in candidates]


def _daily_claims(
    *,
    deep_required: bool,
    selected_deep_candidates: list[SourceCandidate],
    readings: list[object],
    deep_claims: list[Claim],
    summary_artifacts: list[Artifact],
) -> tuple[list[Claim], list[ReviewFinding]]:
    if not deep_required:
        return heuristic_claims(summary_artifacts), []
    if deep_claims:
        return deep_claims, []
    return [], [
        ReviewFinding(
            severity="error",
            message=(
                "Deep reading was required, but no validated deep-reading claims were "
                "produced; heuristic fallback is disabled for this run."
            ),
            metadata={
                "kind": "deep_reading_required_but_missing",
                "selected_count": len(selected_deep_candidates),
                "reading_count": len(readings),
                "deep_claim_count": len(deep_claims),
            },
        )
    ]


def _merge_artifacts(
    summary_artifacts: list[Artifact],
    deep_artifacts: list[Artifact],
) -> list[Artifact]:
    deep_urls = {artifact.source.url for artifact in deep_artifacts}
    return [
        *deep_artifacts,
        *[artifact for artifact in summary_artifacts if artifact.source.url not in deep_urls],
    ]
