from http.client import IncompleteRead
from pathlib import Path

from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.openai_compatible import OpenAICompatibleProvider
from research_radar.analysis.providers import Message, ModelResponse, StaticProvider
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError, ResearchRadarError
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType
from research_radar.pipeline import paper
from research_radar.pipeline.paper import build_direct_paper_source, run_paper
from research_radar.security.secrets import InMemorySecretBackend, SecretManager
from research_radar.storage.files import read_json, read_jsonl


class CapturingProvider:
    """Test provider that records prompts before returning fixture JSON."""

    name = "capturing"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return fixture content and keep the request for assertions."""

        self.messages.append(messages)
        return ModelResponse(content=self.content, model=model)


class SequenceProvider:
    """Test provider that returns a sequence of responses."""

    name = "sequence"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return the next fixture response."""

        if not self.responses:
            raise AssertionError("No more fixture responses")
        return ModelResponse(content=self.responses.pop(0), model=model)


class FailingProvider:
    """Test provider that raises an analysis error."""

    name = "failing-reader"

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Raise a deterministic analysis failure."""

        raise AnalysisError("failing-reader request failed: model=fake-reader")


class CountingProvider:
    """Provider that returns fixed content and counts real model calls."""

    name = "counting"

    def __init__(self, content: str) -> None:
        self.content = content
        self.call_count = 0

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(content=self.content, model=model, metadata={"provider": self.name})


def test_build_direct_paper_source_from_arxiv_pdf_url() -> None:
    source = build_direct_paper_source("https://arxiv.org/pdf/2604.01707v1")

    assert source.source_type == SourceType.PAPER
    assert source.source_name == "direct"
    assert source.canonical_id == "2604.01707v1"
    assert source.title == "arXiv 2604.01707v1"


def test_single_paper_pipeline_writes_failed_run_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text="Paper text.")

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    try:
        run_paper(
            tmp_path,
            config,
            "agent-memory",
            "https://arxiv.org/pdf/2604.01707v1",
            FailingProvider(),
            model="fake-reader",
        )
    except AnalysisError as exc:
        assert "failing-reader request failed" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")

    run_dir = next((tmp_path / "runs").iterdir())
    manifest = read_json(run_dir / "manifest.json")
    run_error = read_json(run_dir / "run_error.json")

    assert manifest["source_count"] == 0
    assert manifest["claim_count"] == 0
    assert manifest["publishable_claim_count"] == 0
    assert manifest["metadata"]["failure"]["stage"] == "reader"
    assert manifest["metadata"]["failure"]["provider"] == "failing-reader"
    assert manifest["metadata"]["failure"]["model"] == "fake-reader"
    assert manifest["metadata"]["failure"]["error_type"] == "AnalysisError"
    assert run_error["stage"] == "reader"
    assert "failing-reader request failed" in run_error["message"]
    assert not (run_dir / "claims.jsonl").exists()
    assert not (run_dir / "readings.jsonl").exists()
    assert not (run_dir / "paper.md").exists()


def test_single_paper_pipeline_requires_localizer_for_chinese_report(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    try:
        run_paper(
            tmp_path,
            config,
            "agent-memory",
            "https://arxiv.org/pdf/2604.01707v1",
            StaticProvider(_paper_reading_json()),
            model="fake-reader",
            language="zh",
        )
    except ResearchRadarError as exc:
        assert "Chinese report localization requires" in str(exc)
    else:
        raise AssertionError("Expected ResearchRadarError")

    assert not (tmp_path / "runs").exists()


def test_single_paper_pipeline_uses_model_cache_on_second_run(
    monkeypatch,
    tmp_path: Path,
) -> None:
    claim_text = "Memory benchmark fixture claim."
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = CountingProvider(_claim_unit_reading_json(claim_text))
    verifier = CountingProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"}
          ]
        }
        """
    )
    cached_reader = CachedLLMProvider(
        reader,
        cache_dir=tmp_path / "cache" / "model_calls",
        task_name="deep_reading",
    )
    cached_verifier = CachedLLMProvider(
        verifier,
        cache_dir=tmp_path / "cache" / "model_calls",
        task_name="verifier",
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text=claim_text)

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    for _ in range(2):
        run_dir = run_paper(
            tmp_path,
            config,
            "agent-memory",
            "https://arxiv.org/pdf/2604.01707v1",
            cached_reader,
            model="fake-reader",
            verifier=cached_verifier,
            verifier_model="fake-verifier",
        )

    runtime = read_json(run_dir / "runtime_summary.json")
    claims = read_jsonl(run_dir / "claims.jsonl")
    assert reader.call_count == 1
    assert verifier.call_count == 1
    assert runtime["cache"]["hit_count"] == 2
    assert runtime["cache"]["miss_count"] == 0
    assert claims[0]["status"] == ClaimStatus.SUPPORTED


