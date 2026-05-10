from pathlib import Path

from research_radar.analysis.providers import StaticProvider
from research_radar.config import parse_config
from research_radar.discovery.base import DiscoveryContext
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType
from research_radar.pipeline import daily
from research_radar.pipeline.daily import run_daily
from research_radar.storage.files import read_json, read_jsonl


class FakeConnector:
    name = "fake"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="A careful paper",
                url="https://example.com/paper",
                source_type=SourceType.PAPER,
                source_name=self.name,
                summary="This paper reports an agent memory benchmark with clear evidence.",
                score=1.0,
            )
        ]


def test_daily_pipeline_writes_required_outputs(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    run_dir = run_daily(tmp_path, config, "agent-memory", [FakeConnector()])

    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "sources.jsonl").exists()
    assert (run_dir / "evidence.jsonl").exists()
    assert (run_dir / "claims.jsonl").exists()
    assert (run_dir / "article_draft.json").exists()
    assert (run_dir / "daily.md").exists()
    assert (run_dir / "wechat.html").exists()
    assert (run_dir / "review_report.md").exists()
    assert (run_dir / "review_findings.jsonl").exists()
    assert "A careful paper" in (run_dir / "daily.md").read_text(encoding="utf-8")


class MixedConnector:
    name = "mixed"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Grounded Agent Memory Benchmark",
                url="https://example.com/good",
                source_type=SourceType.PAPER,
                source_name=self.name,
                summary="An LLM memory benchmark for persistent recall in AI agents.",
                score=1.0,
            ),
            SourceCandidate(
                title="Agent Memory Overclaim",
                url="https://example.com/overclaim",
                source_type=SourceType.PAPER,
                source_name=self.name,
                summary="A weakly described agent memory system for AI agents.",
                score=0.9,
            ),
            SourceCandidate(
                title="The Kubo-Thermalization Correspondence",
                url="https://example.com/physics",
                source_type=SourceType.PAPER,
                source_name=self.name,
                summary="Quantum thermalization and linear-response theory.",
                score=0.8,
            ),
        ]


def test_daily_pipeline_applies_relevance_and_model_review_gates(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"},
            {
              "claim_index": 2,
              "status": "unsupported",
              "risk": "high",
              "reason": "unsupported overclaim"
            }
          ]
        }
        """
    )

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [MixedConnector()],
        verifier=provider,
        verifier_model="fake-reviewer",
    )

    manifest = read_json(run_dir / "manifest.json")
    claims = read_jsonl(run_dir / "claims.jsonl")
    findings = read_jsonl(run_dir / "review_findings.jsonl")
    daily = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert manifest["source_count"] == 3
    assert manifest["claim_count"] == 2
    assert manifest["publishable_claim_count"] == 1
    assert manifest["metadata"]["relevance"]["irrelevant_count"] == 1
    assert [claim["status"] for claim in claims] == [
        ClaimStatus.SUPPORTED,
        ClaimStatus.UNSUPPORTED,
    ]
    assert "Grounded Agent Memory Benchmark is relevant" in daily
    assert "Agent Memory Overclaim is relevant" not in daily
    assert any(finding["metadata"].get("kind") == "source_relevance" for finding in findings)
    assert any(finding["metadata"].get("kind") == "model_review_decision" for finding in findings)


def test_daily_pipeline_writes_deep_reading_outputs(monkeypatch, tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(
            source=source,
            text="Full text about an agent memory benchmark.",
            artifact_path=str(artifact_dir / "fixture.txt"),
            content_type="text/plain",
        )

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [FakeConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    manifest = read_json(run_dir / "manifest.json")
    readings = read_jsonl(run_dir / "readings.jsonl")
    deep_claims = read_jsonl(run_dir / "deep_claims.jsonl")
    draft = (run_dir / "daily.md").read_text(encoding="utf-8")
    deep_report = (run_dir / "deep_reading.md").read_text(encoding="utf-8")

    assert manifest["metadata"]["deep_reading"]["reading_count"] == 1
    assert readings[0]["essence"] == "The source reframes memory quality as grounded recall."
    assert any(claim["text"].startswith("Problem:") for claim in deep_claims)
    assert "Problem: Memory benchmarks reward unsupported answers." in draft
    assert "Solution: Require cited memory evidence before crediting answers." in draft
    assert "Limitations: It only evaluates benchmark-style tasks." in draft
    assert "The source reframes memory quality as grounded recall." in deep_report


def _deep_reading_json() -> str:
    return """
    {
      "deep_readings": {
        "area_context": {
          "background": "Agent memory systems require grounded retrieval.",
          "active_questions": ["How should memory evidence be scored?"],
          "common_baselines": ["Answer-only scoring"],
          "evidence": [{"quote": "Agent memory systems require grounded retrieval."}]
        },
        "problem_solution": {
          "problem": "Memory benchmarks reward unsupported answers.",
          "why_it_matters": "Scores can hide ungrounded guessing.",
          "hidden_assumptions": ["Retrieved memory evidence exists."],
          "solution": "Require cited memory evidence before crediting answers.",
          "mechanism": "The evaluator checks answers against retrieved memory items.",
          "evidence": [{"quote": "Require cited memory evidence before crediting answers."}]
        },
        "related_work": {
          "prior_work": ["Answer-only memory benchmarks"],
          "novelty": "It evaluates grounded answerability rather than answer match alone.",
          "repackaging_risk": "It is an evaluation lens, not a new memory store.",
          "evidence": [{"quote": "grounded answerability rather than answer match"}]
        },
        "limitations": {
          "explicit_limitations": ["It only evaluates benchmark-style tasks."],
          "inferred_weaknesses": ["Deployment behavior remains untested."],
          "evidence": [{"quote": "only evaluates benchmark-style tasks"}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Medium",
          "weak_evaluations": ["No long-horizon deployment evaluation"],
          "missing_ablations": ["No retrieval-format ablation"],
          "bottom_line": "The useful contribution is the evaluation lens.",
          "evidence": [{"quote": "useful contribution is the evaluation lens"}]
        },
        "plain_language_example": "A correct answer without evidence should not get full credit.",
        "essence": "The source reframes memory quality as grounded recall.",
        "unsupported_or_rejected_claims": []
      }
    }
    """
