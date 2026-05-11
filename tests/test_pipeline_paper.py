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
    assert "evidence_anchor_unmatched" in str(findings)
    assert "No evidence anchors for this claim were found" in report


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