def test_single_paper_pipeline_sends_only_publishable_claims_to_verifier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    broad_claim = (
        "Default backbone is Qwen2.5-7B and embedding model is all-MiniLM-L6-v2."
    )
    supported_claim = "LOCOMO is a benchmark dataset for long-context memory."
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = CountingProvider(_two_claim_reading_json(broad_claim, supported_claim))
    verifier = CapturingProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"}
          ]
        }
        """
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text=f"{broad_claim}\n{supported_claim}")

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        reader,
        model="fake-reader",
        verifier=verifier,
        verifier_model="fake-verifier",
    )

    runtime = read_json(run_dir / "runtime_summary.json")
    claims = read_jsonl(run_dir / "claims.jsonl")
    verifier_prompt = verifier.messages[0][1].content
    verifier_stage = next(stage for stage in runtime["stages"] if stage["stage"] == "verifier")

    assert broad_claim not in verifier_prompt
    assert supported_claim in verifier_prompt
    assert verifier_stage["verifier_input_count"] == 1
    assert verifier_stage["verifier_skipped_claim_count"] == 1
    assert [claim["status"] for claim in claims] == [
        ClaimStatus.NEEDS_REVIEW,
        ClaimStatus.SUPPORTED,
    ]


def test_single_paper_pipeline_persists_transport_diagnostics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    manager = SecretManager(InMemorySecretBackend())
    manager.set_openai_api_key("fake-key")
    reader = OpenAICompatibleProvider(
        name="openai",
        endpoint="https://api.example.test/chat/completions",
        api_key_secret="openai.api_key",
        secrets=manager,
        timeout_seconds=17,
    )
    partial = b'{"choices":[{"message":{"content":"partial model answer'

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text="Paper text.")

    def fake_urlopen(*args, **kwargs):
        raise IncompleteRead(partial, expected=100)

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)
    monkeypatch.setattr("research_radar.analysis.openai_compatible.urlopen", fake_urlopen)

    try:
        run_paper(
            tmp_path,
            config,
            "agent-memory",
            "https://arxiv.org/pdf/2604.01707v1",
            reader,
            model="gpt-test",
        )
    except AnalysisError as exc:
        assert "transport_state=partial_model_response" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")

    run_dir = next((tmp_path / "runs").iterdir())
    manifest = read_json(run_dir / "manifest.json")
    run_error = read_json(run_dir / "run_error.json")

    transport = run_error["transport"]
    assert transport["partial_byte_count"] == len(partial)
    assert transport["expected_byte_count"] == 100
    assert transport["transport_state"] == "partial_model_response"
    assert "partial model answer" in transport["response_excerpt"]
    assert manifest["metadata"]["failure"]["transport"] == transport


def test_single_paper_pipeline_writes_auditable_outputs(monkeypatch, tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_paper_reading_json())
    seen_source: dict[str, SourceCandidate] = {}

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        seen_source["source"] = source
        return Artifact(
            source=source,
            text=(
                "The paper evaluates memory in LLM agents. "
                "It organizes methods into a unified framework. "
                "LOCOMO and LONGMEMEVAL are used for evaluation. "
                "The paper reports no deployment evaluation."
            ),
            artifact_path=str(artifact_dir / "paper.pdf"),
            content_type="application/pdf",
        )

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        provider,
        model="fake-analyst",
    )

    manifest = read_json(run_dir / "manifest.json")
    claims = read_jsonl(run_dir / "claims.jsonl")
    findings = read_jsonl(run_dir / "review_findings.jsonl")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")
    deep_report = (run_dir / "deep_reading.md").read_text(encoding="utf-8")
    report = (run_dir / "review_report.md").read_text(encoding="utf-8")

    assert seen_source["source"].source_type == SourceType.PAPER
    assert manifest["mode"] == "paper"
    assert manifest["metadata"]["canonical_id"] == "2604.01707v1"
    assert (run_dir / "artifacts.jsonl").exists()
    assert (run_dir / "paper_sections.jsonl").exists()
    assert (run_dir / "paper_reading_input.md").exists()
    assert (run_dir / "anchor_resolution.jsonl").exists()
    assert (run_dir / "anchor_repair.jsonl").exists()
    assert (run_dir / "readings.jsonl").exists()
    assert (run_dir / "deep_reading.md").exists()
    assert any(claim["text"].startswith("Experiment:") for claim in claims)
    assert any(
        claim["text"].startswith("Critical assessment:")
        and claim["status"] == ClaimStatus.UNSUPPORTED
        for claim in claims
    )
    assert "LOCOMO and LONGMEMEVAL" in brief
    assert "overclaims universal coverage" not in brief
    assert "overclaims universal coverage" not in deep_report
    assert "evidence_anchor_unmatched" in str(findings)
    assert "No evidence anchors for this claim were found" in report


def test_single_paper_pipeline_writes_reader_attempt_audit_after_retry(
    monkeypatch,
    tmp_path: Path,
) -> None:
    claim_text = "Experiment: Memory benchmark fixture."
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = SequenceProvider(["not json", _claim_unit_reading_json(claim_text)])
    verifier = StaticProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"}
          ]
        }
        """
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text=claim_text)

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        reader,
        model="fake-analyst",
        verifier=verifier,
        verifier_model="fake-reviewer",
    )

    attempts = read_jsonl(run_dir / "reader_attempts.jsonl")
    review_report = (run_dir / "review_report.md").read_text(encoding="utf-8")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")

    assert [attempt["status"] for attempt in attempts] == ["failed", "succeeded"]
    assert attempts[0]["error_message"]
    assert "not json" in attempts[0]["response_excerpt"]
    assert "## Reader Attempts" in review_report
    assert claim_text in brief


