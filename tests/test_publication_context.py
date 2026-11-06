"""Method and evaluation context use the existing factual and final review gates."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_paper_reading import _claim_units_fixture
from test_publication_composition import Composer

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.deep_reading import run_artifact_deep_reading
from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.paper_reading import (
    EvaluationContext,
    EvaluationContextItem,
    PaperReading,
    parse_paper_reading,
    reading_to_claims,
    validate_paper_reading,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import model_review_publishable_claims, review_publication_facts
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

URL = "https://example.test/context-paper"
BASE = "Memory benchmark fixture."
FLOW = "The system receives prior sessions, retrieves memories, and then answers the query."
DEPTH = "White-box retrieval uses top-3 memories."
DEPTH_QUOTE = "For white-box retrieval, K=3."
MACRO = "Scores are macro-averaged across conflict types."


def fixture() -> tuple[Artifact, str]:
    """Use explicit independent quotes, including a method absent from atomic claims."""
    source = SourceCandidate("Context paper", URL, SourceType.PAPER, "offline")
    artifact = Artifact(source, "\n".join([BASE, FLOW, DEPTH_QUOTE, MACRO]))
    payload = json.loads(_claim_units_fixture([BASE]))
    body = payload["deep_readings"]
    body["claim_units"][0]["claim_id"] = "c1"
    body["problem_solution"]["mechanism"] = FLOW
    body["problem_solution"]["evidence"] = [{"quote": FLOW, "location": "§2"}]
    body["evaluation_context"] = {
        "available_inputs": [{"text": DEPTH, "evidence": [{
            "quote": DEPTH_QUOTE, "location": "§3",
        }]}],
        "outcome_measurement": [{"text": MACRO, "evidence": [{
            "quote": MACRO, "location": "§3",
        }]}],
    }
    return artifact, json.dumps(payload)


def indexed_fixture() -> tuple[Artifact, str]:
    """New Reader outputs extract evaluation facts once and index their explicit IDs."""
    artifact, raw = fixture()
    payload = json.loads(raw)
    body = payload["deep_readings"]
    template = body["claim_units"][0]
    body["claim_units"].extend([
        {**template, "claim_id": "c2", "text": DEPTH,
         "evidence": [{"quote": DEPTH_QUOTE, "location": "§3"}]},
        {**template, "claim_id": "c3", "text": MACRO,
         "evidence": [{"quote": MACRO, "location": "§3"}]},
    ])
    body["evaluation_context"] = {
        "data_construction": [], "available_inputs": ["c2"], "outcome_measurement": ["c3"],
    }
    return artifact, json.dumps(payload)


@pytest.mark.parametrize("claim_text,quote,accepted", [
    ("White-box retrieval uses top-3 memories.",
     "For white-box analysis, 𝐾= 3for retrieval.", True),
    ("White-box retrieval uses top-5 memories.", "White-box retrieval uses K=5.", True),
    ("White-box retrieval uses K=3.", "White-box retrieval takes the top-3 memories.", True),
    ("White-box retrieval uses top-3 memories.", "Retrieval uses K=5 for 3 users.", False),
    ("White-box retrieval uses K=3.", "Retrieval uses K=5 for 3 users.", False),
    ("White-box retrieval uses top-3 memories.", "Retrieval uses batch_size=3.", False),
    ("White-box retrieval uses top-3 memories.", "Beam search uses K=3.", False),
    ("White-box retrieval uses top-3 memories.", "Retrieval uses K=3.5.", False),
    ("White-box retrieval uses top-3 memories.", "Retrieval compares K=3 and K=5.", False),
    ("Model-X3 retrieves memories.", "Retrieval uses K=3.", False),
])
def test_retrieval_depth_equivalence_does_not_erase_parameter_or_entity_identity(
    claim_text: str, quote: str, accepted: bool,
) -> None:
    artifact = Artifact(SourceCandidate("Paper", URL, SourceType.PAPER, "offline"), quote)
    claim = Claim(claim_text, ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(source_url=URL, quote=quote)])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].is_publishable() is accepted
    assert checked[0].text == claim_text
    assert checked[0].evidence == claim.evidence


def test_context_enters_fact_candidates_only_when_explicitly_requested() -> None:
    artifact, raw = fixture()
    reading = parse_paper_reading(raw, artifact)
    assert len(reading_to_claims(reading)) == 1
    candidates = reading_to_claims(reading, include_context_claims=True)
    assert {c.text for c in candidates} == {
        "Experiment: " + BASE, "Solution: " + FLOW, "Experiment: " + DEPTH, "Experiment: " + MACRO,
    }
    assert len({c.metadata["paper_reading"]["claim_id"] for c in candidates}) == 4
    assert all("fact_review" not in c.metadata for c in candidates)
    assert {c.metadata["paper_reading"]["context_field"] for c in candidates
            if c.metadata["paper_reading"]["source"] == "reading_context"} == {
        "problem_solution.mechanism", "evaluation_context.available_inputs",
        "evaluation_context.outcome_measurement",
    }


def test_context_identity_is_stable_across_reordering_and_source_scoped() -> None:
    artifact, raw = fixture()
    reading = parse_paper_reading(raw, artifact)
    extra = EvaluationContextItem("The retrieval includes prior sessions.", [
        EvidenceAnchor(source_url=URL, quote=FLOW)])
    first = replace(reading, evaluation_context=replace(reading.evaluation_context,
        available_inputs=[*reading.evaluation_context.available_inputs, extra]))
    second = replace(first, evaluation_context=replace(first.evaluation_context,
        available_inputs=list(reversed(first.evaluation_context.available_inputs))))
    def ids(value: PaperReading) -> dict[str, str]:
        return {c.text: c.metadata["paper_reading"]["claim_id"]
                for c in reading_to_claims(value, include_context_claims=True)}
    assert ids(first) == ids(second)
    context_id = ids(first)["Solution: " + FLOW]
    assert context_id != ids(replace(first, source_url="https://example.test/another"))[
        "Solution: " + FLOW]


def test_exact_duplicate_context_does_not_create_duplicate_fact() -> None:
    artifact, raw = fixture()
    reading = parse_paper_reading(raw, artifact)
    item = reading.evaluation_context.available_inputs[0]
    reading = replace(reading, evaluation_context=replace(reading.evaluation_context,
        available_inputs=[item, item]))
    claims = reading_to_claims(reading, include_context_claims=True)
    assert len([c for c in claims if c.text == "Experiment: " + DEPTH]) == 1


def test_context_id_collision_stops_instead_of_reassigning_an_existing_claim() -> None:
    from research_radar.exceptions import AnalysisError

    artifact, raw = fixture()
    reading = parse_paper_reading(raw, artifact)
    method = next(c for c in reading_to_claims(reading, include_context_claims=True)
                  if c.text == "Solution: " + FLOW)
    collision = replace(reading.claim_units[0],
                        claim_id=method.metadata["paper_reading"]["claim_id"])
    with pytest.raises(AnalysisError, match="identity conflicts"):
        reading_to_claims(replace(reading, claim_units=[collision]), include_context_claims=True)


@pytest.mark.parametrize("bad", ["foreign", "missing_quote", "wrong_value"])
def test_context_cannot_bypass_source_anchor_or_parameter_checks(bad: str) -> None:
    artifact, raw = fixture()
    reading = parse_paper_reading(raw, artifact)
    item = reading.evaluation_context.available_inputs[0]
    if bad == "foreign":
        item = replace(item, evidence=[replace(item.evidence[0], source_url="https://other.test")])
    elif bad == "missing_quote":
        item = replace(item, evidence=[replace(item.evidence[0], quote="Never in this paper.")])
    else:
        item = replace(item, text="White-box retrieval uses top-5 memories.")
    reading = replace(reading, evaluation_context=EvaluationContext(available_inputs=[item]))
    claims, _ = validate_paper_reading(reading, artifact, include_context_claims=True)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    context = next(c for c in claims if c.text.endswith(item.text))
    assert not context.is_publishable()


def test_fact_only_deep_reading_connects_context_to_the_existing_ledger() -> None:
    artifact, raw = indexed_fixture()
    result = run_artifact_deep_reading(artifact, Composer(json.loads(raw)), model="offline",
                                      facts_only=True)
    assert {c.text for c in result.claims if c.is_publishable()} == {
        "Experiment: " + BASE, "Solution: " + FLOW, "Experiment: " + DEPTH, "Experiment: " + MACRO,
    }


@pytest.mark.parametrize("context_status", ["supported", "needs_review"])
def test_reviewed_context_reaches_writer_but_rejected_context_cannot_authorize_prose(
    context_status: str,
) -> None:
    artifact, raw = fixture()
    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading, artifact, include_context_claims=True)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    decisions = [{"claim_index": i, "status": context_status if c.text.endswith(MACRO)
                  else "supported", "reason": "Offline factual control."}
                 for i, c in enumerate(claims, 1)]
    facts = review_publication_facts(claims, Composer({"decisions": decisions}), model="offline",
                                   readings=[reading], artifacts=[artifact]).claims
    ids = {c.text: c.metadata["paper_reading"]["claim_id"] for c in facts}
    translations = {"Experiment: " + BASE: "Experiment: 这是记忆评测。",
                    "Solution: " + FLOW: "Solution: 系统接收已有会话，检索记忆，再回答查询。",
                    "Experiment: " + DEPTH: "Experiment: 白盒检索取前3条记忆。",
                    "Experiment: " + MACRO: "Experiment: 分数按冲突类型做宏平均。"}
    paragraph = "系统先读取已有会话，检索记忆后回答查询。"
    experiment = "白盒检索取前3条，分数按冲突类型做宏平均。"
    support = [ids["Solution: " + FLOW]]
    experiment_support = [ids["Experiment: " + DEPTH], ids["Experiment: " + MACRO]]
    writer = Composer({"reader_explanation": {"solution_walkthrough": [{
        "text": paragraph, "supporting_claim_ids": support,
    }], "experiment_interpretation": [{
        "text": experiment, "supporting_claim_ids": experiment_support,
    }]}, "claims": [{"claim_id": c.metadata["paper_reading"]["claim_id"],
                     "text": translations[c.text]} for c in facts if c.is_publishable()]})
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    if context_status != "supported":
        assert localization_failed(localized)
        return
    assert not localization_failed(localized)
    assert all(identity not in paragraph for identity in support)
    final = model_review_publishable_claims(localized.claims, Composer({
        "decisions": [{"claim_index": i, "status": "supported", "reason": "Offline control."}
                      for i in range(1, len(claims) + 1)],
        "explanation_decisions": [{"paragraph_id": "p1.solution_walkthrough.1",
            "status": "supported", "reason": "Offline control.", "covered_claim_ids": support},
            {"paragraph_id": "p1.experiment_interpretation.1", "status": "supported",
             "reason": "Offline control.", "covered_claim_ids": experiment_support}],
    }), model="offline", readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    public, _ = public_explanation(final.readings[0].reader_explanation, final.claims,
                                   source_url=URL)
    assert paragraph in public["solution_walkthrough"]
    retained = final.readings[0].reader_explanation.solution_walkthrough[0]
    assert retained.supporting_claim_ids == support


@pytest.mark.parametrize("entry", ["paper", "daily"])
@pytest.mark.parametrize("mode", ["complete", "writer_missing_condition", "final_missing_coverage"])
def test_production_entries_review_context_before_writing_and_exact_final_prose(
    entry: str, mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_chinese_publication import OfflineProvider
    from test_pipeline_fake import FakeConnector

    from research_radar.config import parse_config
    from research_radar.exceptions import AnalysisError
    from research_radar.pipeline import daily, paper
    from research_radar.storage.files import read_jsonl

    artifact, raw = indexed_fixture()
    order: list[str] = []
    review_responses: list[str] = []
    reader = OfflineProvider([raw], order, "reader")

    class Reviewer(Composer):
        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            order.append("verifier")
            prompt = messages[1].content
            context = json.loads(prompt.split(
                "FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n", 1,
            )[1])
            refs = [json.loads(line.removeprefix("CLAIM REFERENCE: "))
                    for line in prompt.splitlines() if line.startswith("CLAIM REFERENCE: ")]
            assert len(refs) == 4
            feedback = json.dumps({
                "decisions": [{"claim_index": ref["claim_index"], "status": "supported",
                               "reason": "Offline explicit control."} for ref in refs],
                "explanation_decisions": [{"paragraph_id": p["paragraph_id"],
                    "status": "supported", "reason": "Offline explicit control.",
                    "covered_claim_ids": ([] if mode == "final_missing_coverage"
                                          else p["supporting_claim_ids"])}
                    for p in context["paragraphs"]],
            })
            review_responses.append(feedback)
            return ModelResponse(model=model, content=feedback)

    method = "系统先接收已有会话，再检索记忆，最后回答查询。"
    experiment = "白盒检索只取前3条记忆，结果按冲突类型做宏平均。"

    class Writer(Composer):
        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            order.append("writer")
            payload = json.loads(messages[1].content.split("FACT-REVIEWED CANDIDATES (JSON):\n")[1])
            by_text = {fact["text"]: fact["claim_id"] for fact in payload["candidate_facts"]}
            assert set(by_text) == {"Experiment: " + BASE, "Solution: " + FLOW,
                                    "Experiment: " + DEPTH, "Experiment: " + MACRO}
            chinese = {"Experiment: " + BASE: "Experiment: 这是记忆评测。",
                       "Solution: " + FLOW: "Solution: " + method,
                       "Experiment: " + DEPTH: "Experiment: 白盒检索取前3条记忆。",
                       "Experiment: " + MACRO: "Experiment: 分数按冲突类型做宏平均。"}
            return ModelResponse(model=model, content=json.dumps({"claims": [
                {"claim_id": identity, "text": chinese[text]} for text, identity in by_text.items()
            ], "reader_explanation": {
                "solution_walkthrough": [{"text": method,
                    "supporting_claim_ids": [by_text["Solution: " + FLOW]]}],
                "experiment_interpretation": [{
                    "text": ("白盒检索取前3条。"
                             if mode == "writer_missing_condition" else experiment),
                    "supporting_claim_ids": ([by_text["Experiment: " + DEPTH]]
                        if mode == "writer_missing_condition" else [
                            by_text["Experiment: " + DEPTH], by_text["Experiment: " + MACRO]])}],
            }}, ensure_ascii=False))

    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    module = paper if entry == "paper" else daily
    monkeypatch.setattr(module, "ingest_source", lambda source, _: replace(
        artifact, source=source, text=artifact.text + "\n" + "Memory benchmark context.\n" * 100))
    options = dict(verifier=Reviewer({}), verifier_model="offline", localizer=Writer({}),
                   localization_model="offline", language="zh")
    def execute() -> Path:
        if entry == "paper":
            return paper.run_paper(tmp_path, config, "memory", URL, reader,
                                   model="offline", **options)
        return daily.run_daily(tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
            deep_model="offline", deep_limit=1, figure_extractor=lambda *_args, **_kwargs: [],
            **options)
    if mode != "complete":
        with pytest.raises(AnalysisError) as failure:
            execute()
        assert order == (["reader", "verifier", "writer"] if mode == "writer_missing_condition"
                         else ["reader", "verifier", "writer", "verifier"])
        run = next((tmp_path / "runs").iterdir())
        for name in (
            "article_draft.json", "paper.md", "daily.md", "deep_reading.md", "wechat.html",
        ):
            assert not (run / name).exists()
        if mode == "final_missing_coverage":
            manifest = json.loads((run / "manifest.json").read_text())
            run_error = json.loads((run / "run_error.json").read_text())
            assert manifest["metadata"]["failure"] == run_error
            assert run_error["stage"] == "verifier"
            assert run_error["provider"] == "offline"
            assert run_error["model"] == "offline"
            assert run_error["error_type"] == "PublicationReviewError"
            assert run_error["message"] == str(failure.value)
            assert (run / "final_review.json").read_text() == review_responses[-1] + "\n"
            final_claims = read_jsonl(run / "final_review_claims.jsonl")
            assert len(final_claims) == 4
            assert all(c["metadata"]["model_review"]["reviewed_text"] == c["text"]
                       for c in final_claims)
            assert any(c["text"] == "Experiment: 分数按冲突类型做宏平均。"
                       for c in final_claims)
            final_reading, = read_jsonl(run / "final_review_readings.jsonl")
            explanation = final_reading["reader_explanation"]
            assert explanation["solution_walkthrough"][0]["text"] == method
            paragraph, = explanation["experiment_interpretation"]
            assert paragraph["text"] == experiment
            assert paragraph["supporting_claim_ids"] == ["c2", "c3"]
            assert paragraph["review"]["status"] == "needs_review"
            assert "coverage" in paragraph["review"]["reason"].lower()
        return
    run = execute()
    if entry == "paper":
        report = (run / "paper.md").read_text()
    else:
        report = (run / "wechat.html").read_text()
    assert order == ["reader", "verifier", "writer", "verifier"]
    assert method in report and experiment in report
    facts = read_jsonl(run / "fact_claims.jsonl")
    context_facts = [c for c in facts
                     if c["metadata"]["paper_reading"]["source"] == "reading_context"]
    assert len(context_facts) == 1
    final = read_jsonl(run / "localized_readings.jsonl")[0]
    assert final["reader_explanation"]["solution_walkthrough"][0]["review"]["status"] == "supported"
