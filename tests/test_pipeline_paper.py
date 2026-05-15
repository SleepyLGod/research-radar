from pathlib import Path

from research_radar.analysis.providers import StaticProvider
from research_radar.config import parse_config
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType
from research_radar.pipeline import paper
from research_radar.pipeline.paper import build_direct_paper_source, run_paper
from research_radar.storage.files import read_json, read_jsonl


def test_build_direct_paper_source_from_arxiv_pdf_url() -> None:
    source = build_direct_paper_source("https://arxiv.org/pdf/2604.01707v1")

    assert source.source_type == SourceType.PAPER
    assert source.source_name == "direct"
    assert source.canonical_id == "2604.01707v1"
    assert source.title == "arXiv 2604.01707v1"


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
    provider = StaticProvider(_paper_reading_zh_json())

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
        provider,
        model="fake-analyst",
        language="zh",
    )

    manifest = read_json(run_dir / "manifest.json")
    brief = (run_dir / "paper.md").read_text(encoding="utf-8")
    deep_report = (run_dir / "deep_reading.md").read_text(encoding="utf-8")

    assert manifest["metadata"]["report_language"] == "zh"
    assert "# ResearchRadar 论文简报" in brief
    assert "## 问题与动机" in brief
    assert "\nProblem:" not in brief
    assert "\n问题：" in brief
    assert "# 深度阅读报告" in deep_report
    assert "The paper evaluates memory in LLM agents." in brief


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