def test_single_paper_pipeline_repairs_missing_table_anchor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    table_quote = "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = StaticProvider(_missing_anchor_reading_json())
    repair = CapturingProvider(
        f"""
        {{
          "repairs": [
            {{
              "claim_index": 1,
              "quote": "{table_quote}",
              "location": "page 12, Table 7",
              "reason": "Exact table row supports the numeric claim."
            }}
          ]
        }}
        """
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(
            source=source,
            text=f"[page 12]\n{table_quote}",
            artifact_path=str(artifact_dir / "paper.pdf"),
            content_type="application/pdf",
        )

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        reader,
        model="fake-reader",
        anchor_repair_provider=repair,
        anchor_repair_model="fake-repair",
    )

    claims = read_jsonl(run_dir / "claims.jsonl")
    repairs = read_jsonl(run_dir / "anchor_repair.jsonl")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")
    report = (run_dir / "review_report.md").read_text(encoding="utf-8")

    assert claims[0]["status"] == ClaimStatus.SUPPORTED
    assert claims[0]["evidence"][0]["source_url"] == "https://arxiv.org/pdf/2604.01707v1"
    assert repairs[0]["status"] == "accepted"
    assert "Ours reaches 38.79 overall F1" in brief
    assert "No evidence anchors for this claim were found" not in report


def test_single_paper_pipeline_keeps_broad_setup_claim_out_of_brief(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wide_claim = (
        "Default LLM backbone is Qwen2.5-7B-Instruct; embedding model is "
        "all-MiniLM-L6-v2; top-k retrieval uses k=10; greedy decoding is used."
    )
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_claim_unit_reading_json(wide_claim))

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(
            source=source,
            text=wide_claim,
            artifact_path=str(artifact_dir / "paper.pdf"),
            content_type="application/pdf",
        )

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        provider,
        model="fake-reader",
    )

    claims = read_jsonl(run_dir / "claims.jsonl")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")
    report = (run_dir / "review_report.md").read_text(encoding="utf-8")

    assert claims[0]["status"] == ClaimStatus.NEEDS_REVIEW
    assert "claim too broad; split setup facets" in report
    assert wide_claim not in brief


