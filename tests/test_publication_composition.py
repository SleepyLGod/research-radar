"""Fact extraction, Chinese composition and exact final review have separate roles."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_explanation_support_contract import _reading

from research_radar.analysis import localization
from research_radar.analysis.paper_reading import (
    PaperReading,
    ReaderExplanation,
    paper_reading_prompt,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import ReaderContextBudget, check_reader_input
from research_radar.analysis.reading_review import apply_explanation_decisions
from research_radar.analysis.review import apply_model_review_decisions
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

URL = "https://example.com/paper"
FACT = "The authors evaluate 12 simulated users."


class Composer:
    """Controlled answers; parsing and publication decisions use production code."""

    name = "offline"
    reader_contexts = {"offline": ReaderContextBudget(1000000, 32768, 8192)}

    def __init__(self, payload: dict | list[dict]) -> None:
        self.payloads = list(payload) if isinstance(payload, list) else [payload]
        self.requests: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        from reader_fixtures import source_response

        self.requests.append(messages)
        assert self.payloads, "Unexpected extra model call"
        return ModelResponse(source_response(json.dumps(self.payloads.pop(0), ensure_ascii=False),
                                             messages), model)


def candidates() -> tuple[PaperReading, Claim]:
    reading = replace(_reading(FACT, ["c1"]), source_url=URL,
                      reader_explanation=ReaderExplanation())
    claim = Claim("Experiment: " + FACT, ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(source_url=URL, quote=FACT)],
                  metadata={"paper_reading": {"claim_id": "c1", "section": "experiment"}})
    return reading, claim


def test_empty_reader_prose_is_composed_from_eligible_facts_not_translated_as_empty() -> None:
    reading, claim = candidates()
    provider = Composer([{"reader_explanation": {"experiment_interpretation": [
        {"text": "作者评估了 12 个模拟用户；这不是实际部署结论。", "supporting_claim_ids": ["c1"]},
    ]}}, {"claims": [{"index": 0, "text": "Experiment: 作者评估 12 个模拟用户。"}]}])
    result = localization.localize_report_content(readings=[reading], claims=[claim],
        sources=[], provider=provider, model="offline", language="zh")
    assert result.readings[0].reader_explanation.experiment_interpretation
    assert not localization.localization_failed(result)
    assert FACT in provider.requests[0][-1].content
    assert "unverified" in provider.requests[0][-1].content.lower()
    example = json.loads(provider.requests[0][-1].content.split(
        "Complete JSON shape (replace placeholder prose, retain nesting):\n", 1,
    )[1].split("\n\nUNVERIFIED CANDIDATES", 1)[0])
    assert isinstance(example["reader_explanation"], dict)
    assert result.readings[0].reader_explanation.experiment_interpretation[0].review is None


@pytest.mark.parametrize("entry", ["paper", "daily"])
def test_facts_composition_and_final_review_use_the_production_entry(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_chinese_publication import OfflineProvider, reading_response
    from test_pipeline_fake import FakeConnector

    from research_radar.config import parse_config
    from research_radar.pipeline import daily, paper

    order = []
    payload = json.loads(reading_response())
    payload["deep_readings"]["reader_explanation"] = {}
    reader = OfflineProvider([json.dumps(payload)], order, "reader")
    writer = OfflineProvider([json.dumps({"reader_explanation": {
        "experiment_interpretation": [{"text": "这项研究只测 memory benchmark。",
                                      "supporting_claim_ids": ["c1"]}],
    }, "claims": [{"claim_id": "c1", "text": "Experiment: memory benchmark 离线样例。"}]},
        ensure_ascii=False)], order, "writer")
    writer.reader_contexts = {"fake-localizer": ReaderContextBudget(1000000, 32768, 8192)}
    fact_decision = json.dumps({"decisions": [{"claim_index": 1, "status": "supported",
        "reason": "Controlled offline fact approval."}]})
    verifier = OfflineProvider([fact_decision, json.dumps({"decisions": [{"claim_index": 1,
        "status": "supported", "reason": "Controlled offline approval, not live evidence."}],
        "explanation_decisions": [{"paragraph_id": "p1.experiment_interpretation.1",
            "status": "supported", "reason": "Controlled offline approval."}]})],
        order, "verifier")
    module = paper if entry == "paper" else daily
    monkeypatch.setattr(module, "ingest_source", lambda source, _: Artifact(
        source, "Memory benchmark fixture.\n" * 400))
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    options = dict(verifier=verifier, verifier_model="fake-reviewer", localizer=writer,
                   localization_model="fake-localizer", language="zh")
    if entry == "paper":
        run = paper.run_paper(tmp_path, config, "memory", URL, reader,
                              model="fake-reader", **options)
        public = (run / "paper.md").read_text()
    else:
        run = daily.run_daily(tmp_path, config, "memory", [FakeConnector()],
            deep_reader=reader, deep_model="fake-reader", deep_limit=1,
            figure_extractor=lambda *_args, **_kwargs: [], **options)
        public = (run / "wechat.html").read_text()
    assert order == ["reader", "verifier", "writer", "verifier"]
    assert "这项研究只测 memory benchmark。" in public
    assert "这项研究只测 memory benchmark。" in verifier.messages[1][-1].content
    assert (run / "fact_claims.jsonl").exists()
    assert (run / "fact_review.json").exists()


@pytest.mark.parametrize("ids", [[], ["invented"], ["c1", "c1"], "c1"])
def test_composition_cannot_invent_or_infer_support(ids: object) -> None:
    reading, claim = candidates()
    provider = Composer({"reader_explanation": {"solution_walkthrough": [
        {"text": "不能靠猜测绑定。", "supporting_claim_ids": ids},
    ]}})
    result = localization.localize_report_content(readings=[reading], claims=[claim],
        sources=[], provider=provider, model="offline", language="zh")
    assert localization.localization_failed(result)
    assert len(provider.requests) == 1
    assert result.readings[0] == reading


def test_noneligible_fact_and_foreign_paper_are_not_writer_input() -> None:
    reading, claim = candidates()
    claim = replace(claim, metadata={**claim.metadata, "internal_payload": "DO NOT SEND INTERNAL"})
    rejected = replace(claim, text="DO NOT SEND REJECTED", status=ClaimStatus.NEEDS_REVIEW)
    foreign = replace(claim, text="DO NOT SEND FOREIGN", evidence=[
        EvidenceAnchor(source_url="https://other.org", quote=FACT)])
    provider = Composer({"reader_explanation": {"experiment_interpretation": [
        {"text": "作者评估 12 个模拟用户。", "supporting_claim_ids": ["c1"]},
    ]}})
    localization.compose_reading(reading, [claim, rejected, foreign], provider, model="offline")
    request = provider.requests[0][-1].content
    assert "DO NOT SEND" not in request


def test_live_writer_container_mistake_is_not_normalized_into_approval() -> None:
    reading, claim = candidates()
    provider = Composer({"reader_explanation": [
        {"text": "作者评估了 12 个模拟用户。", "supporting_claim_ids": ["c1"]},
    ]})
    result = localization.localize_report_content(readings=[reading], claims=[claim],
        sources=[], provider=provider, model="offline", language="zh")
    assert localization.localization_failed(result)
    assert result.readings == [reading]
    assert len(provider.requests) == 1


def test_final_review_removes_false_ranking_without_promoting_composed_prose() -> None:
    reading, claim = candidates()
    claim = replace(claim, text="Experiment: Letta is highest at 0.8435.")
    from research_radar.analysis.paper_reading import ReaderExplanationParagraph

    reading = replace(reading, reader_explanation=ReaderExplanation(
        experiment_interpretation=[ReaderExplanationParagraph("Letta 排名第一。", ["c1"])],
    ))
    reviewed, _ = apply_model_review_decisions([claim], json.dumps({"decisions": [
        {"claim_index": 1, "status": "unsupported", "reason": "MemOS 0.8449 is higher."},
    ]}))
    readings = apply_explanation_decisions([reading], reviewed, {"explanation_decisions": [
        {"paragraph_id": "p1.experiment_interpretation.1", "status": "supported", "reason": "bad"},
    ]}, source_urls={URL})
    from research_radar.analysis.explanation_policy import public_explanation

    public, _ = public_explanation(readings[0].reader_explanation, reviewed, source_url=URL)
    assert not public["experiment_interpretation"]


def test_facts_only_reader_does_not_request_a_second_article() -> None:
    artifact = Artifact(SourceCandidate("Paper", URL, SourceType.PAPER, "fixture"), FACT)
    prompt = paper_reading_prompt(artifact, facts_only=True)
    assert '"reader_explanation":{}' in prompt
    assert "solution_walkthrough must be the most detailed" not in prompt
    assert "complete available extracted text" in prompt


def test_soft_estimate_keeps_full_input_and_reports_warning() -> None:
    from research_radar.analysis.providers import Message

    provider = Composer({})
    provider.reader_contexts = {"offline": ReaderContextBudget(100, 20, 10, soft_limit=True)}
    messages = [Message("user", "完整原文" * 40)]
    before = messages[0].content
    audit = check_reader_input(messages, provider, model="offline")
    assert audit["status"] == "exceeds_estimate"
    assert messages[0].content == before
