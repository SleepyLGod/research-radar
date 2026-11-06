"""Facts survive prose rejection without inheriting another text's approval."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_publication_composition import FACT, URL, Composer, candidates

from research_radar.analysis import localization, review
from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
from research_radar.analysis.reading_review import apply_explanation_decisions
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType


def approved_fact():
    """Review a literal fixture fact through the shared review entry, not a status flag."""
    reading, claim = candidates()
    artifact = Artifact(SourceCandidate("Paper", URL, SourceType.PAPER, "fixture"), FACT)
    provider = Composer({"decisions": [{"claim_index": 1, "status": "supported",
                                       "reason": "Offline source-grounded fixture."}]})
    result = review.review_publication_facts([claim], provider, model="offline",
        readings=[reading], artifacts=[artifact])
    return reading, result.claims[0]


def test_fact_approval_is_bound_to_text_evidence_and_source() -> None:
    _, claim = approved_fact()
    assert review.fact_is_reviewed(claim)
    assert not review.fact_is_reviewed(replace(claim, text="Every model call uses GPT."))
    assert not review.fact_is_reviewed(replace(claim, evidence=[
        replace(claim.evidence[0], source_url="https://other.org/paper")]))
    assert not review.fact_is_reviewed(replace(claim, status=ClaimStatus.NEEDS_REVIEW))


def test_invalid_fact_review_stops_before_writing() -> None:
    reading, claim = candidates()
    provider = Composer({"decisions": []})
    with pytest.raises(AnalysisError, match="fact review"):
        review.review_publication_facts([claim], provider, model="offline",
            readings=[reading], artifacts=[])
    assert len(provider.requests) == 0  # Missing original source must fail locally.


def test_one_writer_call_translates_facts_and_composes_prose() -> None:
    reading, claim = approved_fact()
    provider = Composer({"reader_explanation": {"experiment_interpretation": [
        {"text": "作者用 12 个模拟用户做评估。", "supporting_claim_ids": ["c1"]},
    ]}, "claims": [{"claim_id": "c1", "text": "Experiment: 作者评估 12 个模拟用户。"}]})
    result = localization.localize_report_content(readings=[reading], claims=[claim], sources=[],
        provider=provider, model="offline", language="zh", verified_facts=True)
    assert not localization.localization_failed(result)
    assert len(provider.requests) == 1
    assert result.claims[0].text == "Experiment: 作者评估 12 个模拟用户。"
    assert result.claims[0].evidence == claim.evidence
    assert result.claims[0].metadata == claim.metadata
    assert result.readings[0].reader_explanation.experiment_interpretation[0].review is None
    assert "Chinese public writing style" in provider.requests[0][-1].content
    prompt = provider.requests[0][-1].content
    assert "UNVERIFIED CANDIDATES" not in prompt
    example = json.loads(prompt.split(
        "Complete JSON shape (replace placeholder prose, retain nesting):\n", 1,
    )[1].split("\n\nFACT-REVIEWED CANDIDATES", 1)[0])
    assert set(example) == {"reader_explanation", "claims"}


@pytest.mark.parametrize("bad", ["missing", "duplicate", "foreign", "changed_quantity"])
def test_combined_writer_cannot_drop_or_reassign_facts(bad: str) -> None:
    reading, claim = approved_fact()
    translations = [{"claim_id": "c1", "text": "Experiment: 作者评估 12 个模拟用户。"}]
    if bad == "missing":
        translations = []
    elif bad == "duplicate":
        translations *= 2
    elif bad == "foreign":
        translations[0]["claim_id"] = "other"
    else:
        translations[0]["text"] = "Experiment: 作者评估 120 个模拟用户。"
    provider = Composer({"reader_explanation": {"experiment_interpretation": [
        {"text": "作者评估 12 个模拟用户。", "supporting_claim_ids": ["c1"]},
    ]}, "claims": translations})
    result = localization.localize_report_content(readings=[reading], claims=[claim], sources=[],
        provider=provider, model="offline", language="zh", verified_facts=True)
    assert localization.localization_failed(result)
    assert result.claims == [claim]
    assert len(provider.requests) == 1


def test_rejected_mixed_paragraph_does_not_hide_independent_approved_fact() -> None:
    reading, first = candidates()
    second = replace(first, text="Experiment: The results are macro averaged.", metadata={
        "paper_reading": {"claim_id": "c2", "section": "experiment"}})
    claims, _ = review.apply_model_review_decisions([first, second], json.dumps({"decisions": [
        {"claim_index": i, "status": "supported", "reason": "Offline fixture."} for i in (1, 2)
    ]}))
    explanation = ReaderExplanation(experiment_interpretation=[
        ReaderExplanationParagraph("The results are macro averaged.", ["c2"]),
        ReaderExplanationParagraph("12 users; all model calls use GPT.", ["c1"]),
    ])
    reading = replace(reading, reader_explanation=explanation)
    reviewed = apply_explanation_decisions([reading], claims, {"explanation_decisions": [
        {"paragraph_id": "p1.experiment_interpretation.1", "status": "supported",
         "reason": "Supported aggregation."},
        {"paragraph_id": "p1.experiment_interpretation.2", "status": "needs_review",
         "reason": "Unjustified all-calls scope."},
    ]}, source_urls={URL})[0]
    public, _ = public_explanation(reviewed.reader_explanation, claims, source_url=URL)
    assert FACT in public["experiment_interpretation"]
    assert public["experiment_interpretation"].count("macro averaged") == 1
    assert "all model calls" not in public["experiment_interpretation"]
    assert reviewed.reader_explanation.experiment_interpretation[1].text.endswith("use GPT.")


@pytest.mark.parametrize("entry,missing_verifier", [
    ("paper", False), ("daily", False), ("daily", True),
])
def test_bad_fact_review_stops_production_before_writer(
    entry: str, missing_verifier: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_chinese_publication import OfflineProvider, reading_response
    from test_pipeline_fake import FakeConnector

    from research_radar.config import parse_config
    from research_radar.pipeline import daily, paper

    order: list[str] = []
    reader = OfflineProvider([reading_response()], order, "reader")
    verifier = (None if missing_verifier else
                OfflineProvider(['{"decisions": []}'], order, "verifier"))
    writer = OfflineProvider([], order, "forbidden-writer")
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    module = paper if entry == "paper" else daily
    monkeypatch.setattr(module, "ingest_source", lambda source, _: Artifact(
        source, "Memory benchmark fixture.\n" * 400))
    options = dict(verifier=verifier, verifier_model="fake-reviewer", localizer=writer,
                   localization_model="fake-localizer", language="zh")
    with pytest.raises(
        AnalysisError, match="Verifier" if missing_verifier else "fact review",
    ) as failure:
        if entry == "paper":
            paper.run_paper(tmp_path, config, "memory", URL, reader, model="fake-reader", **options)
        else:
            daily.run_daily(tmp_path, config, "memory", [FakeConnector()],
                deep_reader=reader, deep_model="fake-reader", deep_limit=1, **options)
    assert order == (["reader"] if missing_verifier else ["reader", "verifier"])
    run = next((tmp_path / "runs").iterdir())
    if not missing_verifier:
        assert (run / "reader_claims.jsonl").exists()
        assert (run / "readings.jsonl").exists()
    manifest = json.loads((run / "manifest.json").read_text())
    run_error = json.loads((run / "run_error.json").read_text())
    assert manifest["metadata"]["failure"] == run_error
    assert run_error["stage"] == "verifier"
    assert run_error["provider"] == (verifier.name if verifier is not None else None)
    assert run_error["model"] == "fake-reviewer"
    assert run_error["error_type"] == type(failure.value).__name__
    assert run_error["message"] == str(failure.value)
    assert not (run / "final_review.json").exists()
    for name in ("article_draft.json", "paper.md", "daily.md", "deep_reading.md", "wechat.html"):
        assert not (run / name).exists()


def test_another_papers_approved_fact_cannot_fill_this_papers_section() -> None:
    _, claim = approved_fact()
    public, _ = public_explanation(ReaderExplanation(), [claim], source_url="https://other.org")
    assert not any(public.values())