def test_single_paper_pipeline_uses_late_full_paper_sections(
    monkeypatch,
    tmp_path: Path,
) -> None:
    late_result = "LATE_RESULT: LOCOMO improves after modular memory routing."
    late_limitation = "LATE_LIMITATION: Deployment behavior remains untested."
    artifact_text = "\n\n".join(
        [
            "[page 1]\nAbstract\n" + ("early abstract filler " * 900),
            "[page 5]\n3 Framework\nThe framework separates memory write and retrieval.",
            f"[page 14]\n5 Experiments\n{late_result}",
            f"[page 16]\n7 Conclusion\n{late_limitation}",
            "[page 17]\nReferences\n[1] A reference about LOCOMO.",
        ]
    )
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = CapturingProvider(_late_section_reading_json(late_result, late_limitation))

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(
            source=source,
            text=artifact_text,
            artifact_path=str(artifact_dir / "paper.pdf"),
            content_type="application/pdf",
        )

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        provider,
        model="fake-analyst",
    )

    prompt = provider.messages[0][1].content
    sections = read_jsonl(run_dir / "paper_sections.jsonl")
    claims = read_jsonl(run_dir / "claims.jsonl")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")
    reading_input = (run_dir / "paper_reading_input.md").read_text(encoding="utf-8")

    assert late_result not in artifact_text[:12_000]
    assert late_result in prompt
    assert late_limitation in prompt
    assert "role=experiments_results" in reading_input
    assert "role=limitations_conclusion" in reading_input
    assert any(row["role"] == "references" for row in sections)
    assert all(
        not (
            row["role"] == "references"
            and row["metadata"].get("selection_reason") == "role coverage: references"
        )
        for row in sections
    )
    assert any(late_result in claim["text"] for claim in claims)
    assert any(late_limitation in claim["text"] for claim in claims)
    assert late_result in brief
    assert late_limitation in brief


