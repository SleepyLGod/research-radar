from pathlib import Path

from research_radar.analysis.providers import Message, ModelResponse, StaticProvider
from research_radar.config import parse_config
from research_radar.discovery.base import DiscoveryContext
from research_radar.exceptions import IngestionError
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType
from research_radar.pipeline import daily
from research_radar.pipeline.daily import run_daily
from research_radar.storage.files import read_json, read_jsonl

DEEP_READING_FIXTURE_TEXT = """
Agent memory systems require grounded retrieval.
Require cited memory evidence before crediting answers.
The paper studies grounded answerability rather than answer match alone.
The system only evaluates benchmark-style tasks.
The useful contribution is the evaluation lens.
Memory benchmarks reward unsupported answers.
The evaluation runs on a fixture benchmark.
Accuracy is the main fixture metric.
The fixture result shows grounded answers score higher.
""".strip()


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


class SequenceProvider:
    """Test provider that returns responses in order."""

    name = "sequence"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return the next fixture response."""

        if not self.responses:
            raise AssertionError("No more fixture responses")
        return ModelResponse(content=self.responses.pop(0), model=model)


class CapturingPaperConnector:
    name = "arxiv"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        self.queries = context.topic.queries
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
    assert (run_dir / "research_plan.json").exists()
    assert (run_dir / "run_progress.jsonl").exists()
    assert (run_dir / "wide_scan.json").exists()
    assert (run_dir / "source_selection.json").exists()
    assert (run_dir / "source_history_report.json").exists()
    assert (run_dir / "synthesis_outline.md").exists()
    assert (run_dir / "review_report.md").exists()
    assert (run_dir / "review_findings.jsonl").exists()
    assert (run_dir / "verification_actions.jsonl").exists()
    assert "A careful paper" in (run_dir / "daily.md").read_text(encoding="utf-8")
    progress = read_jsonl(run_dir / "run_progress.jsonl")
    assert [event["stage"] for event in progress][:3] == [
        "run",
        "discovery",
        "discovery",
    ]
    assert progress[-1]["stage"] == "run"
    assert progress[-1]["status"] == "completed"


def test_daily_pipeline_expands_queries_for_paper_connectors(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    connector = CapturingPaperConnector()

    run_dir = run_daily(tmp_path, config, "agent-memory", [connector])
    manifest = read_json(run_dir / "manifest.json")

    assert connector.queries == [
        "agent memory",
        "agent memory paper",
        "agent memory benchmark",
        "agent memory survey",
        "agent memory arxiv",
    ]
    assert manifest["metadata"]["research_plan"]["paper_query_count"] == 5
    assert manifest["metadata"]["query_expansion"]["arxiv"]["discovery_stage"] == "primary_sources"
    assert manifest["metadata"]["query_expansion"]["arxiv"]["expanded_queries"] == [
        "agent memory",
        "agent memory paper",
        "agent memory benchmark",
        "agent memory survey",
        "agent memory arxiv",
    ]


def test_daily_deep_reading_retry_writes_reader_attempt_audit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = SequenceProvider(["not json", _deep_reading_claim_units_json()])
    verifier = StaticProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"},
            {"claim_index": 2, "status": "unsupported", "risk": "high", "reason": "overbroad"}
          ]
        }
        """
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_model="fake-analyst",
        deep_limit=1,
        verifier=verifier,
        verifier_model="fake-reviewer",
    )

    attempts = read_jsonl(run_dir / "reader_attempts.jsonl")
    progress = read_jsonl(run_dir / "run_progress.jsonl")
    review_report = (run_dir / "review_report.md").read_text(encoding="utf-8")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert [attempt["status"] for attempt in attempts] == ["failed", "succeeded"]
    assert attempts[0]["error_message"]
    assert any(
        event["stage"] == "reader" and event["status"] == "started"
        for event in progress
    )
    assert not any("api_key" in str(event).lower() for event in progress)
    assert "## Reader Attempts" in review_report
    assert "Memory benchmarks reward unsupported answers." in daily_text


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


