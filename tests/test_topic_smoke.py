from pathlib import Path

from research_radar.analysis.providers import StaticProvider
from research_radar.config import parse_config
from research_radar.evaluation.topic_smoke import (
    DEFAULT_TOPIC_SMOKE_SPECS,
    TopicSmokeReport,
    TopicSmokeSpec,
    render_topic_smoke_markdown,
    run_topic_smoke,
    select_topic_specs,
    summarize_topic_run,
)
from research_radar.exceptions import ResearchRadarError
from research_radar.storage.files import read_json, write_json, write_jsonl, write_text


def test_topic_smoke_summary_reads_selected_source(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, DEFAULT_TOPIC_SMOKE_SPECS[0])

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert result.passed
    assert result.selected_source is not None
    assert result.selected_source["title"] == "Grounded Agent Memory Benchmark"
    assert result.selected_source["role"] == "benchmark_paper"
    assert result.best_skipped_paper is None
    assert result.paper_candidate_count == 1
    assert result.relevant_paper_count == 1
    assert result.viable_paper_count == 1
    assert result.paper_selection_reason == "paper selected"
    assert result.publishable_claim_count == 1


def test_topic_smoke_reports_survey_list_selection_failure(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        selected_url="https://example.com/list",
        sources=[
            _source(
                "Awesome Agent Memory",
                "https://example.com/list",
                "survey_or_list",
                "A curated list of agent memory resources.",
            ),
            _source(
                "Grounded Agent Memory Benchmark",
                "https://example.com/paper",
                "benchmark_paper",
                "A paper about agent memory benchmark evaluation.",
            ),
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert not result.passed
    assert "selected source is a survey/list despite non-list relevant sources" in result.failures


def test_topic_smoke_reports_repo_hiding_comparable_paper(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        selected_url="https://example.com/repo",
        sources=[
            _source(
                "agent-memory-benchmark",
                "https://example.com/repo",
                "implementation_repo",
                "Benchmark implementation for agent memory.",
                source_type="repository",
                source_name="github",
                relevance=0.8,
            ),
            _source(
                "Grounded Agent Memory Benchmark",
                "https://example.com/paper",
                "benchmark_paper",
                "A paper about agent memory benchmark evaluation.",
                relevance=0.65,
            ),
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert not result.passed
    assert result.best_skipped_paper is not None
    assert result.best_skipped_paper["title"] == "Grounded Agent Memory Benchmark"
    assert result.paper_selection_reason == "viable paper skipped"
    assert "selected repository hides a comparable relevant paper" in result.failures


def test_topic_smoke_reports_low_centrality_selection(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[2],
        selected_url="https://example.com/legal-rag",
        sources=[
            _source(
                "Fine-grained Claim-level RAG Benchmark for Law",
                "https://example.com/legal-rag",
                "benchmark_paper",
                "A law-specific RAG benchmark.",
                centrality=0.42,
            ),
            _source(
                "RAG Systems Evaluation Benchmark",
                "https://example.com/general-rag",
                "benchmark_paper",
                "A general retrieval augmented generation evaluation benchmark.",
                centrality=0.78,
            ),
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[2])

    assert not result.passed
    assert result.selected_source is not None
    assert result.selected_source["centrality_score"] == 0.42
    assert result.best_skipped_paper is not None
    assert result.best_skipped_paper["centrality_score"] == 0.78
    assert "selected paper has low centrality despite a stronger viable paper" in result.failures


def test_topic_smoke_does_not_treat_missing_centrality_as_low_centrality(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[2],
        selected_url="https://example.com/general-rag",
        sources=[
            _source(
                "RAG Systems Evaluation Benchmark",
                "https://example.com/general-rag",
                "benchmark_paper",
                "A general retrieval augmented generation evaluation benchmark.",
            ),
            _source(
                "Another RAG Benchmark",
                "https://example.com/other-rag",
                "benchmark_paper",
                "A general retrieval augmented generation benchmark.",
                centrality=0.78,
            ),
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[2])

    assert result.passed
    assert result.selected_source is not None
    assert result.selected_source["centrality_score"] is None
    assert "selected paper has low centrality despite a stronger viable paper" not in (
        result.failures
    )


def test_topic_smoke_ignores_below_threshold_best_skipped_paper(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[2],
        selected_url="https://example.com/general-rag",
        sources=[
            _source(
                "RAG Systems Evaluation Benchmark",
                "https://example.com/general-rag",
                "benchmark_paper",
                "A general retrieval augmented generation evaluation benchmark.",
                relevance=0.8,
                centrality=0.42,
            ),
            _source(
                "Low-Relevance RAG Candidate",
                "https://example.com/low-rag",
                "benchmark_paper",
                "A weak retrieval augmented generation match.",
                relevance=0.45,
                centrality=0.88,
            ),
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[2])

    assert result.passed
    assert result.best_skipped_paper is None


def test_topic_smoke_markdown_includes_skipped_paper_centrality(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[2],
        selected_url="https://example.com/legal-rag",
        sources=[
            _source(
                "Fine-grained Claim-level RAG Benchmark for Law",
                "https://example.com/legal-rag",
                "benchmark_paper",
                "A law-specific RAG benchmark.",
                centrality=0.42,
            ),
            _source(
                "RAG Systems Evaluation Benchmark",
                "https://example.com/general-rag",
                "benchmark_paper",
                "A general retrieval augmented generation evaluation benchmark.",
                centrality=0.78,
            ),
        ],
    )
    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[2])
    report = TopicSmokeReport(
        root=str(tmp_path),
        summary_path=str(tmp_path / "summary.json"),
        markdown_path=str(tmp_path / "summary.md"),
        passed=result.passed,
        results=[result],
    )

    markdown = render_topic_smoke_markdown(report)

    assert "Skipped Centrality" in markdown
    assert "0.780" in markdown


def test_topic_smoke_markdown_includes_fit_and_history_status(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        sources=[
            _source(
                "Grounded Agent Memory Benchmark",
                "https://example.com/paper",
                "benchmark_paper",
                "A paper about agent memory benchmark evaluation.",
                history_status="new",
                history_family_key="arxiv:2604.01707",
            )
        ],
    )
    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])
    report = TopicSmokeReport(
        root=str(tmp_path),
        summary_path=str(tmp_path / "summary.json"),
        markdown_path=str(tmp_path / "summary.md"),
        passed=result.passed,
        results=[result],
    )

    markdown = render_topic_smoke_markdown(report)

    assert "Fit" in markdown
    assert "History" in markdown
    assert "Deep Status" in markdown
    assert "| agent-memory | PASS" in markdown
    assert "| OK |" in markdown
    assert "| new (arxiv:2604.01707) | succeeded |" in markdown


def test_topic_smoke_distinguishes_missing_paper_from_below_threshold(tmp_path: Path) -> None:
    no_paper_run = _write_run(
        tmp_path / "missing",
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        selected_url="https://example.com/repo",
        sources=[
            _source(
                "agent-memory-benchmark",
                "https://example.com/repo",
                "implementation_repo",
                "Benchmark implementation for agent memory.",
                source_type="repository",
                source_name="github",
            )
        ],
    )
    low_paper_run = _write_run(
        tmp_path / "low",
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        selected_url="https://example.com/repo",
        sources=[
            _source(
                "agent-memory-benchmark",
                "https://example.com/repo",
                "implementation_repo",
                "Benchmark implementation for agent memory.",
                source_type="repository",
                source_name="github",
                relevance=0.8,
            ),
            _source(
                "Agentic Discovery for Test-Time Scaling",
                "https://example.com/paper",
                "benchmark_paper",
                "A paper about test-time scaling.",
                relevance=0.47,
            ),
        ],
    )

    no_paper = summarize_topic_run(no_paper_run, DEFAULT_TOPIC_SMOKE_SPECS[0])
    low_paper = summarize_topic_run(low_paper_run, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert no_paper.paper_selection_reason == "no paper found"
    assert not no_paper.passed
    assert "research brief degraded because no relevant paper was selected" in no_paper.failures
    assert low_paper.paper_selection_reason == "paper below threshold"
    assert low_paper.rejected_paper_candidates[0]["title"] == (
        "Agentic Discovery for Test-Time Scaling"
    )


def test_topic_smoke_reports_zero_publishable_claims(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        publishable_claim_count=0,
        claims=[],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert not result.passed
    assert "publishable_claim_count is zero" in result.failures


def test_semantic_scholar_warning_does_not_fail_valid_smoke(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        extra_findings=[
            {
                "severity": "warning",
                "message": "semantic_scholar discovery failed: transient upstream error",
                "claim_text": None,
                "metadata": {},
            }
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert result.passed
    assert result.warning_count == 1
    assert result.semantic_scholar_warning_count == 1


def test_topic_smoke_fails_selected_paper_ingestion_failure(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        extra_findings=[
            {
                "severity": "warning",
                "message": "Deep ingestion failed: fixture parse failure",
                "claim_text": "Grounded Agent Memory Benchmark",
                "metadata": {
                    "kind": "deep_ingestion_failed",
                    "source_url": "https://example.com/paper",
                },
            }
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert not result.passed
    assert result.paper_selection_reason == "selected paper ingestion failed"
    assert "selected paper failed ingestion" in result.failures


def test_topic_smoke_reports_all_paper_ingestion_failures(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        selected_url="https://example.com/no-selection",
        sources=[
            _source(
                "Broken Agent Memory Paper",
                "https://example.com/broken-paper",
                "benchmark_paper",
                "A paper about agent memory benchmark evaluation.",
            ),
            _source(
                "Also Broken Agent Memory Paper",
                "https://example.com/also-broken-paper",
                "benchmark_paper",
                "A paper about agent memory benchmark evaluation.",
            ),
        ],
        publishable_claim_count=0,
        claims=[],
        extra_findings=[
            {
                "severity": "warning",
                "message": "Deep ingestion failed: fixture parse failure",
                "claim_text": "Broken Agent Memory Paper",
                "metadata": {
                    "kind": "deep_ingestion_failed",
                    "source_url": "https://example.com/broken-paper",
                },
            },
            {
                "severity": "warning",
                "message": "Deep ingestion failed: fixture parse failure",
                "claim_text": "Also Broken Agent Memory Paper",
                "metadata": {
                    "kind": "deep_ingestion_failed",
                    "source_url": "https://example.com/also-broken-paper",
                },
            },
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert not result.passed
    assert result.selected_source is None
    assert result.paper_selection_reason == "all paper ingestion failed"
    assert "all paper ingestion failed" in result.failures


def test_topic_smoke_reports_downgraded_claim_render_leak(tmp_path: Path) -> None:
    leaked_claim = "Critique: This is a leaked unsupported critique."
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[0],
        claims=[
            _claim("Problem: The paper studies grounded recall.", "supported"),
            _claim(leaked_claim, "unsupported"),
        ],
        daily_text=f"# Brief\n\n{leaked_claim}\n",
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[0])

    assert not result.passed
    assert "downgraded claims appeared in daily.md" in result.failures


def test_run_topic_smoke_writes_aggregate_summary(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    specs = DEFAULT_TOPIC_SMOKE_SPECS

    def fake_runner(root: Path, config, topic_id: str, connectors, **kwargs) -> Path:
        topic_ids = {topic.id for topic in config.topics}
        assert topic_id in topic_ids
        assert config.topic(topic_id).source_intent == "research_brief"
        if topic_id == "llm-reasoning-eval":
            assert config.topic(topic_id).concept_groups["agent_context"]
        spec = next(item for item in specs if item.id == topic_id)
        return _write_run(root / topic_id, spec)

    report = run_topic_smoke(
        tmp_path,
        config,
        [],
        StaticProvider("{}"),
        model="fake-model",
        specs=specs,
        runner=fake_runner,
    )

    summary = read_json(Path(report.summary_path))
    assert report.passed
    assert Path(report.markdown_path).exists()
    assert [item["topic_id"] for item in summary["results"]] == [
        spec.id for spec in DEFAULT_TOPIC_SMOKE_SPECS
    ]
    assert "best_skipped_paper" in summary["results"][0]
    assert "paper_candidate_count" in summary["results"][0]
    assert "rejected_paper_candidates" in summary["results"][0]
    assert (tmp_path / "topic_smoke_progress.jsonl").exists()


def test_run_topic_smoke_refreshes_summary_after_each_topic(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    specs = [DEFAULT_TOPIC_SMOKE_SPECS[0], DEFAULT_TOPIC_SMOKE_SPECS[1]]

    def fake_runner(root: Path, config, topic_id: str, connectors, **kwargs) -> Path:
        if topic_id == "llm-reasoning-eval":
            partial_summary = read_json(root / "topic_smoke_summary.json")
            assert [item["topic_id"] for item in partial_summary["results"]] == [
                "agent-memory"
            ]
            raise ResearchRadarError("fixture second topic failure")
        spec = next(item for item in specs if item.id == topic_id)
        return _write_run(root / topic_id, spec)

    report = run_topic_smoke(
        tmp_path,
        config,
        [],
        StaticProvider("{}"),
        model="fake-model",
        specs=specs,
        runner=fake_runner,
    )

    summary = read_json(Path(report.summary_path))
    assert not report.passed
    assert [item["topic_id"] for item in summary["results"]] == [
        "agent-memory",
        "llm-reasoning-eval",
    ]
    assert summary["results"][0]["passed"] is True
    assert summary["results"][1]["passed"] is False


def test_run_topic_smoke_soft_budget_warns_without_failing(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    def fake_runner(root: Path, config, topic_id: str, connectors, **kwargs) -> Path:
        return _write_run(root / topic_id, DEFAULT_TOPIC_SMOKE_SPECS[0])

    report = run_topic_smoke(
        tmp_path,
        config,
        [],
        StaticProvider("{}"),
        model="fake-model",
        specs=[DEFAULT_TOPIC_SMOKE_SPECS[0]],
        runner=fake_runner,
        topic_budget_seconds=0.000001,
    )

    summary = read_json(Path(report.summary_path))
    assert report.passed
    assert summary["results"][0]["passed"] is True
    assert summary["results"][0]["elapsed_seconds"] is not None
    assert "topic exceeded soft budget" in summary["results"][0]["topic_fit_warnings"][0]


def test_reasoning_eval_warns_on_memory_centric_selection(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[1],
        selected_url="https://example.com/memory-reasoning",
        sources=[
            _source(
                "Continual Self-Improvement with Lightweight Experiential Latent Memories",
                "https://example.com/memory-reasoning",
                "benchmark_paper",
                "A method paper about latent memories for math reasoning.",
            )
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[1])

    assert result.passed
    assert result.topic_fit_warnings == [
        "selected reasoning-eval paper appears method/memory-centric; "
        "check for a reasoning benchmark or evaluation-centered paper"
    ]


def test_reasoning_eval_does_not_warn_on_benchmark_selection(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[1],
        selected_url="https://example.com/reasoning-benchmark",
        sources=[
            _source(
                "AIME and GPQA Reasoning Evaluation Benchmark",
                "https://example.com/reasoning-benchmark",
                "benchmark_paper",
                "A benchmark for LLM reasoning evaluation with AIME and GPQA accuracy.",
            )
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[1])

    assert result.passed
    assert result.topic_fit_warnings == []


def test_rag_systems_warns_on_domain_or_modality_specific_selection(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[2],
        selected_url="https://example.com/multimodal-docqa-rag",
        sources=[
            _source(
                "Benchmarking Retrieval-Augmented Multimodal Generation for Document QA",
                "https://example.com/multimodal-docqa-rag",
                "benchmark_paper",
                "A multimodal document question answering RAG benchmark.",
            )
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[2])

    assert result.passed
    assert result.topic_fit_warnings == [
        "selected RAG paper appears domain- or modality-specific; "
        "check whether it represents general RAG systems"
    ]


def test_rag_systems_does_not_warn_on_general_system_selection(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        DEFAULT_TOPIC_SMOKE_SPECS[2],
        selected_url="https://example.com/general-rag",
        sources=[
            _source(
                "RAG Systems Evaluation Benchmark",
                "https://example.com/general-rag",
                "benchmark_paper",
                "A general RAG systems evaluation benchmark with flaw analysis.",
            )
        ],
    )

    result = summarize_topic_run(run_dir, DEFAULT_TOPIC_SMOKE_SPECS[2])

    assert result.passed
    assert result.topic_fit_warnings == []


def test_select_topic_specs_can_select_llm_inference() -> None:
    specs = select_topic_specs(["llm-inference"])

    assert [spec.id for spec in specs] == ["llm-inference"]
    assert "LLM serving optimization" in specs[0].queries


def test_topic_smoke_failure_summary_omits_model_prompt(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    error = (
        "codex command failed: Reading additional input from stdin...\n"
        "SYSTEM:\n"
        "You are a strict factuality reviewer.\n"
        "USER:\n"
        "Review these claims.\n"
        "ERROR: You've hit your usage limit."
    )

    def fake_runner(*args, **kwargs) -> Path:
        raise ResearchRadarError(error)

    report = run_topic_smoke(
        tmp_path,
        config,
        [],
        StaticProvider("{}"),
        model="fake-model",
        specs=[DEFAULT_TOPIC_SMOKE_SPECS[0]],
        runner=fake_runner,
    )

    summary = read_json(Path(report.summary_path))
    failure = summary["results"][0]["failures"][0]
    assert "usage limit" in failure
    assert "strict factuality reviewer" not in failure
    assert "Review these claims" not in failure


def _write_run(
    base_dir: Path,
    spec: TopicSmokeSpec,
    *,
    selected_url: str = "https://example.com/paper",
    sources: list[dict] | None = None,
    publishable_claim_count: int = 1,
    claims: list[dict] | None = None,
    daily_text: str = "# Brief\n\nProblem: The paper studies grounded recall.\n",
    extra_findings: list[dict] | None = None,
) -> Path:
    run_dir = base_dir / "runs" / f"2026-05-11-{spec.id}"
    source_rows = sources or [
        _source(
            "Grounded Agent Memory Benchmark",
            "https://example.com/paper",
            "benchmark_paper",
            "A paper about agent memory benchmark evaluation.",
        )
    ]
    finding_rows = [
        {
            "severity": "info",
            "message": "Deep-read source selection selected",
            "claim_text": source["title"],
            "metadata": {
                "kind": "deep_source_selection",
                "source_url": source["url"],
                "selected": source["url"] == selected_url,
                "role": source["metadata"]["source_role"]["role"],
                "deep_read_priority": source["metadata"]["source_role"]["deep_read_priority"],
                "attempted_for_deep_reading": source["url"] == selected_url,
                "deep_reading_status": (
                    "succeeded" if source["url"] == selected_url else "not_attempted"
                ),
            },
        }
        for source in source_rows
    ]
    if extra_findings:
        finding_rows.extend(extra_findings)

    write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_dir.name,
            "topic_id": spec.id,
            "mode": "daily",
            "publishable_claim_count": publishable_claim_count,
        },
    )
    write_jsonl(run_dir / "sources.jsonl", source_rows)
    write_jsonl(run_dir / "review_findings.jsonl", finding_rows)
    write_jsonl(
        run_dir / "claims.jsonl",
        claims
        if claims is not None
        else [_claim("Problem: The paper studies grounded recall.", "supported")],
    )
    write_text(run_dir / "daily.md", daily_text)
    return run_dir


def _source(
    title: str,
    url: str,
    role: str,
    summary: str,
    *,
    source_type: str = "paper",
    source_name: str = "arxiv",
    relevance: float = 1.0,
    centrality: float | None = None,
    history_status: str | None = None,
    history_family_key: str | None = None,
) -> dict:
    metadata = {
        "relevance": {"status": "relevant", "score": relevance},
        "source_role": {
            "role": role,
            "reason": f"classified as {role}",
            "deep_read_priority": 450 if role != "survey_or_list" else 50,
        },
    }
    if centrality is not None:
        metadata["source_centrality"] = {
            "score": centrality,
            "positive_signals": ["fixture"],
            "negative_signals": [],
            "reason": "fixture centrality",
        }
    if history_status is not None:
        metadata["source_history"] = {
            "status": history_status,
            "family_key": history_family_key,
            "family_keys": [history_family_key] if history_family_key else [],
            "version": None,
            "previous_version": None,
        }
    return {
        "title": title,
        "url": url,
        "source_type": source_type,
        "source_name": source_name,
        "summary": summary,
        "metadata": metadata,
    }


def _claim(text: str, status: str) -> dict:
    return {
        "text": text,
        "status": status,
        "evidence": [
            {
                "source_url": "https://example.com/paper",
                "quote": "The paper studies grounded recall.",
            }
        ],
    }