def test_single_paper_pipeline_supports_chinese_report_language(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = CapturingProvider(_paper_reading_json())
    verifier = StaticProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"},
            {"claim_index": 2, "status": "supported", "risk": "low", "reason": "grounded"},
            {"claim_index": 3, "status": "supported", "risk": "low", "reason": "grounded"}
          ]
        }
        """
    )
    localizer = CapturingProvider(_paper_localization_json())

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(
            source=source,
            text=(
                "The paper evaluates memory in LLM agents. "
                "It organizes methods into a unified framework. "
                "LOCOMO and LONGMEMEVAL are used for evaluation. "
                "The paper reports no deployment evaluation."
            ),
            artifact_path=str(artifact_dir / "paper.pdf"),
            content_type="application/pdf",
        )

    monkeypatch.setattr(paper, "ingest_source", fake_ingest_source)

    run_dir = run_paper(
        tmp_path,
        config,
        "agent-memory",
        "https://arxiv.org/pdf/2604.01707v1",
        reader,
        model="fake-analyst",
        verifier=verifier,
        verifier_model="fake-reviewer",
        localizer=localizer,
        localization_model="fake-localizer",
        language="zh",
    )

    manifest = read_json(run_dir / "manifest.json")
    claims = read_jsonl(run_dir / "claims.jsonl")
    localized_readings = read_jsonl(run_dir / "localized_readings.jsonl")
    attempts = read_jsonl(run_dir / "localization_attempts.jsonl")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")
    deep_report = (run_dir / "deep_reading.md").read_text(encoding="utf-8")
    reader_prompt = reader.messages[0][1].content
    localization_prompt = localizer.messages[0][1].content

    assert manifest["metadata"]["analysis_language"] == "en"
    assert manifest["metadata"]["report_language"] == "zh"
    assert manifest["metadata"]["localization"]["status"] == "succeeded"
    assert "Simplified Chinese" not in reader_prompt
    assert "Translate verified ResearchRadar display text into Simplified Chinese" in (
        localization_prompt
    )
    assert "Keep technical terms" in localization_prompt
    assert "# ResearchRadar 论文简报" in brief
    assert "## 问题与动机" in brief
    assert "\nProblem:" not in brief
    assert "论文评估 LLM agent 中的 memory 方法。" in brief
    assert "LOCOMO" in brief
    assert "LONGMEMEVAL" in brief
    assert "unified framework" in brief
    assert claims[0]["text"].startswith("Problem: The paper evaluates")
    assert localized_readings[0]["problem_solution"]["problem"].startswith("论文评估")
    assert attempts[0]["status"] == "succeeded"
    assert [attempt["scope"] for attempt in attempts] == ["reading", "display"]
    assert "深度阅读报告" in deep_report
    assert "# 深度阅读报告" in deep_report


def _paper_reading_json() -> str:
    return """
    {
      "deep_readings": {
        "area_context": {
          "background": "Agent memory research studies persistence and retrieval for LLM agents.",
          "active_questions": ["How should memory architectures be compared?"],
          "common_baselines": ["Long-context prompting"],
          "evidence": [{"quote": "The paper evaluates memory in LLM agents."}]
        },
        "problem_solution": {
          "problem": "The paper evaluates memory in LLM agents.",
          "why_it_matters": "Without a shared framing, memory strategies are hard to compare.",
          "hidden_assumptions": ["Benchmarks capture important memory behavior."],
          "solution": "It organizes methods into a unified framework.",
          "mechanism": "The framework separates memory architecture choices and strategies.",
          "evidence": [{"quote": "It organizes methods into a unified framework."}]
        },
        "related_work": {
          "prior_work": ["Long-context prompting"],
          "novelty": "It organizes methods into a unified framework.",
          "repackaging_risk": "It is partly a synthesis of existing memory strategies.",
          "evidence": [{"quote": "unified framework"}]
        },
        "experiments": {
          "summary": "LOCOMO and LONGMEMEVAL are used for evaluation.",
          "evidence": [{"quote": "LOCOMO and LONGMEMEVAL are used for evaluation."}]
        },
        "limitations": {
          "explicit_limitations": ["The paper reports no deployment evaluation."],
          "inferred_weaknesses": ["Benchmark coverage may not represent open-ended agents."],
          "evidence": [{"quote": "The paper reports no deployment evaluation."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Medium",
          "weak_evaluations": ["No deployment evaluation"],
          "missing_ablations": ["No broad agent deployment ablation"],
          "bottom_line": "The paper overclaims universal coverage.",
          "evidence": [{"quote": "this quote is not in the artifact"}]
        },
        "plain_language_example": "It is like comparing memory systems with a common checklist.",
        "essence": "The paper turns scattered LLM memory designs into a shared comparison frame.",
        "unsupported_or_rejected_claims": []
      }
    }
    """


def _paper_localization_json() -> str:
    return """
    {
      "readings": [
        {
          "index": 0,
          "area_context": {
            "background": "Agent memory 研究关注 LLM agent 的持久化与检索。",
            "active_questions": ["如何比较不同 memory 架构？"],
            "common_baselines": ["long-context prompting"]
          },
          "problem_solution": {
            "problem": "论文评估 LLM agent 中的 memory 方法。",
            "why_it_matters": "没有统一框架时，不同 memory 策略很难公平比较。",
            "hidden_assumptions": ["benchmark 能覆盖关键 memory 行为。"],
            "solution": "它把方法组织进一个 unified framework。",
            "mechanism": "这个 framework 拆分 memory architecture choices 和 strategies。"
          },
          "related_work": {
            "prior_work": ["long-context prompting"],
            "novelty": "它把已有方法整理成统一比较框架。",
            "repackaging_risk": "部分贡献是综合已有 memory strategies。"
          },
          "experiments": {
            "summary": "论文使用 LOCOMO 和 LONGMEMEVAL 进行评估。"
          },
          "limitations": {
            "explicit_limitations": ["论文没有报告 deployment evaluation。"],
            "inferred_weaknesses": ["benchmark 覆盖可能不能代表开放式 agent。"],
            "future_work": ["后续应验证长期部署场景。"]
          },
          "critical_assessment": {
            "overclaiming_risk": "中等",
            "weak_evaluations": ["没有 deployment evaluation"],
            "missing_ablations": ["没有广泛 agent deployment ablation"],
            "bottom_line": "它更像统一分析框架，而不是证明所有 memory systems 都有效。"
          },
          "plain_language_example": "像用同一张 checklist 比较不同 memory systems。",
          "essence": "论文把分散的 LLM memory 设计整理成共同比较框架。"
        }
      ],
      "claims": [
        {"index": 0, "text": "Problem: 论文评估 LLM agent 中的 memory 方法。"},
        {"index": 1, "text": "Solution: 它把方法组织进一个 unified framework。"},
        {"index": 2, "text": "Experiment: 论文使用 LOCOMO 和 LONGMEMEVAL 进行评估。"}
      ],
      "sources": [
        {
          "url": "https://arxiv.org/pdf/2604.01707v1",
          "gist": "这是一篇关于 LLM agent memory 的论文。"
        }
      ],
      "figures": []
    }
    """


def _paper_reading_zh_json() -> str:
    return """
    {
      "deep_readings": {
        "area_context": {
          "background": "Agent memory 研究关注 LLM agent 的持久化与检索。",
          "active_questions": ["如何比较不同记忆架构？"],
          "common_baselines": ["长上下文提示"],
          "evidence": [{"quote": "The paper evaluates memory in LLM agents."}]
        },
        "problem_solution": {
          "problem": "论文试图评估 LLM agent 中的记忆机制。",
          "why_it_matters": "没有统一框架时，不同记忆策略很难公平比较。",
          "hidden_assumptions": ["这些 benchmark 能覆盖关键记忆行为。"],
          "solution": "它把方法组织进一个统一框架。",
          "mechanism": "框架拆分记忆架构选择与策略。",
          "evidence": [{"quote": "It organizes methods into a unified framework."}]
        },
        "related_work": {
          "prior_work": ["长上下文提示"],
          "novelty": "它把已有策略整理成统一比较框架。",
          "repackaging_risk": "部分贡献是综合已有记忆策略，而不是全新机制。",
          "evidence": [{"quote": "unified framework"}]
        },
        "experiments": {
          "summary": "论文使用 LOCOMO 和 LONGMEMEVAL 进行评估。",
          "evidence": [{"quote": "LOCOMO and LONGMEMEVAL are used for evaluation."}]
        },
        "limitations": {
          "explicit_limitations": ["论文没有报告部署评估。"],
          "inferred_weaknesses": ["benchmark 覆盖可能不能代表开放式 agent。"],
          "future_work": ["后续应验证长期部署场景。"],
          "evidence": [{"quote": "The paper reports no deployment evaluation."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "中等",
          "weak_evaluations": ["没有部署评估"],
          "missing_ablations": ["没有广泛部署消融"],
          "bottom_line": "它更像统一分析框架，而不是证明所有记忆系统都有效。",
          "evidence": [{"quote": "The paper evaluates memory in LLM agents."}]
        },
        "plain_language_example": "像用同一张检查表比较不同记忆系统。",
        "essence": "论文把分散的 LLM 记忆设计整理成共同比较框架。",
        "unsupported_or_rejected_claims": []
      }
    }
    """


def _missing_anchor_reading_json() -> str:
    return """
    {
      "deep_readings": {
        "area_context": {
          "background": "The paper studies agent memory.",
          "evidence": [{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}]
        },
        "problem_solution": {
          "problem": "The paper studies agent memory.",
          "why_it_matters": "It compares benchmark performance.",
          "hidden_assumptions": [],
          "solution": "The paper studies agent memory.",
          "mechanism": "The paper studies agent memory.",
          "evidence": [{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}]
        },
        "related_work": {
          "prior_work": ["unknown"],
          "novelty": "unknown",
          "repackaging_risk": "unknown",
          "evidence": [{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}]
        },
        "limitations": {
          "explicit_limitations": [],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "The table supports only a narrow numeric claim.",
          "evidence": [{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}]
        },
        "plain_language_example": "A table row compares methods.",
        "essence": "The paper compares memory methods.",
        "claim_units": [
          {
            "section": "experiment",
            "claim_kind": "fact",
            "text": "Ours reaches 38.79 overall F1 in Table 7.",
            "evidence": [],
            "publishable_default": true
          }
        ],
        "unsupported_or_rejected_claims": []
      }
    }
    """


def _claim_unit_reading_json(claim_text: str) -> str:
    return f"""
    {{
      "deep_readings": {{
        "area_context": {{
          "background": "The paper studies agent memory.",
          "evidence": [{{"quote": "{claim_text}"}}]
        }},
        "problem_solution": {{
          "problem": "The paper studies agent memory.",
          "why_it_matters": "It compares benchmark performance.",
          "hidden_assumptions": [],
          "solution": "The paper studies agent memory.",
          "mechanism": "The paper studies agent memory.",
          "evidence": [{{"quote": "{claim_text}"}}]
        }},
        "related_work": {{
          "prior_work": ["unknown"],
          "novelty": "unknown",
          "repackaging_risk": "unknown",
          "evidence": [{{"quote": "{claim_text}"}}]
        }},
        "limitations": {{
          "explicit_limitations": [],
          "inferred_weaknesses": [],
          "evidence": [{{"quote": "{claim_text}"}}]
        }},
        "critical_assessment": {{
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "The paper studies agent memory.",
          "evidence": [{{"quote": "{claim_text}"}}]
        }},
        "plain_language_example": "A paper setup can be split into atomic facts.",
        "essence": "The paper studies agent memory.",
        "claim_units": [
          {{
            "section": "experiment",
            "claim_kind": "fact",
            "text": "{claim_text}",
            "evidence": [{{"quote": "{claim_text}"}}],
            "publishable_default": true
          }}
        ],
        "unsupported_or_rejected_claims": []
      }}
    }}
    """


def _two_claim_reading_json(broad_claim: str, supported_claim: str) -> str:
    return f"""
    {{
      "deep_readings": {{
        "area_context": {{
          "background": "The paper studies agent memory.",
          "evidence": [{{"quote": "{supported_claim}"}}]
        }},
        "problem_solution": {{
          "problem": "The paper studies agent memory.",
          "why_it_matters": "It compares benchmark performance.",
          "hidden_assumptions": [],
          "solution": "The paper studies agent memory.",
          "mechanism": "The paper studies agent memory.",
          "evidence": [{{"quote": "{supported_claim}"}}]
        }},
        "related_work": {{
          "prior_work": ["unknown"],
          "novelty": "unknown",
          "repackaging_risk": "unknown",
          "evidence": [{{"quote": "{supported_claim}"}}]
        }},
        "limitations": {{
          "explicit_limitations": [],
          "inferred_weaknesses": [],
          "evidence": [{{"quote": "{supported_claim}"}}]
        }},
        "critical_assessment": {{
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "The paper studies agent memory.",
          "evidence": [{{"quote": "{supported_claim}"}}]
        }},
        "plain_language_example": "A paper setup can be split into atomic facts.",
        "essence": "The paper studies agent memory.",
        "claim_units": [
          {{
            "section": "experiment",
            "claim_kind": "fact",
            "text": "{broad_claim}",
            "evidence": [{{"quote": "{broad_claim}"}}],
            "publishable_default": true
          }},
          {{
            "section": "experiment",
            "claim_kind": "fact",
            "text": "{supported_claim}",
            "evidence": [{{"quote": "{supported_claim}"}}],
            "publishable_default": true
          }}
        ],
        "unsupported_or_rejected_claims": []
      }}
    }}
    """


def _late_section_reading_json(late_result: str, late_limitation: str) -> str:
    return f"""
    {{
      "deep_readings": {{
        "area_context": {{
          "background": "The paper studies agent memory.",
          "evidence": [{{"quote": "The framework separates memory write and retrieval."}}]
        }},
        "problem_solution": {{
          "problem": "Agent memory systems need comparable decomposition.",
          "why_it_matters": "The decomposition makes memory choices easier to inspect.",
          "hidden_assumptions": [],
          "solution": "The framework separates memory write and retrieval.",
          "mechanism": "The framework separates memory write and retrieval.",
          "evidence": [{{"quote": "The framework separates memory write and retrieval."}}]
        }},
        "related_work": {{
          "prior_work": ["unknown"],
          "novelty": "unknown",
          "repackaging_risk": "unknown",
          "evidence": [{{"quote": "The framework separates memory write and retrieval."}}]
        }},
        "experiments": {{
          "summary": "{late_result}",
          "evidence": [{{"quote": "{late_result}"}}]
        }},
        "limitations": {{
          "explicit_limitations": ["{late_limitation}"],
          "inferred_weaknesses": [],
          "evidence": [{{"quote": "{late_limitation}"}}]
        }},
        "critical_assessment": {{
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "The strongest supported caution is limited deployment evidence.",
          "evidence": [{{"quote": "{late_limitation}"}}]
        }},
        "plain_language_example": "It is like separating notes from lookup.",
        "essence": "The paper frames agent memory as separable write and retrieval choices.",
        "claim_units": [
          {{
            "section": "experiment",
            "claim_kind": "fact",
            "text": "Experiment: {late_result}",
            "evidence": [{{"quote": "{late_result}"}}],
            "publishable_default": true
          }},
          {{
            "section": "limitations",
            "claim_kind": "limitation",
            "text": "Limitations: {late_limitation}",
            "evidence": [{{"quote": "{late_limitation}"}}],
            "publishable_default": true
          }}
        ],
        "unsupported_or_rejected_claims": []
      }}
    }}
    """
