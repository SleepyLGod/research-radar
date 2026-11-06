"""Fact review and exact final-language review use complete original sources."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS
from test_paper_reading import _claim_units_fixture

from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import ReaderContextBudget
from research_radar.analysis.review import model_review_publishable_claims, reviewed_analysis_claims
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)
from research_radar.pipeline import daily, paper
from research_radar.storage.files import read_json, read_jsonl

FACT = "Memory benchmark fixture."
CHINESE_CLAIM = "实验仅覆盖 memory benchmark，不代表真实部署。"
CHINESE_PARAGRAPH = "这项研究讨论 memory benchmark 的评测范围；这些实验不能直接解释真实部署的表现。"


class OfflineProvider:
    """Return controlled responses; all production parsing and composition stay real."""

    name = "offline-publication"
    reader_contexts = {**OFFLINE_READER_CONTEXTS,
                       "fake-localizer": ReaderContextBudget(1000000, 32768, 8192)}

    def __init__(self, responses: list[str], order: list[str], label: str) -> None:
        self.responses = list(responses)
        self.order = order
        self.label = label
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.order.append(self.label)
        self.messages.append(messages)
        assert self.responses, "No unbudgeted call is allowed"
        from reader_fixtures import source_response

        return ModelResponse(content=source_response(self.responses.pop(0), messages), model=model)


def reading_response() -> str:
    """One explicit source-bound claim and one candidate explanation."""
    payload = json.loads(_claim_units_fixture([FACT]))
    body = payload["deep_readings"]
    body["claim_units"][0]["claim_id"] = "c1"
    body["reader_explanation"] = {
        "solution_walkthrough": [{"text": FACT, "supporting_claim_ids": ["c1"]}],
    }
    return json.dumps(payload)


def translations() -> list[str]:
    """Offline Chinese proposals, not real model outputs or judgments."""
    return [json.dumps({"readings": [{"index": 0, "reader_explanation": {
        "solution_walkthrough": [{"text": CHINESE_PARAGRAPH,
                                  "supporting_claim_ids": ["c1"]}],
    }}]}, ensure_ascii=False), json.dumps({"claims": [
        {"index": 0, "text": "Experiment: " + CHINESE_CLAIM},
    ], "sources": [], "figures": []}, ensure_ascii=False)]


@pytest.mark.parametrize("change", ["evidence", "metadata", "status", "length"])
def test_translation_cannot_change_identity_or_promote_before_final_review(change: str) -> None:
    original = Claim(text=FACT, status=ClaimStatus.NEEDS_REVIEW,
                     evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote=FACT)])
    candidate = replace(original, text=CHINESE_CLAIM)
    if change == "evidence":
        candidate = replace(candidate, evidence=[])
    elif change == "metadata":
        candidate = replace(candidate, metadata={"paper_reading": {"claim_id": "other"}})
    elif change == "status":
        candidate = replace(candidate, status=ClaimStatus.SUPPORTED)
    provider = OfflineProvider([], [], "forbidden")
    with pytest.raises(AnalysisError):
        model_review_publishable_claims([candidate] if change != "length" else [], provider,
                                       model="fake-reviewer", analysis_claims=[original])
    assert not provider.messages


def test_original_analysis_never_inherits_a_different_papers_review() -> None:
    original = Claim(text=FACT, status=ClaimStatus.SUPPORTED,
                     evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote=FACT)])
    alien = replace(original, evidence=[replace(original.evidence[0], source_url="https://other.org")])
    with pytest.raises(AnalysisError):
        reviewed_analysis_claims([original], [alien])


@pytest.mark.parametrize("bad", ["missing_paragraph", "changed_quantity", "missing_claim_text"])
def test_unusable_translation_keeps_originals_for_audit_but_cannot_publish_as_chinese(
    bad: str,
) -> None:
    from test_explanation_support_contract import _reading

    original = Claim(text="Experiment: Accuracy is 70%.", status=ClaimStatus.SUPPORTED,
                     evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote="70%")])
    reading = _reading("Accuracy is 70%.", ["c1"])
    replies = [
        {"readings": [{"index": 0, "reader_explanation": {"opening_context": [
            {"text": "准确率为 70%。", "supporting_claim_ids": ["c1"]},
        ]}}]},
        {"claims": [{"index": 0, "text": "Experiment: 准确率为 70%。"}]},
    ]
    if bad == "missing_paragraph":
        replies[0]["readings"][0]["reader_explanation"] = {}
    elif bad == "changed_quantity":
        replies[1]["claims"][0]["text"] = "Experiment: 准确率为 99%。"
    else:
        replies[1]["claims"][0].pop("text")
    provider = OfflineProvider(
        [json.dumps(v, ensure_ascii=False) for v in replies], [], "translation",
    )
    result = localize_report_content(readings=[reading], claims=[original], sources=[],
                                     provider=provider, model="offline", language="zh")
    assert localization_failed(result)
    if bad == "changed_quantity":
        assert result.claims[0] == original
    elif bad == "missing_paragraph":
        assert result.readings[0].reader_explanation.opening_context[0].text == "Accuracy is 70%."


@pytest.mark.parametrize("entry", ["paper", "daily"])
@pytest.mark.parametrize("claim_status,paragraph_status,kept", [
    ("supported", "supported", True),
    ("supported", "needs_review", False),
    ("unsupported", "supported", False),
    ("supported", "missing", False),
])
def test_pipeline_reviews_actual_chinese_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str,
    claim_status: str, paragraph_status: str, kept: bool,
) -> None:
    order: list[str] = []
    reader = OfflineProvider([reading_response()], order, "reader")
    translator = OfflineProvider([json.dumps({"reader_explanation": {
        "solution_walkthrough": [{"text": CHINESE_PARAGRAPH, "supporting_claim_ids": ["c1"]}],
    }, "claims": [{"claim_id": "c1", "text": "Experiment: " + CHINESE_CLAIM}]},
        ensure_ascii=False)], order, "translation")
    decisions = [] if paragraph_status == "missing" else [{
        "paragraph_id": "p1.solution_walkthrough.1", "status": paragraph_status,
        "reason": "Offline fixture decision, not independent model evidence.",
    }]
    fact_decision = json.dumps({"decisions": [{"claim_index": 1, "status": "supported",
                                             "reason": "Offline fact review."}]})
    verifier = OfflineProvider([fact_decision, json.dumps({"decisions": [{
        "claim_index": 1, "status": claim_status, "reason": "Offline fixture.",
    }], "explanation_decisions": decisions})], order, "verifier")
    config = parse_config({"topics": [{"id": "memory", "queries": ["memory benchmark"],
                                      "concept_groups": {"memory": ["memory"],
                                                         "evaluation": ["benchmark"]}}]})

    full_text = (FACT + "\nFULL ORIGINAL: this is not a deployment evaluation.\n"
                 + "Complete full-paper input.\n" * 300)

    def ingest(source: SourceCandidate, _: Path) -> Artifact:
        return Artifact(source, full_text)

    options = dict(verifier=verifier, verifier_model="fake-reviewer", localizer=translator,
                   localization_model="fake-localizer", language="zh")
    if entry == "paper":
        monkeypatch.setattr(paper, "ingest_source", ingest)
        run = paper.run_paper(tmp_path, config, "memory", "https://example.invalid/paper",
                              reader, model="fake-reader", **options)
        public = (run / "paper.md").read_text()
    else:
        class Connector:
            name = "offline"

            def discover(self, context: object) -> list[SourceCandidate]:
                return [SourceCandidate(title="Memory benchmark paper",
                        url="https://example.com/paper", source_type=SourceType.PAPER,
                        source_name="offline", summary="Memory benchmark research.", score=1.0)]

        monkeypatch.setattr(daily, "ingest_source", ingest)
        run = daily.run_daily(tmp_path, config, "memory", [Connector()],
                              deep_reader=reader, deep_model="fake-reader", deep_limit=1, **options)
        public = (run / "wechat.html").read_text()
        assert read_json(run / "article_draft.json")["metadata"]["language"] == "zh"

    assert order == ["reader", "verifier", "translation", "verifier"]
    request = verifier.messages[1][1].content
    assert CHINESE_CLAIM in request and CHINESE_PARAGRAPH in request
    assert "FULL ORIGINAL: this is not a deployment evaluation." in request
    context = json.loads(request.split("FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n", 1)[1])
    assert full_text in context["full_sources"][0]["reading_packet"]
    assert (CHINESE_PARAGRAPH in public) is kept
    claims = read_jsonl(run / "claims.jsonl")
    assert claims[0]["text"].endswith(FACT), "Preserve the English analysis"
    assert claims[0]["status"] == claim_status
    localized = read_jsonl(run / "localized_readings.jsonl")
    paragraph = localized[0]["reader_explanation"]["solution_walkthrough"][0]
    assert paragraph["text"] == CHINESE_PARAGRAPH
    assert not reader.responses and not translator.responses and not verifier.responses


@pytest.mark.parametrize("entry", ["paper", "daily"])
def test_failed_body_stops_production_entry_before_display_and_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    order: list[str] = []
    reader = OfflineProvider([reading_response()], order, "reader")
    translator = OfflineProvider(['{"readings":[{"index":0}]}'], order, "translation")
    verifier = OfflineProvider([json.dumps({"decisions": [{"claim_index": 1,
        "status": "supported", "reason": "Offline factual review only."}]})], order, "verifier")
    config = parse_config({"topics": [{"id": "memory", "queries": ["memory benchmark"],
                                      "concept_groups": {"memory": ["memory"],
                                                         "evaluation": ["benchmark"]}}]})

    def ingest(source: SourceCandidate, _: Path) -> Artifact:
        return Artifact(source, FACT)

    options = dict(verifier=verifier, verifier_model="fake-reviewer", localizer=translator,
                   localization_model="fake-localizer", language="zh")
    if entry == "paper":
        monkeypatch.setattr(paper, "ingest_source", ingest)
        with pytest.raises(AnalysisError, match="Chinese report localization failed"):
            paper.run_paper(tmp_path, config, "memory", "https://example.invalid/paper",
                            reader, model="fake-reader", **options)
    else:
        from test_pipeline_fake import FakeConnector

        monkeypatch.setattr(daily, "ingest_source", ingest)
        with pytest.raises(AnalysisError, match="Chinese report localization failed"):
            daily.run_daily(tmp_path, config, "memory", [FakeConnector()],
                            deep_reader=reader, deep_model="fake-reader", deep_limit=1, **options)
    run = next((tmp_path / "runs").iterdir())

    assert order == ["reader", "verifier", "translation"]
    assert read_json(run / "manifest.json")["metadata"]["failure"]["stage"] == "localization"
    assert len(read_jsonl(run / "localization_attempts.jsonl")) == 1
    assert not (run / "paper.md").exists()
    assert not (run / "wechat.html").exists()
