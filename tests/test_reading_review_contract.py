"""Offline paragraph review, full context and publication boundary regressions."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS
from test_explanation_support_contract import FACT, UNRELATED, _reading
from test_paper_reading import _artifact

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.localization import _localized_reader_explanation
from research_radar.analysis.paper_reading import parse_paper_reading
from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.reader_input import ReaderContextBudget, ReaderInputError
from research_radar.analysis.review import model_review_publishable_claims
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor


class ReviewingProvider:
    """Return explicit offline decisions and retain the actual request."""

    name = "offline-review"
    reader_contexts = OFFLINE_READER_CONTEXTS

    def __init__(self, status: str = "supported", *, decisions: object = None) -> None:
        self.status = status
        self.decisions = decisions
        self.messages = []

    def complete(self, messages: list, *, model: str) -> ModelResponse:
        self.messages.append(messages)
        return ModelResponse(content=json.dumps({
            "decisions": [{"claim_index": 1, "status": "supported", "reason": "Source agrees."}],
            "explanation_decisions": self.decisions if self.decisions is not None else [{
                "paragraph_id": "p1.opening_context.1", "status": self.status,
                "reason": "Read the full evaluation context, not only the cited quote.",
            }],
        }), model=model)


def claim() -> Claim:
    """One source-bound, locally eligible claim, before model review."""
    source = _artifact().source
    return Claim(text=f"Experiment: {FACT}", status=ClaimStatus.SUPPORTED,
                 evidence=[EvidenceAnchor(source_url=source.url, source_title=source.title,
                                          quote=FACT)],
                 metadata={"paper_reading": {"claim_id": "c20", "section": "experiment"}})


def review(provider: ReviewingProvider, text: str = FACT):
    artifact = replace(_artifact(), text=f"{FACT}\nFULL CONTEXT: failed sessions were excluded.")
    return model_review_publishable_claims(
        [claim()], provider, model="offline-model", readings=[_reading(text, ["c20"])],
        artifacts=[artifact],
    )


def test_one_call_reviews_claim_and_exact_paragraph_with_complete_source() -> None:
    provider = ReviewingProvider()
    result = review(provider)
    assert len(provider.messages) == 1
    prompt = provider.messages[0][1].content
    assert "FULL CONTEXT: failed sessions were excluded." in prompt
    assert "p1.opening_context.1" in prompt
    assert FACT in prompt
    public, audit = public_explanation(
        result.readings[0].reader_explanation, result.claims, source_url=_artifact().source.url,
    )
    assert public["opening_context"] == FACT
    assert audit["kept_count"] == 1


@pytest.mark.parametrize("decisions", [[], [{"paragraph_id": "unknown", "status": "supported"}],
    [{"paragraph_id": "p1.opening_context.1", "status": "supported"}] * 2,
    [{"paragraph_id": "p1.opening_context.1", "status": "invalid"}]])
def test_missing_invalid_duplicate_or_unknown_decisions_do_not_publish(decisions: object) -> None:
    result = review(ReviewingProvider(decisions=decisions), UNRELATED)
    public, _ = public_explanation(
        result.readings[0].reader_explanation, result.claims, source_url=_artifact().source.url,
    )
    assert public["opening_context"] == ""
    assert FACT in public["experiment_interpretation"]
    assert result.readings[0].reader_explanation.opening_context[0].text == UNRELATED


def test_rejected_prose_does_not_reject_its_still_supported_claim() -> None:
    result = review(ReviewingProvider("needs_review"), UNRELATED)
    public, _ = public_explanation(
        result.readings[0].reader_explanation, result.claims, source_url=_artifact().source.url,
    )
    assert public["opening_context"] == ""
    assert result.claims[0].is_publishable()


def test_paragraph_approval_cannot_override_a_rejected_supporting_claim() -> None:
    class RejectingClaim(ReviewingProvider):
        def complete(self, messages: list, *, model: str) -> ModelResponse:
            response = super().complete(messages, model=model)
            payload = json.loads(response.content)
            payload["decisions"][0]["status"] = "needs_review"
            return ModelResponse(content=json.dumps(payload), model=model)

    result = review(RejectingClaim())
    public, audit = public_explanation(
        result.readings[0].reader_explanation, result.claims, source_url=_artifact().source.url,
    )
    assert public["opening_context"] == ""
    assert audit["kept_count"] == 0


@pytest.mark.parametrize("change", ["text", "ids", "claim", "source", "status", "duplicate"])
def test_approval_is_not_reusable_after_content_or_support_changes(change: str) -> None:
    result = review(ReviewingProvider())
    paragraph = result.readings[0].reader_explanation.opening_context[0]
    claims = result.claims
    if change == "text":
        paragraph = replace(paragraph, text=UNRELATED)
    elif change == "ids":
        paragraph = replace(paragraph, supporting_claim_ids=["other"])
    elif change == "claim":
        claims = [replace(claims[0], text="Experiment: translated or changed assertion")]
    elif change == "source":
        claims = [replace(claims[0], evidence=[replace(claims[0].evidence[0], source_url="https://other.invalid")])]
    elif change == "status":
        claims = [replace(claims[0], status=ClaimStatus.NEEDS_REVIEW)]
    else:
        claims = claims * 2
    explanation = replace(result.readings[0].reader_explanation, opening_context=[paragraph])
    public, _ = public_explanation(explanation, claims, source_url=_artifact().source.url)
    assert public["opening_context"] == ""


def test_full_context_review_stops_before_call_when_capacity_is_unknown() -> None:
    provider = ReviewingProvider()
    provider.reader_contexts = {}
    with pytest.raises(ReaderInputError, match="context_unknown"):
        review(provider)
    assert not provider.messages


def test_full_context_review_never_truncates_to_fit_a_small_window() -> None:
    provider = ReviewingProvider()
    provider.reader_contexts = {"offline-model": ReaderContextBudget(2000, 100, 100)}
    with pytest.raises(ReaderInputError, match="context_exceeded"):
        review(provider)
    assert not provider.messages


def test_missing_source_cannot_authorize_a_paragraph() -> None:
    provider = ReviewingProvider()
    result = model_review_publishable_claims(
        [claim()], provider, model="offline-model", readings=[_reading(FACT, ["c20"])],
        artifacts=[],
    )
    public, _ = public_explanation(
        result.readings[0].reader_explanation, result.claims, source_url=_artifact().source.url,
    )
    assert public["opening_context"] == ""


def test_duplicate_claim_decisions_cannot_authorize_dependent_prose() -> None:
    from research_radar.analysis.review import apply_model_review_decisions

    claims, findings = apply_model_review_decisions([claim()], json.dumps({"decisions": [
        {"claim_index": 1, "status": "supported"},
        {"claim_index": 1, "status": "supported"},
    ]}))
    assert not claims[0].is_publishable()
    assert any(f.metadata.get("kind") == "model_review_duplicate_index" for f in findings)


def test_schema_bound_reader_cannot_accidentally_constrain_verifier() -> None:
    from research_radar.exceptions import AnalysisError

    provider = ReviewingProvider()
    provider.response_schema = {"type": "object"}
    with pytest.raises(AnalysisError, match="schema.*Verifier"):
        review(provider)
    assert not provider.messages


def test_actual_translation_does_not_inherit_english_paragraph_approval() -> None:
    result = review(ReviewingProvider())
    translated, _ = _localized_reader_explanation(
        result.readings[0].reader_explanation,
        {"opening_context": [{"text": "评测覆盖了 12 个问题。", "supporting_claim_ids": ["c20"]}]},
        findings=[],
    )
    assert translated.opening_context[0].review is None
    public, _ = public_explanation(translated, result.claims, source_url=_artifact().source.url)
    assert public["opening_context"] == ""


def test_reader_cannot_self_approve_or_choose_its_source_identity() -> None:
    from test_paper_reading import _claim_units_fixture

    payload = json.loads(_claim_units_fixture([FACT]))
    body = payload["deep_readings"]
    body["source_url"] = "https://wrong.invalid"
    body["reader_explanation"] = {"opening_context": [{
        "text": UNRELATED, "supporting_claim_ids": ["c1"],
        "review": {"status": "supported", "binding_sha256": "fake"},
    }]}
    reading = parse_paper_reading(json.dumps(payload), _artifact())
    assert reading.source_url == _artifact().source.url
    assert reading.reader_explanation.opening_context[0].review is None


def test_same_claim_id_in_other_paper_cannot_support_this_paragraph() -> None:
    from research_radar.analysis.reading_review import apply_explanation_decisions

    result = review(ReviewingProvider())
    other = replace(result.readings[0], source_url="https://other.invalid/paper")
    reviewed = apply_explanation_decisions(
        [result.readings[0], other], result.claims, {"explanation_decisions": [
            {"paragraph_id": f"p{i}.opening_context.1", "status": "supported", "reason": "Agrees"}
            for i in [1, 2]
        ]}, source_urls={other.source_url, result.readings[0].source_url},
    )
    first_public, _ = public_explanation(
        reviewed[0].reader_explanation, result.claims, source_url=reviewed[0].source_url,
    )
    assert first_public["opening_context"]
    other_public, _ = public_explanation(
        reviewed[1].reader_explanation, result.claims, source_url=reviewed[1].source_url,
    )
    assert not other_public["opening_context"]


def test_single_paper_composition_checks_current_reading_identity() -> None:
    from research_radar.compose.paper import render_paper_brief

    prose = "The twelve-question evaluation defines the scope of this result."
    result = review(ReviewingProvider(), prose)
    reading = result.readings[0]
    assert prose in render_paper_brief(reading, result.claims)
    changed = replace(reading, title="Other paper", source_url="https://other.invalid/paper")
    assert prose not in render_paper_brief(changed, result.claims)
    assert FACT not in render_paper_brief(changed, result.claims)


@pytest.mark.parametrize("mode", ["daily", "paper"])
@pytest.mark.parametrize("approved", [True, False])
def test_production_entry_publishes_only_explicitly_reviewed_paragraphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, approved: bool,
) -> None:
    from test_pipeline_fake import (
        DEEP_READING_FIXTURE_TEXT,
        FakeConnector,
        SequenceProvider,
        _deep_reading_claim_units_json,
    )

    from research_radar.config import parse_config
    from research_radar.models import Artifact
    from research_radar.pipeline import daily, paper
    from research_radar.storage.files import read_jsonl

    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    payload = json.loads(_deep_reading_claim_units_json())
    body = payload["deep_readings"]
    # Keep the tested source fact; this prose is a distinct surface requiring its own decision.
    prose = "This explains the benchmark evaluation setting."
    body["claim_units"][0]["claim_id"] = "c1"
    body["reader_explanation"] = {
        "opening_context": [{"text": prose, "supporting_claim_ids": ["c1"]}],
    }
    reader = SequenceProvider([json.dumps(payload)])
    verifier = SequenceProvider([json.dumps({
        "decisions": [{"claim_index": 1, "status": "supported", "reason": "Offline fixture"}],
        "explanation_decisions": [{"paragraph_id": "p1.opening_context.1",
            "status": "supported" if approved else "needs_review", "reason": "Offline fixture"}],
    })])
    monkeypatch.setattr(daily if mode == "daily" else paper, "ingest_source",
                        lambda source, _: Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT))
    if mode == "daily":
        run = daily.run_daily(
            tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
            deep_limit=1, verifier=verifier, figure_extractor=lambda *_a, **_k: [],
        )
        paths = [run / "daily.md", run / "wechat.html", run / "article_draft.json"]
    else:
        run = paper.run_paper(tmp_path, config, "memory", "https://example.com/paper",
                              reader, model="offline", verifier=verifier)
        paths = [run / "paper.md"]
    assert all((prose in path.read_text()) is approved for path in paths)
    saved = read_jsonl(run / "readings.jsonl")[0]["reader_explanation"]
    assert saved["opening_context"][0]["text"] == prose
    assert len(verifier.messages) == 1