class PrecisionGateConnector:
    name = "precision-gate"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Memory in the LLM Era",
                url="https://arxiv.org/abs/2604.01707",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="This LLM memory paper evaluates agent memory with LOCOMO.",
                score=1.0,
            ),
            SourceCandidate(
                title="ZeRO-Prefill: Zero Redundancy Overheads in MoE Prefill Serving",
                url="https://arxiv.org/abs/2605.00010",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="A method to reduce redundancy in prefill serving for MoE models.",
                score=0.9,
            ),
            SourceCandidate(
                title="Analysis of Optimality of Large Language Models on Planning Problems",
                url="https://arxiv.org/abs/2605.00012",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="An analysis of whether LLMs reason optimally in planning problems.",
                score=0.8,
            ),
        ]


class RepoPrecisionConnector:
    name = "repo-precision"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Memory in the LLM Era",
                url="https://arxiv.org/abs/2604.01707",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="This LLM memory paper evaluates agent memory with LOCOMO.",
                score=1.0,
            ),
            SourceCandidate(
                title="agent-memory-benchmark",
                url="https://github.com/example/agent-memory-benchmark",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="Benchmark implementation for agent memory systems with LongMemEval.",
                score=0.9,
            ),
            SourceCandidate(
                title="TeleAI-UAGI/Awesome-Agent-Memory",
                url="https://github.com/TeleAI-UAGI/Awesome-Agent-Memory",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="A curated collection of systems, benchmarks, and papers on agent memory.",
                score=0.8,
            ),
            SourceCandidate(
                title="Samarth2001/LLM-Fine-tuning",
                url="https://github.com/Samarth2001/LLM-Fine-tuning",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary=(
                    "Parameter-efficient fine-tuning experiments for 7B LLMs "
                    "with QLoRA and memory optimization strategies."
                ),
                score=0.7,
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


def test_daily_repo_precision_gate_keeps_only_serious_repositories(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory systems", "LLM memory benchmark"],
                    "required_phrases": ["agent memory", "LLM memory", "LOCOMO", "LongMemEval"],
                }
            ],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [RepoPrecisionConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    sources = read_jsonl(run_dir / "sources.jsonl")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")
    review_report = (run_dir / "review_report.md").read_text(encoding="utf-8")
    by_title = {source["title"]: source for source in sources}

    assert len(sources) == 4
    assert ingested[0].title == "Memory in the LLM Era"
    assert "Memory in the LLM Era" in daily_text
    assert "agent-memory-benchmark" in daily_text
    assert "TeleAI-UAGI/Awesome-Agent-Memory" not in daily_text
    assert "Samarth2001/LLM-Fine-tuning" not in daily_text
    assert by_title["Samarth2001/LLM-Fine-tuning"]["metadata"]["relevance"]["status"] != "relevant"
    assert (
        by_title["TeleAI-UAGI/Awesome-Agent-Memory"]["metadata"]["daily_report_gate"]["status"]
        == "suppressed"
    )
    assert "research brief excludes repository resource lists" in review_report
    assert "research brief repo missing configured required phrase" in review_report


def test_daily_precision_gate_keeps_only_required_phrase_papers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory systems", "LLM memory benchmark"],
                    "required_phrases": ["agent memory", "LLM memory", "LOCOMO"],
                    "negative_phrases": ["prefill serving", "planning problems"],
                }
            ],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [PrecisionGateConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    sources = read_jsonl(run_dir / "sources.jsonl")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert ingested[0].title == "Memory in the LLM Era"
    assert "Memory in the LLM Era" in daily_text
    assert "ZeRO-Prefill" not in daily_text
    assert "Planning Problems" not in daily_text
    assert {
        source["title"]: source["metadata"]["relevance"]["status"] for source in sources
    } == {
        "Memory in the LLM Era": "relevant",
        "ZeRO-Prefill: Zero Redundancy Overheads in MoE Prefill Serving": "irrelevant",
        "Analysis of Optimality of Large Language Models on Planning Problems": "irrelevant",
    }


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
            text=DEEP_READING_FIXTURE_TEXT,
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
    assert "**Core:** Memory benchmarks reward unsupported answers." in deep_report
    assert "Why it matters: Scores can hide ungrounded guessing." in deep_report
    assert "Setup: The evaluation runs on a fixture benchmark." in deep_report
    assert "Metrics/benchmarks: Accuracy is the main fixture metric." in deep_report
    assert "Repackaging risk: It is an evaluation lens, not a new memory store." in deep_report


def test_daily_pipeline_writes_verification_actions_for_atomic_claims(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    reader = StaticProvider(_deep_reading_claim_units_json())
    verifier = StaticProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"},
            {
              "claim_index": 2,
              "status": "unsupported",
              "risk": "high",
              "reason": "The evaluation claim is broader than its evidence."
            }
          ],
          "follow_up_actions": [
            {
              "action_type": "split_claim",
              "claim_index": 2,
              "reason": "Separate benchmark scope from broad evaluation quality.",
              "query": "agent memory benchmark evidence support",
              "source_url": "https://example.com/paper"
            }
          ]
        }
        """
    )

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_model="fake-analyst",
        deep_limit=1,
        verifier=verifier,
        verifier_model="fake-reviewer",
    )

    manifest = read_json(run_dir / "manifest.json")
    claims = read_jsonl(run_dir / "claims.jsonl")
    actions = read_jsonl(run_dir / "verification_actions.jsonl")
    sources_before = read_jsonl(run_dir / "sources.jsonl")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")
    review_report = (run_dir / "review_report.md").read_text(encoding="utf-8")

    assert manifest["claim_count"] == 2
    assert manifest["publishable_claim_count"] == 1
    assert claims[0]["status"] == ClaimStatus.SUPPORTED
    assert claims[1]["status"] == ClaimStatus.UNSUPPORTED
    assert "Problem: Memory benchmarks reward unsupported answers." in daily_text
    assert "Experiment: The paper proves all agent memory evaluations are solved." not in daily_text
    assert actions[0]["action_type"] == "split_claim"
    assert actions[0]["claim_text"] == claims[1]["text"]
    assert "## Verification Actions" in review_report
    assert "Separate benchmark scope" in review_report
    assert read_jsonl(run_dir / "sources.jsonl") == sources_before


def test_daily_pipeline_repairs_deep_reading_anchor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    table_quote = "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"
    reader = StaticProvider(_missing_anchor_deep_reading_json())
    repair = StaticProvider(
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
        return Artifact(source=source, text=f"[page 12]\n{table_quote}")

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_model="fake-reader",
        deep_limit=1,
        anchor_repair_provider=repair,
        anchor_repair_model="fake-repair",
    )

    claims = read_jsonl(run_dir / "claims.jsonl")
    repairs = read_jsonl(run_dir / "anchor_repair.jsonl")
    draft = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert claims[0]["status"] == ClaimStatus.SUPPORTED
    assert repairs[0]["status"] == "accepted"
    assert "Ours reaches 38.79 overall F1" in draft


def test_daily_deep_required_disables_summary_fallback_when_ingestion_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        raise IngestionError("fixture ingestion failure")

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
    claims = read_jsonl(run_dir / "claims.jsonl")
    findings = read_jsonl(run_dir / "review_findings.jsonl")
    draft = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert manifest["claim_count"] == 0
    assert manifest["publishable_claim_count"] == 0
    assert claims == []
    assert "No claim passed evidence verification" in draft
    assert "A careful paper is relevant" not in draft
    assert any(
        finding["metadata"].get("kind") == "deep_ingestion_failed" for finding in findings
    )
    assert any(
        finding["metadata"].get("kind") == "deep_reading_required_but_missing"
        for finding in findings
    )


def test_daily_pipeline_omits_seen_sources_from_second_daily_run(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    run_daily(tmp_path, config, "agent-memory", [FakeConnector()])
    run_dir = run_daily(tmp_path, config, "agent-memory", [FakeConnector()])

    manifest = read_json(run_dir / "manifest.json")
    history_report = read_json(run_dir / "source_history_report.json")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert manifest["publishable_claim_count"] == 0
    assert manifest["metadata"]["source_history"]["omitted_seen_count"] == 1
    assert history_report["omitted_seen_sources"][0]["title"] == "A careful paper"
    assert "No new or updated sources passed the report gate." in daily_text
    assert "A careful paper" not in daily_text


class VersionedArxivConnector:
    name = "arxiv"

    def __init__(self) -> None:
        self.version = 1

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        version = self.version
        self.version += 1
        return [
            SourceCandidate(
                title="Memory in the LLM Era",
                url=f"http://arxiv.org/abs/2604.01707v{version}",
                canonical_id=f"2604.01707v{version}",
                source_type=SourceType.PAPER,
                source_name=self.name,
                summary="A paper about agent memory benchmark evaluation.",
                score=1.0,
            )
        ]


def test_daily_pipeline_reports_new_arxiv_version(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    connector = VersionedArxivConnector()

    run_daily(tmp_path, config, "agent-memory", [connector])
    run_dir = run_daily(tmp_path, config, "agent-memory", [connector])

    history_report = read_json(run_dir / "source_history_report.json")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert history_report["counts"]["version_update"] == 1
    assert "status=version_update" in daily_text
    assert "version=v2" in daily_text
    assert "Memory in the LLM Era" in daily_text


class WebAndPrimaryConnector:
    name = "web_search"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Agent Memory Web Context",
                url="https://example.com/agent-memory",
                source_type=SourceType.WEB,
                source_name=self.name,
                summary="A web page about agent memory systems.",
                score=0.4,
            )
        ]


def test_daily_pipeline_records_discovery_stage_metadata(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "discovery": {"trusted_domains": ["example.com"]},
        }
    )

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [WebAndPrimaryConnector()],
    )

    manifest = read_json(run_dir / "manifest.json")
    sources = read_jsonl(run_dir / "sources.jsonl")

    assert manifest["metadata"]["discovery"]["stage_counts"]["web_search"] == 1
    assert sources[0]["metadata"]["discovery_stage"] == "web_search"
    assert sources[0]["metadata"]["trusted_domain_match"] == "example.com"


class WebCanonicalPaperConnector:
    name = "web_search"
    diagnostics = {
        "provider": "tavily",
        "query_count": 2,
        "successful_query_count": 1,
        "failed_query_count": 1,
        "slow_query_count": 0,
        "candidate_count": 2,
        "canonical_paper_count": 1,
        "canonical_repository_count": 0,
        "generic_web_count": 1,
        "timeout_seconds": 30,
        "elapsed_seconds": 1.5,
        "queries": [
            {
                "query": "agent memory",
                "status": "failed",
                "candidate_count": 0,
                "elapsed_seconds": 0.5,
                "timeout_seconds": 30,
                "error_type": "TimeoutError",
            },
            {
                "query": "agent memory benchmark",
                "status": "succeeded",
                "candidate_count": 2,
                "elapsed_seconds": 1.0,
                "timeout_seconds": 30,
            },
        ],
    }

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="MemBench arXiv HTML",
                url="https://arxiv.org/abs/2506.21605v1",
                canonical_id="2506.21605v1",
                source_type=SourceType.PAPER,
                source_name=self.name,
                summary="An agent memory benchmark paper.",
                score=1.0,
                metadata={
                    "search_provider": "tavily",
                    "web_canonicalization": {
                        "source_type": "paper",
                        "rule": "arxiv",
                        "original_url": "https://arxiv.org/html/2506.21605v1",
                    },
                },
            ),
            SourceCandidate(
                title="Generic LLM app blog",
                url="https://example.com/generic-llm-app",
                source_type=SourceType.WEB,
                source_name=self.name,
                summary="A generic LLM application post.",
                score=0.4,
                metadata={"search_provider": "tavily"},
            ),
        ]


def test_daily_pipeline_writes_web_search_summary(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory"],
                    "required_phrases": ["agent memory"],
                }
            ],
        }
    )

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [WebCanonicalPaperConnector()],
    )

    manifest = read_json(run_dir / "manifest.json")
    summary = read_json(run_dir / "web_search_summary.json")

    assert manifest["metadata"]["web_search"]["canonical_paper_count"] == 1
    assert manifest["metadata"]["web_search"]["failed_query_count"] == 1
    assert manifest["metadata"]["discovery"]["connector_diagnostics"]["web_search"][
        "query_count"
    ] == 2
    assert summary["provider_counts"] == {"tavily": 2}
    assert summary["canonical_paper_count"] == 1
    assert summary["generic_web_count"] == 1
    assert summary["query_diagnostics"][0]["status"] == "failed"
    assert summary["filtered_web_noise_examples"][0]["title"] == "Generic LLM app blog"

    findings = read_jsonl(run_dir / "review_findings.jsonl")
    assert any(
        finding["metadata"].get("kind") == "web_search_query_failed"
        for finding in findings
    )


def test_daily_pipeline_marks_research_brief_without_paper_as_degraded(tmp_path: Path) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [RepoOnlyConnector()],
    )

    manifest = read_json(run_dir / "manifest.json")
    findings = read_jsonl(run_dir / "review_findings.jsonl")

    assert manifest["metadata"]["quality_gate"]["status"] == "degraded"
    assert any(
        finding["metadata"].get("kind") == "research_quality_gate" for finding in findings
    )


class PaperAndListConnector:
    name = "paper-and-list"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Awesome Agent Memory",
                url="https://github.com/example/awesome-agent-memory",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="A curated collection of agent memory systems and benchmarks.",
                score=1.0,
            ),
            SourceCandidate(
                title="Memory in the LLM Era",
                url="https://arxiv.org/abs/2604.01707",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="A paper about agent memory benchmark evaluation.",
                score=0.1,
            ),
        ]


class PaperAndRepoConnector:
    name = "paper-and-repo"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="agent-memory-benchmark",
                url="https://github.com/example/agent-memory-benchmark",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="Benchmark implementation for agent memory systems.",
                score=1.0,
            ),
            SourceCandidate(
                title="Memory in the LLM Era",
                url="https://arxiv.org/abs/2604.01707",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="A paper about agent memory benchmark evaluation.",
                score=0.1,
            ),
        ]


def test_daily_deep_reading_prefers_research_paper_over_repo(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [PaperAndRepoConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    manifest = read_json(run_dir / "manifest.json")

    assert ingested[0].title == "Memory in the LLM Era"
    assert manifest["metadata"]["deep_reading"]["source_intent"] == "research_brief"


def test_daily_deep_reading_prefers_paper_over_resource_list(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [PaperAndListConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    sources = read_jsonl(run_dir / "sources.jsonl")
    findings = read_jsonl(run_dir / "review_findings.jsonl")

    assert ingested[0].title == "Memory in the LLM Era"
    assert {
        source["title"]: source["metadata"]["source_role"]["role"] for source in sources
    } == {
        "Awesome Agent Memory": "survey_or_list",
        "Memory in the LLM Era": "benchmark_paper",
    }
    assert any(
        finding["metadata"].get("kind") == "deep_source_selection"
        and finding["metadata"].get("selected")
        and finding["claim_text"] == "Memory in the LLM Era"
        for finding in findings
    )


class ListOnlyConnector:
    name = "list-only"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Awesome Agent Memory",
                url="https://github.com/example/awesome-agent-memory",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="A curated collection of agent memory systems and benchmarks.",
                score=1.0,
            )
        ]


class RepoOnlyConnector:
    name = "repo-only"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="agent-memory-benchmark",
                url="https://github.com/example/agent-memory-benchmark",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="Benchmark implementation for agent memory systems.",
                score=1.0,
            )
        ]


def test_daily_deep_reading_does_not_fallback_to_repo_for_research_brief(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [RepoOnlyConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    manifest = read_json(run_dir / "manifest.json")
    readings = read_jsonl(run_dir / "readings.jsonl")
    claims = read_jsonl(run_dir / "claims.jsonl")
    source_selection = read_json(run_dir / "source_selection.json")
    draft = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert ingested == []
    assert readings == []
    assert claims == []
    assert manifest["publishable_claim_count"] == 0
    assert source_selection["selected_count"] == 0
    assert "No claim passed evidence verification" in draft


def test_daily_deep_reading_suppresses_resource_list_for_research_brief(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [ListOnlyConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    findings = read_jsonl(run_dir / "review_findings.jsonl")
    sources = read_jsonl(run_dir / "sources.jsonl")
    draft = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert ingested == []
    assert "Awesome Agent Memory" not in draft
    assert sources[0]["metadata"]["daily_report_gate"]["status"] == "suppressed"
    assert any(
        finding["metadata"].get("kind") == "daily_report_gate"
        and finding["claim_text"] == "Awesome Agent Memory"
        for finding in findings
    )
    assert any(
        finding["metadata"].get("kind") == "deep_reading_required_but_missing"
        for finding in findings
    )


class LowRelevancePaperAndStrongRepoConnector:
    name = "low-paper-strong-repo"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="LLMs Improving LLMs: Agentic Discovery for Test-Time Scaling",
                url="https://arxiv.org/abs/2605.06655",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="An LLM agent benchmark evaluation for test-time scaling.",
                score=1.0,
            ),
            SourceCandidate(
                title="go-agent-memory",
                url="https://github.com/example/go-agent-memory",
                source_type=SourceType.REPOSITORY,
                source_name="github",
                summary="An agent memory system with persistent recall.",
                score=0.1,
            ),
        ]


def test_daily_deep_reading_ignores_repo_when_only_viable_research_brief_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [LowRelevancePaperAndStrongRepoConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    source_selection = read_json(run_dir / "source_selection.json")
    sources = read_jsonl(run_dir / "sources.jsonl")

    assert ingested == []
    assert source_selection["selected_count"] == 0
    assert "centrality_score" in source_selection["ranked_sources"][0]
    assert "source_centrality" in sources[0]["metadata"]


def test_implementation_scan_can_deep_read_repo(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory"],
                    "source_intent": "implementation_scan",
                }
            ],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [RepoOnlyConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    readings = read_jsonl(run_dir / "readings.jsonl")

    assert ingested[0].title == "agent-memory-benchmark"
    assert readings


class TwoPaperRetryConnector:
    name = "two-paper-retry"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="Agent Memory Paper with Broken PDF",
                url="https://example.com/broken-paper",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="A paper about agent memory benchmark evaluation.",
                score=1.0,
            ),
            SourceCandidate(
                title="Agent Memory Paper with Valid PDF",
                url="https://example.com/valid-paper",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary="A paper about agent memory benchmark evaluation.",
                score=0.9,
            ),
        ]


class MixedRagPublicSourcesConnector:
    name = "mixed-rag-public"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        return [
            SourceCandidate(
                title="RAGChecker",
                url="https://openreview.net/forum?id=ragchecker",
                source_type=SourceType.PAPER,
                source_name="openreview",
                summary=(
                    "A retrieval augmented generation evaluation benchmark framework "
                    "for diagnosing RAG systems."
                ),
                score=1.0,
            ),
            SourceCandidate(
                title="An LLM-RAG Approach for Healthy Eating",
                url="https://arxiv.org/abs/2605.15213",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary=(
                    "A retrieval augmented generation evaluation benchmark for "
                    "personalized food and nutrition recommendations."
                ),
                score=0.9,
            ),
            SourceCandidate(
                title="DRAGON: Dynamic RAG Benchmark On News",
                url="https://arxiv.org/abs/2507.05713",
                source_type=SourceType.PAPER,
                source_name="arxiv",
                summary=(
                    "A retrieval augmented generation evaluation benchmark for Russian "
                    "news corpora."
                ),
                score=0.8,
            ),
        ]


def test_daily_deep_reading_retries_next_paper_after_ingestion_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )
    provider = StaticProvider(_deep_reading_json())
    ingested: list[SourceCandidate] = []

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        ingested.append(source)
        if source.url == "https://example.com/broken-paper":
            raise IngestionError("fixture ingestion failure")
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "agent-memory",
        [TwoPaperRetryConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    manifest = read_json(run_dir / "manifest.json")
    source_selection = read_json(run_dir / "source_selection.json")
    rows = {row["title"]: row for row in source_selection["ranked_sources"]}

    assert [source.title for source in ingested] == [
        "Agent Memory Paper with Broken PDF",
        "Agent Memory Paper with Valid PDF",
    ]
    assert manifest["metadata"]["deep_reading"]["reading_count"] == 1
    assert rows["Agent Memory Paper with Broken PDF"]["attempted_for_deep_reading"] is True
    assert rows["Agent Memory Paper with Broken PDF"]["deep_reading_status"] == "ingestion_failed"
    assert rows["Agent Memory Paper with Broken PDF"]["selected_for_deep_reading"] is False
    assert rows["Agent Memory Paper with Valid PDF"]["attempted_for_deep_reading"] is True
    assert rows["Agent Memory Paper with Valid PDF"]["deep_reading_status"] == "succeeded"
    assert rows["Agent Memory Paper with Valid PDF"]["selected_for_deep_reading"] is True


def test_daily_public_sources_are_curated_without_changing_audit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "rag-systems",
                    "queries": ["RAG systems evaluation"],
                    "paper_queries": ["retrieval augmented generation evaluation benchmark"],
                    "concept_groups": {
                        "agent_context": ["RAG", "retrieval augmented generation"],
                        "memory_mechanism": ["RAG systems", "retrieval system"],
                        "evaluation_signal": ["RAG benchmark", "RAG evaluation", "benchmark"],
                    },
                }
            ],
        }
    )
    provider = StaticProvider(_deep_reading_json())

    def fake_ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", fake_ingest_source)

    run_dir = run_daily(
        tmp_path,
        config,
        "rag-systems",
        [MixedRagPublicSourcesConnector()],
        deep_reader=provider,
        deep_model="fake-analyst",
        deep_limit=1,
    )

    sources = read_jsonl(run_dir / "sources.jsonl")
    source_selection = read_json(run_dir / "source_selection.json")
    article_draft = read_json(run_dir / "article_draft.json")
    daily_text = (run_dir / "daily.md").read_text(encoding="utf-8")

    assert {source["title"] for source in sources} == {
        "RAGChecker",
        "An LLM-RAG Approach for Healthy Eating",
        "DRAGON: Dynamic RAG Benchmark On News",
    }
    assert source_selection["selected_sources"][0]["title"] == "RAGChecker"
    assert {row["title"] for row in source_selection["ranked_sources"]} == {
        "RAGChecker",
        "An LLM-RAG Approach for Healthy Eating",
        "DRAGON: Dynamic RAG Benchmark On News",
    }
    assert "RAGChecker" in daily_text
    assert "Healthy Eating" not in daily_text
    assert "DRAGON" not in daily_text
    source_titles = [
        item["title"]
        for section in article_draft["sections"]
        if section["metadata"].get("kind") == "new_updated_sources"
        for item in section["metadata"]["sources"]
    ]
    assert source_titles == ["RAGChecker"]
    synthesis_outline = (run_dir / "synthesis_outline.md").read_text(encoding="utf-8")
    assert "RAGChecker" in synthesis_outline
    assert "Healthy Eating" in synthesis_outline
    assert "DRAGON" in synthesis_outline


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
        "experiments": {
          "setup": "The evaluation runs on a fixture benchmark.",
          "metrics_benchmarks": ["Accuracy is the main fixture metric."],
          "main_findings": "The fixture result shows grounded answers score higher.",
          "cost_robustness_findings": "unknown",
          "known_caveats": "unknown",
          "evidence": [{"quote": "The evaluation runs on a fixture benchmark."}]
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


def _deep_reading_claim_units_json() -> str:
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
        "claim_units": [
          {
            "section": "problem",
            "claim_kind": "fact",
            "text": "Memory benchmarks reward unsupported answers.",
            "evidence": [{"quote": "Memory benchmarks reward unsupported answers."}],
            "publishable_default": true
          },
          {
            "section": "experiment",
            "claim_kind": "interpretation",
            "text": "The paper proves all agent memory evaluations are solved.",
            "evidence": [
              {"quote": "The paper studies grounded answerability rather than answer match alone."}
            ],
            "publishable_default": true
          }
        ],
        "unsupported_or_rejected_claims": []
      }
    }
    """


def _missing_anchor_deep_reading_json() -> str:
    return """
    {
      "deep_readings": {
        "area_context": {
          "background": "Agent memory systems require grounded retrieval.",
          "evidence": [{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}]
        },
        "problem_solution": {
          "problem": "Agent memory systems require grounded retrieval.",
          "why_it_matters": "Benchmark tables compare methods.",
          "hidden_assumptions": [],
          "solution": "Agent memory systems require grounded retrieval.",
          "mechanism": "Agent memory systems require grounded retrieval.",
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
