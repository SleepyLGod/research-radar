"""Real-topic smoke harness and acceptance checks."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from research_radar.analysis.providers import LLMProvider
from research_radar.config import AppConfig, TopicConfig
from research_radar.discovery.base import DiscoveryConnector
from research_radar.discovery.source_selection import (
    RESEARCH_BRIEF,
    RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR,
)
from research_radar.exceptions import ResearchRadarError
from research_radar.pipeline.daily import run_daily
from research_radar.storage.files import ensure_dir, read_json, read_jsonl, write_json, write_text

QUALITY_ROLES = {"primary_paper", "benchmark_paper", "implementation_repo"}


@dataclass(frozen=True)
class TopicSmokeSpec:
    """Configuration for one real-topic smoke evaluation."""

    id: str
    queries: tuple[str, ...]
    topic_signals: tuple[str, ...]
    source_intent: str = RESEARCH_BRIEF
    paper_queries: tuple[str, ...] = ()
    concept_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    priority_sources: tuple[str, ...] = (
        "arxiv.org",
        "semanticscholar.org",
        "github.com",
    )


@dataclass(frozen=True)
class TopicSmokeResult:
    """Acceptance-check result for one topic run."""

    topic_id: str
    run_dir: str | None
    passed: bool
    failures: list[str]
    selected_source: dict[str, Any] | None
    best_skipped_paper: dict[str, Any] | None
    paper_candidate_count: int
    relevant_paper_count: int
    viable_paper_count: int
    paper_selection_reason: str
    rejected_paper_candidates: list[dict[str, Any]]
    publishable_claim_count: int
    warning_count: int
    semantic_scholar_warning_count: int
    obvious_noise: bool


@dataclass(frozen=True)
class TopicSmokeReport:
    """Aggregated topic smoke report."""

    root: str
    summary_path: str
    markdown_path: str
    passed: bool
    results: list[TopicSmokeResult]


DailyRunner = Callable[..., Path]


DEFAULT_TOPIC_SMOKE_SPECS: tuple[TopicSmokeSpec, ...] = (
    TopicSmokeSpec(
        id="agent-memory",
        queries=("agent memory systems", "LLM memory benchmark"),
        topic_signals=(
            "agent memory",
            "llm memory",
            "memory benchmark",
            "persistent recall",
        ),
        paper_queries=(
            "Memory in the LLM Era",
            "LLM agent memory benchmark",
            "LOCOMO LongMemEval agent memory",
            "long term memory LLM agents",
        ),
        concept_groups={
            "agent_context": (
                "agent memory",
                "LLM agent memory",
                "agentic memory",
                "autonomous LLM agents",
            ),
            "memory_mechanism": (
                "memory retrieval",
                "agent recall",
                "persistent recall",
                "long-term memory",
                "memory systems",
            ),
            "evaluation_signal": (
                "LOCOMO",
                "LongMemEval",
                "agent memory benchmark",
                "memory evaluation",
            ),
            "negative_compute_or_training": (
                "prefill serving",
                "kv cache",
                "fine-tuning",
                "QLoRA",
            ),
        },
    ),
    TopicSmokeSpec(
        id="llm-reasoning-eval",
        queries=("LLM reasoning evaluation", "reasoning benchmark test-time scaling"),
        topic_signals=(
            "reasoning evaluation",
            "reasoning benchmark",
            "llm reasoning",
            "test-time scaling",
            "test time scaling",
        ),
        paper_queries=(
            "LLM reasoning evaluation benchmark",
            "test-time scaling reasoning benchmark",
            "reasoning trace self consistency evaluation",
        ),
        concept_groups={
            "agent_context": (
                "LLM reasoning",
                "large language model reasoning",
                "reasoning model",
            ),
            "memory_mechanism": (
                "reasoning evaluation",
                "reasoning benchmark",
                "test-time scaling",
                "test time scaling",
                "reasoning trace",
                "self consistency",
            ),
            "evaluation_signal": (
                "benchmark",
                "evaluation",
                "pass@",
                "accuracy",
            ),
            "negative_compute_or_training": (
                "kv cache",
                "prefill serving",
                "fine-tuning",
                "quantization",
            ),
        },
    ),
    TopicSmokeSpec(
        id="rag-systems",
        queries=("RAG systems evaluation", "retrieval augmented generation benchmark"),
        topic_signals=(
            "rag",
            "retrieval augmented generation",
            "retrieval-augmented generation",
            "retrieval benchmark",
            "rag system",
        ),
        paper_queries=(
            "retrieval augmented generation evaluation benchmark",
            "RAG systems evaluation",
            "retrieval augmented generation survey",
        ),
        concept_groups={
            "agent_context": (
                "RAG",
                "retrieval augmented generation",
                "retrieval-augmented generation",
            ),
            "memory_mechanism": (
                "retrieval",
                "retriever",
                "grounded generation",
                "knowledge grounding",
            ),
            "evaluation_signal": (
                "RAG benchmark",
                "retrieval benchmark",
                "RAG evaluation",
                "retrieval augmented generation evaluation",
            ),
            "negative_compute_or_training": (
                "kv cache",
                "prefill serving",
                "fine-tuning",
                "quantization",
            ),
        },
    ),
)


def select_topic_specs(topic_ids: Sequence[str] | None) -> list[TopicSmokeSpec]:
    """Return smoke specs for requested topic ids."""

    specs = {spec.id: spec for spec in DEFAULT_TOPIC_SMOKE_SPECS}
    if not topic_ids:
        return list(DEFAULT_TOPIC_SMOKE_SPECS)
    selected = []
    for topic_id in topic_ids:
        spec = specs.get(topic_id)
        if spec is None:
            raise ResearchRadarError(f"Unknown topic smoke spec: {topic_id}")
        selected.append(spec)
    return selected


def with_smoke_topics(config: AppConfig, specs: Sequence[TopicSmokeSpec]) -> AppConfig:
    """Add missing smoke topics to a loaded config without mutating it."""

    existing_topic_ids = {topic.id for topic in config.topics}
    topics = list(config.topics)
    for spec in specs:
        if spec.id in existing_topic_ids:
            continue
        topics.append(
            TopicConfig(
                id=spec.id,
                queries=list(spec.queries),
                paper_queries=list(spec.paper_queries),
                concept_groups={
                    group: list(aliases)
                    for group, aliases in spec.concept_groups.items()
                },
                priority_sources=list(spec.priority_sources),
                source_intent=spec.source_intent,
            )
        )
    return replace(config, topics=topics)


def run_topic_smoke(
    root: Path,
    config: AppConfig,
    connectors: list[DiscoveryConnector],
    provider: LLMProvider,
    *,
    model: str,
    specs: Sequence[TopicSmokeSpec] = DEFAULT_TOPIC_SMOKE_SPECS,
    limit: int = 5,
    deep_limit: int = 1,
    language: str | None = None,
    runner: DailyRunner = run_daily,
) -> TopicSmokeReport:
    """Run daily smoke checks for a small set of research topics."""

    if limit < 1:
        raise ResearchRadarError("--limit must be at least 1.")
    if deep_limit < 1:
        raise ResearchRadarError("--deep-limit must be at least 1 for topic smoke.")

    root = ensure_dir(root)
    smoke_config = with_smoke_topics(config, specs)
    results: list[TopicSmokeResult] = []
    for spec in specs:
        try:
            run_dir = runner(
                root,
                smoke_config,
                spec.id,
                connectors,
                verifier=provider,
                verifier_model=model,
                limit=limit,
                deep_reader=provider,
                deep_model=model,
                deep_limit=deep_limit,
                language=language,
            )
        except ResearchRadarError as exc:
            results.append(_failed_topic_result(spec.id, str(exc)))
            continue
        results.append(summarize_topic_run(run_dir, spec))

    summary_path = root / "topic_smoke_summary.json"
    markdown_path = root / "topic_smoke_summary.md"
    report = TopicSmokeReport(
        root=str(root),
        summary_path=str(summary_path),
        markdown_path=str(markdown_path),
        passed=all(result.passed for result in results),
        results=results,
    )
    write_json(summary_path, _report_to_dict(report))
    write_text(markdown_path, render_topic_smoke_markdown(report))
    return report


def summarize_topic_run(run_dir: Path, spec: TopicSmokeSpec) -> TopicSmokeResult:
    """Summarize one run directory and enforce smoke acceptance checks."""

    manifest = read_json(run_dir / "manifest.json")
    sources = read_jsonl(run_dir / "sources.jsonl")
    findings = read_jsonl(run_dir / "review_findings.jsonl")
    claims = read_jsonl(run_dir / "claims.jsonl")
    daily_text = _read_optional_text(run_dir / "daily.md")

    selected_source = _selected_source(sources, findings)
    best_skipped_paper = _best_skipped_paper(sources, selected_source)
    paper_diagnostics = _paper_diagnostics(sources, findings, selected_source)
    rejected_papers = _rejected_papers(sources)
    non_list_relevant_count = _non_list_relevant_count(sources)
    warning_count = sum(1 for finding in findings if finding.get("severity") == "warning")
    semantic_scholar_warning_count = sum(
        1
        for finding in findings
        if finding.get("severity") == "warning"
        and str(finding.get("message", "")).startswith("semantic_scholar discovery failed")
    )
    publishable_claim_count = int(manifest.get("publishable_claim_count", 0))

    failures = _acceptance_failures(
        spec=spec,
        selected_source=selected_source,
        best_skipped_paper=best_skipped_paper,
        paper_selection_reason=str(paper_diagnostics["paper_selection_reason"]),
        non_list_relevant_count=non_list_relevant_count,
        publishable_claim_count=publishable_claim_count,
        claims=claims,
        daily_text=daily_text,
    )
    obvious_noise = selected_source is not None and not _has_required_signal(selected_source, spec)
    return TopicSmokeResult(
        topic_id=spec.id,
        run_dir=str(run_dir),
        passed=not failures,
        failures=failures,
        selected_source=selected_source,
        best_skipped_paper=best_skipped_paper,
        paper_candidate_count=paper_diagnostics["paper_candidate_count"],
        relevant_paper_count=paper_diagnostics["relevant_paper_count"],
        viable_paper_count=paper_diagnostics["viable_paper_count"],
        paper_selection_reason=str(paper_diagnostics["paper_selection_reason"]),
        rejected_paper_candidates=rejected_papers,
        publishable_claim_count=publishable_claim_count,
        warning_count=warning_count,
        semantic_scholar_warning_count=semantic_scholar_warning_count,
        obvious_noise=obvious_noise,
    )


def render_topic_smoke_markdown(report: TopicSmokeReport) -> str:
    """Render a human-readable topic smoke summary."""

    status = "PASS" if report.passed else "FAIL"
    lines = [
        f"# ResearchRadar Topic Smoke: {status}",
        "",
        f"- Root: `{report.root}`",
        f"- Summary JSON: `{report.summary_path}`",
        "",
        "| Topic | Status | Selected Source | Role | "
        "Best Skipped Paper | Papers | Paper Status | Claims | Warnings | Failures |",
        "| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | --- |",
    ]
    for result in report.results:
        selected = result.selected_source or {}
        selected_title = str(selected.get("title", "-")).replace("|", "\\|")
        selected_role = str(selected.get("role", "-")).replace("|", "\\|")
        skipped = result.best_skipped_paper or {}
        skipped_title = str(skipped.get("title", "-")).replace("|", "\\|")
        paper_status = result.paper_selection_reason.replace("|", "\\|")
        failures = ("; ".join(result.failures) if result.failures else "-").replace("|", "\\|")
        lines.append(
            "| "
            f"{result.topic_id} | "
            f"{'PASS' if result.passed else 'FAIL'} | "
            f"{selected_title} | "
            f"{selected_role} | "
            f"{skipped_title} | "
            f"{result.paper_candidate_count}/{result.relevant_paper_count}/"
            f"{result.viable_paper_count} | "
            f"{paper_status} | "
            f"{result.publishable_claim_count} | "
            f"{result.warning_count} | "
            f"{failures} |"
        )
    lines.extend(_rejected_paper_lines(report.results))
    lines.append("")
    return "\n".join(lines)


def _failed_topic_result(topic_id: str, reason: str) -> TopicSmokeResult:
    return TopicSmokeResult(
        topic_id=topic_id,
        run_dir=None,
        passed=False,
        failures=[f"topic run failed: {reason}"],
        selected_source=None,
        best_skipped_paper=None,
        paper_candidate_count=0,
        relevant_paper_count=0,
        viable_paper_count=0,
        paper_selection_reason="topic run failed",
        rejected_paper_candidates=[],
        publishable_claim_count=0,
        warning_count=0,
        semantic_scholar_warning_count=0,
        obvious_noise=True,
    )


def _report_to_dict(report: TopicSmokeReport) -> dict[str, Any]:
    return {
        "root": report.root,
        "summary_path": report.summary_path,
        "markdown_path": report.markdown_path,
        "passed": report.passed,
        "results": [asdict(result) for result in report.results],
    }


def _selected_source(
    sources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    selected_url = None
    selected_role = None
    for finding in findings:
        metadata = finding.get("metadata", {})
        if (
            metadata.get("kind") == "deep_source_selection"
            and metadata.get("selected") is True
        ):
            selected_url = metadata.get("source_url")
            selected_role = metadata.get("role")
            break
    if selected_url is None:
        return None
    for source in sources:
        if source.get("url") != selected_url:
            continue
        role = _source_role(source)
        return {
            "title": source.get("title"),
            "url": source.get("url"),
            "source_type": source.get("source_type"),
            "source_name": source.get("source_name"),
            "role": role or selected_role,
            "summary": source.get("summary"),
            "relevance_score": _relevance_score(source),
            "selection_score": _selection_score_from_findings(findings, selected_url),
        }
    return {
        "title": None,
        "url": selected_url,
        "source_type": None,
        "source_name": None,
        "role": selected_role,
        "summary": None,
        "relevance_score": 0.0,
        "selection_score": _selection_score_from_findings(findings, selected_url),
    }


def _selection_score_from_findings(
    findings: list[dict[str, Any]],
    source_url: str,
) -> float | None:
    for finding in findings:
        metadata = finding.get("metadata", {})
        if metadata.get("source_url") == source_url and "selection_score" in metadata:
            return float(metadata["selection_score"])
    return None


def _best_skipped_paper(
    sources: list[dict[str, Any]],
    selected_source: dict[str, Any] | None,
) -> dict[str, Any] | None:
    selected_url = selected_source.get("url") if selected_source else None
    skipped_papers = [
        source
        for source in sources
        if source.get("url") != selected_url
        and _source_role(source) in {"primary_paper", "benchmark_paper"}
        and source.get("metadata", {}).get("relevance", {}).get("status") == "relevant"
    ]
    if not skipped_papers:
        return None
    best = sorted(
        skipped_papers,
        key=lambda source: (
            _paper_role_rank(source),
            _relevance_score(source),
            float(source.get("score", 0.0)),
        ),
        reverse=True,
    )[0]
    selected_role = selected_source.get("role") if selected_source else None
    return {
        "title": best.get("title"),
        "url": best.get("url"),
        "role": _source_role(best),
        "relevance_score": _relevance_score(best),
        "reason": (
            f"Skipped while selected role was {selected_role}; "
            f"paper relevance={_relevance_score(best):.3f}"
        ),
    }


def _paper_diagnostics(
    sources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    selected_source: dict[str, Any] | None,
) -> dict[str, object]:
    paper_sources = [_paper for _paper in sources if _is_paper_source(_paper)]
    relevant_papers = [
        source
        for source in paper_sources
        if source.get("metadata", {}).get("relevance", {}).get("status") == "relevant"
    ]
    viable_papers = [
        source
        for source in relevant_papers
        if _relevance_score(source) >= RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR
    ]
    return {
        "paper_candidate_count": len(paper_sources),
        "relevant_paper_count": len(relevant_papers),
        "viable_paper_count": len(viable_papers),
        "paper_selection_reason": _paper_selection_reason(
            paper_sources,
            relevant_papers,
            viable_papers,
            findings,
            selected_source,
        ),
    }


def _rejected_papers(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rejected = []
    for source in sources:
        if not _is_paper_source(source):
            continue
        relevance = source.get("metadata", {}).get("relevance", {})
        score = _relevance_score(source)
        status = str(relevance.get("status", "unknown"))
        if status == "relevant" and score >= RESEARCH_BRIEF_PAPER_RELEVANCE_FLOOR:
            continue
        rejected.append(
            {
                "title": source.get("title"),
                "url": source.get("url"),
                "status": status,
                "score": score,
                "reason": relevance.get("reason", "no relevance reason"),
            }
        )
    return sorted(rejected, key=lambda item: float(item["score"]), reverse=True)[:3]


def _rejected_paper_lines(results: list[TopicSmokeResult]) -> list[str]:
    lines = ["", "## Top Rejected Paper Candidates", ""]
    for result in results:
        if not result.rejected_paper_candidates:
            lines.append(f"- `{result.topic_id}`: none")
            continue
        rows = []
        for paper in result.rejected_paper_candidates:
            rows.append(
                f"{paper.get('title')} "
                f"({paper.get('status')}, {paper.get('score')}): {paper.get('reason')}"
            )
        lines.append(f"- `{result.topic_id}`: " + "; ".join(rows))
    return lines


def _paper_selection_reason(
    paper_sources: list[dict[str, Any]],
    relevant_papers: list[dict[str, Any]],
    viable_papers: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    selected_source: dict[str, Any] | None,
) -> str:
    if selected_source is not None and selected_source.get("role") in {
        "primary_paper",
        "benchmark_paper",
    }:
        failure_reason = _selected_paper_failure_reason(selected_source, findings)
        return failure_reason or "paper selected"
    if not paper_sources:
        return "no paper found"
    if not relevant_papers:
        return "no relevant paper"
    if not viable_papers:
        return "paper below threshold"
    return "viable paper skipped"


def _selected_paper_failure_reason(
    selected_source: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str | None:
    source_url = selected_source.get("url")
    for finding in findings:
        metadata = finding.get("metadata", {})
        if metadata.get("source_url") != source_url:
            continue
        kind = metadata.get("kind")
        if kind == "deep_ingestion_failed":
            return "selected paper ingestion failed"
        if kind == "deep_reading_failed":
            return "selected paper reading failed"
    return None


def _non_list_relevant_count(sources: list[dict[str, Any]]) -> int:
    count = 0
    for source in sources:
        relevance = source.get("metadata", {}).get("relevance", {})
        if relevance.get("status") != "relevant":
            continue
        if _source_role(source) == "survey_or_list":
            continue
        count += 1
    return count


def _source_role(source: dict[str, Any]) -> str | None:
    role = source.get("metadata", {}).get("source_role", {}).get("role")
    return str(role) if role is not None else None


def _is_paper_source(source: dict[str, Any]) -> bool:
    return source.get("source_type") == "paper" or _source_role(source) in {
        "primary_paper",
        "benchmark_paper",
    }


def _paper_role_rank(source: dict[str, Any]) -> int:
    return {"primary_paper": 50, "benchmark_paper": 40}.get(_source_role(source) or "", 0)


def _relevance_score(source: dict[str, Any]) -> float:
    return float(source.get("metadata", {}).get("relevance", {}).get("score", 0.0))


def _acceptance_failures(
    *,
    spec: TopicSmokeSpec,
    selected_source: dict[str, Any] | None,
    best_skipped_paper: dict[str, Any] | None,
    paper_selection_reason: str,
    non_list_relevant_count: int,
    publishable_claim_count: int,
    claims: list[dict[str, Any]],
    daily_text: str,
) -> list[str]:
    failures: list[str] = []
    if selected_source is None:
        failures.append("no deep-read source was selected")
    else:
        selected_role = selected_source.get("role")
        if selected_role == "survey_or_list" and non_list_relevant_count > 0:
            failures.append("selected source is a survey/list despite non-list relevant sources")
        if _hides_comparable_paper(spec, selected_source, best_skipped_paper):
            failures.append("selected repository hides a comparable relevant paper")
        if not _has_required_signal(selected_source, spec):
            failures.append("selected source lacks topic phrase or quality source signal")
        if (
            spec.source_intent == RESEARCH_BRIEF
            and selected_role == "implementation_repo"
            and best_skipped_paper is None
        ):
            failures.append("research brief degraded because no relevant paper was selected")
        if paper_selection_reason == "selected paper ingestion failed":
            failures.append("selected paper failed ingestion")
        if paper_selection_reason == "selected paper reading failed":
            failures.append("selected paper failed deep reading")

    if publishable_claim_count <= 0:
        failures.append("publishable_claim_count is zero")

    leaked_claims = _downgraded_claims_in_brief(claims, daily_text)
    if leaked_claims:
        failures.append("downgraded claims appeared in daily.md")
    return failures


def _hides_comparable_paper(
    spec: TopicSmokeSpec,
    selected_source: dict[str, Any],
    best_skipped_paper: dict[str, Any] | None,
) -> bool:
    if spec.source_intent != RESEARCH_BRIEF:
        return False
    if selected_source.get("role") != "implementation_repo":
        return False
    if best_skipped_paper is None:
        return False
    selected_score = float(selected_source.get("relevance_score", 0.0))
    paper_score = float(best_skipped_paper.get("relevance_score", 0.0))
    return paper_score >= max(0.6, selected_score - 0.2)


def _has_required_signal(source: dict[str, Any], spec: TopicSmokeSpec) -> bool:
    role = source.get("role")
    if role in QUALITY_ROLES:
        return True
    text = _normalize_source_text(source)
    return any(signal in text for signal in _normalized_signals(spec))


def _normalized_signals(spec: TopicSmokeSpec) -> tuple[str, ...]:
    return tuple(signal.casefold() for signal in spec.topic_signals)


def _normalize_source_text(source: dict[str, Any]) -> str:
    values = [
        source.get("title"),
        source.get("summary"),
        source.get("source_name"),
        source.get("source_type"),
        source.get("url"),
    ]
    return " ".join(str(value).casefold() for value in values if value)


def _downgraded_claims_in_brief(claims: list[dict[str, Any]], daily_text: str) -> list[str]:
    leaked: list[str] = []
    for claim in claims:
        if claim.get("status") == "supported":
            continue
        text = str(claim.get("text", ""))
        if _claim_text_in_brief(text, daily_text):
            leaked.append(text)
    return leaked


def _claim_text_in_brief(claim_text: str, daily_text: str) -> bool:
    if len(claim_text) >= 20 and claim_text in daily_text:
        return True
    _, separator, body = claim_text.partition(":")
    stripped_body = body.strip() if separator else ""
    return len(stripped_body) >= 20 and stripped_body in daily_text


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
