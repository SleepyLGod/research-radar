"""Writing roles guide paragraphs; exact final review decides semantic support."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_publication_composition import Composer, candidates
from test_review_targets import SchemaReviewer

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.method_flow import MethodFlow, MethodOperation, MethodRoleValue
from research_radar.analysis.paper_reading import EvaluationContext, ReaderExplanation
from research_radar.analysis.reading_review import paragraph_is_public
from research_radar.analysis.review import model_review_publishable_claims, review_publication_facts
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

FIXTURE = Path(__file__).parent / "fixtures/publication_scope_boundary.json"


def test_same_evaluation_process_can_join_method_and_measurement_facts() -> None:
    """The real MemConflict paragraph joins three facts about one verified-judgment process."""
    reading, _ = candidates()
    quote = (
        "All answer and memory-item judgments are produced through LLM-assisted matching "
        "followed by human verification. Human annotators review the LLM judgments, "
        "especially ambiguous matches, paraphrases, and attribution cases, and the final "
        "metrics are computed from the verified judgments."
    )
    texts = {
        "c12": "Solution: Answer and memory-item matches are judged with LLM assistance, "
               "reviewed by human annotators, and scored from the verified judgments.",
        "c19": "Solution: The final metrics are computed after the LLM-assisted judgments "
               "have been human-verified.",
        "c39": "Experiment: Answer and memory-item judgments use LLM-assisted matching "
               "followed by human verification.",
    }
    claims = [Claim(text, ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(reading.source_url, quote)],
        metadata={"paper_reading": {"claim_id": cid,
                  "section": "experiment" if cid == "c39" else "solution"}})
        for cid, text in texts.items()]
    reading = replace(reading, method_flow=MethodFlow(operations=[MethodOperation(
        "Compute metrics from verified judgments", "c19", [], [], [])]),
        evaluation_context=EvaluationContext(claim_references={
            "data_construction": [], "available_inputs": [], "outcome_measurement": ["c39"]}))
    artifact = Artifact(SourceCandidate("MemConflict", reading.source_url,
        SourceType.PAPER, "offline"), quote)
    facts = review_publication_facts(claims, SchemaReviewer(), model="offline",
        readings=[reading], artifacts=[artifact])
    paragraph = {
        "text": "答案与记忆项的匹配不是直接当作真值：判断由 LLM 辅助产生，再由人类标注者复核，"
                "最终指标基于已验证的判断计算。",
        "supporting_claim_ids": ["c12", "c39", "c19"],
    }
    answer = {"reader_explanation": {"solution_walkthrough": [paragraph]},
              "claims": [{"claim_id": cid, "text": text} for cid, text in texts.items()]}
    localized = localize_report_content(readings=facts.readings, claims=facts.claims,
        sources=[], provider=Composer(answer), model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    candidate = localized.readings[0].reader_explanation.solution_walkthrough[0]
    assert candidate.text == paragraph["text"]
    assert not paragraph_is_public(candidate, localized.claims, source_url=reading.source_url)
    final = model_review_publishable_claims(localized.claims, SchemaReviewer(), model="offline",
        readings=localized.readings, artifacts=[artifact], analysis_claims=facts.claims)
    public, _ = public_explanation(final.readings[0].reader_explanation, final.claims,
                                   source_url=reading.source_url)
    assert public["solution_walkthrough"] == paragraph["text"]


def scoped_material() -> tuple:
    """Review literal source facts and operation roles through the production entry."""
    data = json.loads(FIXTURE.read_text())
    url = data["source_url"]
    reading, _ = candidates()
    roles = {
        "c8": ("Extract current intent", ["Dialogue context"], ["Current-intent description"]),
        "c9": ("Retrieve candidate memories", ["Current intent", "Memory bank"], ["Candidates"]),
        "c12": ("Identify missing slots", ["Dialogue context", "Task goal"], ["Missing slots"]),
        "c16": ("Generate response",
                ["Dialogue context", "Selected memory answers", "Missing slots"], ["Response"]),
    }
    operations = [MethodOperation(scope, cid,
        [MethodRoleValue(name, [cid]) for name in inputs],
        [MethodRoleValue(name, [cid]) for name in outputs], [])
        for cid, (scope, inputs, outputs) in roles.items()]
    reading = replace(reading, source_url=url, reader_explanation=ReaderExplanation(),
        method_flow=MethodFlow(operations=operations), evaluation_context=EvaluationContext(
            claim_references={"data_construction": [], "available_inputs": ["c16", "c30"],
                              "outcome_measurement": ["c30"]}))
    claims = [Claim(row["text"], ClaimStatus.SUPPORTED, evidence=[EvidenceAnchor(
        url, row["quote"], location=row["location"])], metadata={"paper_reading": {
            "claim_id": row["id"], "section": row["section"]}}) for row in data["facts"]]
    artifact = Artifact(SourceCandidate("MemGuide", url, SourceType.PAPER, "offline"),
                        "\n\n".join(row["quote"] for row in data["facts"]))
    facts = review_publication_facts(claims, SchemaReviewer(), model="offline",
                                    readings=[reading], artifacts=[artifact])
    return data, facts.readings[0], facts.claims, artifact


def writer_answer(data: dict, *, mixed: bool = False) -> dict:
    """Use a preserved failed clause or an explicitly editorial coherent control."""
    return {"reader_explanation": {
        "solution_walkthrough": [copy.deepcopy(data["editorial_method"])],
        "experiment_interpretation": [copy.deepcopy(
            data["original"] if mixed else data["editorial_measurement"])],
    }, "claims": [{"claim_id": row["id"], "text": row["translation"]}
                  for row in data["facts"]]}


@pytest.mark.parametrize("section", ["solution_walkthrough", "experiment_interpretation"])
def test_mixed_role_candidate_is_not_semantically_approved_by_composition(section: str) -> None:
    data, reading, facts, _ = scoped_material()
    payload = writer_answer(data, mixed=True)
    if section == "solution_walkthrough":
        payload["reader_explanation"] = {
            section: [data["editorial_method"], data["original"]]}
    result = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(payload), model="offline", language="zh", verified_facts=True)
    assert not localization_failed(result)
    paragraph = getattr(result.readings[0].reader_explanation, section)[-1]
    assert paragraph.text == data["original"]["text"]
    assert not paragraph_is_public(paragraph, result.claims, source_url=reading.source_url)


def test_writer_receives_operation_local_inputs_and_separate_measurement_scope() -> None:
    data, reading, facts, _ = scoped_material()
    writer = Composer(writer_answer(data))
    result = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(result)
    payload = json.loads(writer.requests[0][-1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert payload["paragraph_scopes"] == {
        "method_claim_ids": ["c8", "c9", "c12", "c16"], "measurement_claim_ids": ["c30"]}
    generation = next(op for op in payload["method_flow"]["operations"]
                      if op["operation_claim_id"] == "c16")
    assert [item["name"] for item in generation["inputs"]] == [
        "Dialogue context", "Selected memory answers", "Missing slots"]
    assert not any(p.review for p in result.readings[0].reader_explanation.solution_walkthrough)


def test_separate_connected_prose_reaches_public_body_only_after_exact_review() -> None:
    data, reading, facts, artifact = scoped_material()
    result = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(writer_answer(data)), model="offline", language="zh", verified_facts=True)
    final = model_review_publishable_claims(result.claims, SchemaReviewer(), model="offline",
        readings=result.readings, artifacts=[artifact], analysis_claims=facts)
    public, audit = public_explanation(final.readings[0].reader_explanation, final.claims,
                                       source_url=reading.source_url)
    assert public["solution_walkthrough"] == data["editorial_method"]["text"]
    assert public["experiment_interpretation"] == data["editorial_measurement"]["text"]
    assert audit["fallback_section_count"] == 0 and audit["dropped_count"] == 0


@pytest.mark.parametrize("omission", ["missing", "unsupported", "needs_review", "no_coverage"])
def test_separate_condition_still_requires_its_own_final_decision(omission: str) -> None:
    data, reading, facts, artifact = scoped_material()
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(writer_answer(data)), model="offline", language="zh", verified_facts=True)
    decisions = [{"paragraph_id": "p1.solution_walkthrough.1", "status": "supported",
        "reason": "Offline control, not real approval.",
        "covered_claim_ids": ["c8", "c9", "c12", "c16"]}]
    if omission != "missing":
        decisions.append({"paragraph_id": "p1.experiment_interpretation.1",
            "status": "supported" if omission == "no_coverage" else omission,
            "reason": "Offline negative control.",
            "covered_claim_ids": [] if omission == "no_coverage" else ["c30"]})
    verifier = Composer({"decisions": [{"claim_index": i, "status": "supported",
        "reason": "Offline control."} for i in range(1, 6)], "explanation_decisions": decisions})
    with pytest.raises(AnalysisError, match="coverage"):
        model_review_publishable_claims(localized.claims, verifier, model="offline",
            readings=localized.readings, artifacts=[artifact], analysis_claims=facts)


def test_changed_paragraph_does_not_inherit_its_old_final_approval() -> None:
    data, reading, facts, artifact = scoped_material()
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(writer_answer(data)), model="offline", language="zh", verified_facts=True)
    final = model_review_publishable_claims(localized.claims, SchemaReviewer(), model="offline",
        readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    explanation = final.readings[0].reader_explanation
    changed = replace(explanation, experiment_interpretation=[replace(
        explanation.experiment_interpretation[0], text="评判器只看预测答案。")])
    public, _ = public_explanation(changed, final.claims, source_url=reading.source_url)
    assert "评判器只看预测答案" not in public["experiment_interpretation"]


def test_independent_condition_survives_rejection_of_redundant_method_prose() -> None:
    data, reading, facts, artifact = scoped_material()
    payload = writer_answer(data)
    payload["reader_explanation"]["solution_walkthrough"].append({
        "text": "回答生成器直接使用全部候选记忆。", "supporting_claim_ids": ["c16"]})
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(payload), model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)  # Scope separation is not semantic approval.
    final = model_review_publishable_claims(localized.claims, Composer({
        "decisions": [{"claim_index": i, "status": "supported", "reason": "Offline control."}
                      for i in range(1, 6)],
        "explanation_decisions": [
            {"paragraph_id": "p1.solution_walkthrough.1", "status": "supported",
             "reason": "Offline editorial control.",
             "covered_claim_ids": ["c8", "c9", "c12", "c16"]},
            {"paragraph_id": "p1.solution_walkthrough.2", "status": "unsupported",
             "reason": "Selected memory answers are not all retrieved candidates."},
            {"paragraph_id": "p1.experiment_interpretation.1", "status": "supported",
             "reason": "Offline editorial control.", "covered_claim_ids": ["c30"]},
        ]}), model="offline", readings=localized.readings, artifacts=[artifact],
        analysis_claims=facts)
    public, audit = public_explanation(final.readings[0].reader_explanation, final.claims,
                                       source_url=reading.source_url)
    assert public["solution_walkthrough"] == data["editorial_method"]["text"]
    assert public["experiment_interpretation"] == data["editorial_measurement"]["text"]
    assert audit["dropped_count"] == 1


def test_original_rejected_mixed_paragraph_is_not_split_or_salvaged_by_final_review() -> None:
    data, reading, facts, artifact = scoped_material()
    from research_radar.analysis.paper_reading import ReaderExplanationParagraph

    original = replace(reading, reader_explanation=ReaderExplanation(
        solution_walkthrough=[ReaderExplanationParagraph(**data["editorial_method"])],
        experiment_interpretation=[ReaderExplanationParagraph(**data["original"])]))
    original_text = original.reader_explanation.experiment_interpretation[0].text
    with pytest.raises(AnalysisError, match='"c30"'):
        model_review_publishable_claims(facts, Composer({
            "decisions": [{"claim_index": i, "status": "supported", "reason": "Offline control."}
                          for i in range(1, 6)],
            "explanation_decisions": [
                {"paragraph_id": "p1.solution_walkthrough.1", "status": "supported",
                 "reason": "Offline editorial control.",
                 "covered_claim_ids": ["c8", "c9", "c12", "c16"]},
                {"paragraph_id": "p1.experiment_interpretation.1", "status": "unsupported",
                 "reason": data["rejection_reason"],
                 "covered_claim_ids": ["c8", "c9", "c12", "c30"]},
            ]}), model="offline", readings=[original], artifacts=[artifact], analysis_claims=facts)
    assert original.reader_explanation.experiment_interpretation[0].text == original_text


def test_explicit_method_role_is_not_reclassified_when_it_also_indexes_measurement() -> None:
    data, reading, facts, _ = scoped_material()
    references = copy.deepcopy(reading.evaluation_context.claim_references)
    references["outcome_measurement"].append("c16")
    reading = replace(reading, evaluation_context=EvaluationContext(claim_references=references))
    writer = Composer(writer_answer(data))
    result = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(result)
    payload = json.loads(writer.requests[0][-1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert payload["paragraph_scopes"]["measurement_claim_ids"] == ["c30"]
    assert result.readings[0].reader_explanation.solution_walkthrough[0].supporting_claim_ids == [
        "c8", "c9", "c12", "c16"]
