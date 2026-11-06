"""Reviewed conditions must reach reviewed prose, not just its translated fact ledger."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_publication_composition import Composer, candidates

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.paper_reading import ReaderExplanation
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

FIXTURE = Path(__file__).parent / "fixtures/publication_coverage_omission.json"


def reviewed_fixture() -> tuple:
    """Use the saved failure's identities and text with explicit offline fact decisions."""
    data = json.loads(FIXTURE.read_text())
    url = data["source_url"]
    reading, _ = candidates()
    reading = replace(reading, source_url=url, reader_explanation=ReaderExplanation())
    claims = [Claim(f["text"], ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=url, quote=f["text"])], metadata={"paper_reading": {
            "claim_id": f["claim_id"], "section": "experiment",
            "source": "reading_context" if f["context_field"] else "claim_units",
            **({"context_field": f["context_field"]} if f["context_field"] else {}),
        }}) for f in data["facts"]]
    artifact = Artifact(SourceCandidate("MemConflict", url, SourceType.PAPER, "offline"),
                        "\n".join(c.text for c in claims))
    facts = review_publication_facts(claims, Composer({"decisions": [
        {"claim_index": i, "status": "supported", "reason": "Offline control, not live review."}
        for i in range(1, 5)]}), model="offline", readings=[reading], artifacts=[artifact]).claims
    return data, reading, facts, artifact


def writer_payload(data: dict, *, complete: bool = False) -> dict:
    """Keep the actual omitted paragraph or supply a clearly editorial test control."""
    paragraphs = [data["writer_paragraph"]]
    if complete:
        paragraphs.append({
            "text": "查询在冲突具备可评估条件后发出，系统只能使用截至该会话的历史。"
                    "总体指标先分别计算各类冲突的得分，再按冲突类型取宏平均，不按查询频率加权。",
            "supporting_claim_ids": ["context-8f706441703b6b46", "context-8495d05328c66338"],
        })
    return {"reader_explanation": {"experiment_interpretation": paragraphs},
            "claims": [{"claim_id": f["claim_id"], "text": f["translation"]}
                       for f in data["facts"]]}


def test_saved_writer_failure_cannot_satisfy_prose_coverage_by_translating_every_fact() -> None:
    data, reading, facts, _ = reviewed_fixture()
    writer = Composer(writer_payload(data))
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert localized.claims == facts
    assert localized.readings == [reading]
    assert "coverage" in localized.attempts[0].error_message.lower()
    assert len(writer.requests) == 1


def test_fact_review_does_not_require_prose_that_has_not_been_written() -> None:
    _, reading, facts, artifact = reviewed_fixture()
    result = review_publication_facts(facts, Composer({"decisions": [
        {"claim_index": i, "status": "supported", "reason": "Offline fact review only."}
        for i in range(1, 5)]}), model="offline", readings=[reading], artifacts=[artifact])
    assert result.reviewed_count == 4
    assert result.readings == [reading]


def test_required_conditions_cannot_be_hidden_in_an_unrelated_section() -> None:
    data, reading, facts, _ = reviewed_fixture()
    payload = writer_payload(data, complete=True)
    payload["reader_explanation"]["related_work_context"] = [
        payload["reader_explanation"]["experiment_interpretation"].pop()]
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(payload), model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)


def test_conditions_explained_with_method_setup_need_not_be_repeated() -> None:
    data, reading, facts, artifact = reviewed_fixture()
    payload = writer_payload(data, complete=True)
    payload["reader_explanation"]["solution_walkthrough"] = [
        payload["reader_explanation"]["experiment_interpretation"].pop()]
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(payload), model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    result = model_review_publishable_claims(localized.claims, Composer({
        "decisions": [{"claim_index": i, "status": "supported", "reason": "Offline control."}
                      for i in range(1, 5)],
        "explanation_decisions": [
            {"paragraph_id": "p1.solution_walkthrough.1", "status": "supported",
             "reason": "The setup paragraph explicitly states both conditions.",
             "covered_claim_ids": ["context-8f706441703b6b46", "context-8495d05328c66338"]},
            {"paragraph_id": "p1.experiment_interpretation.1", "status": "supported",
             "reason": "Offline control."}],
        }), model="offline", readings=localized.readings, artifacts=[artifact],
        analysis_claims=facts)
    public, _ = public_explanation(result.readings[0].reader_explanation, result.claims,
                                   source_url=reading.source_url)
    assert public["solution_walkthrough"] == payload["reader_explanation"][
        "solution_walkthrough"][0]["text"]


@pytest.mark.parametrize("coverage", [None, [], ["c12"], ["foreign"],
    ["context-8f706441703b6b46", "context-8f706441703b6b46"]])
def test_valid_support_ids_alone_cannot_prove_a_condition_was_explained(coverage: object) -> None:
    data, reading, facts, artifact = reviewed_fixture()
    writer = Composer(writer_payload(data, complete=True))
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    decisions = [{"paragraph_id": f"p1.experiment_interpretation.{i}", "status": "supported",
                  "reason": "Offline supported paragraph."} for i in (1, 2)]
    if coverage is not None:
        decisions[1]["covered_claim_ids"] = coverage
    final = Composer({"decisions": [{"claim_index": i, "status": "supported",
        "reason": "Offline supported fact."} for i in range(1, 5)],
        "explanation_decisions": decisions})
    with pytest.raises(AnalysisError, match="coverage"):
        model_review_publishable_claims(localized.claims, final, model="offline",
            readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    assert len(final.requests) == 1


def test_connected_conditions_publish_only_after_exact_final_coverage_decisions() -> None:
    data, reading, facts, artifact = reviewed_fixture()
    payload = writer_payload(data, complete=True)
    writer = Composer(payload)
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    final = Composer({"decisions": [{"claim_index": i, "status": "supported",
        "reason": "Offline supported fact."} for i in range(1, 5)], "explanation_decisions": [
            {"paragraph_id": "p1.experiment_interpretation.1", "status": "supported",
             "reason": "Offline supported paragraph."},
            {"paragraph_id": "p1.experiment_interpretation.2", "status": "supported",
             "reason": "Both conditions are explicitly explained in this exact paragraph.",
             "covered_claim_ids": ["context-8f706441703b6b46", "context-8495d05328c66338"]},
        ]})
    result = model_review_publishable_claims(localized.claims, final, model="offline",
        readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    public, audit = public_explanation(result.readings[0].reader_explanation, result.claims,
                                       source_url=reading.source_url)
    expected = "\n\n".join(p["text"] for p in payload["reader_explanation"][
        "experiment_interpretation"])
    assert public["experiment_interpretation"] == expected  # No appended fact list.
    assert audit["dropped_count"] == 0
    request = json.loads(writer.requests[0][1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert request["required_coverage"] == {"experiment_interpretation": [
        "context-8f706441703b6b46", "context-8495d05328c66338"]}


def test_rejected_method_cannot_be_repaired_by_authorizing_its_unreviewed_steps() -> None:
    data, reading, facts, _ = reviewed_fixture()
    rejected = replace(facts[0],
        text="Solution: Create users, inject conflicts, then evaluate top-K.",
        status=ClaimStatus.UNSUPPORTED, metadata={"paper_reading": {
            "claim_id": "method-gap", "source": "reading_context", "section": "solution",
            "context_field": "problem_solution.mechanism"},
            "anchor_resolution": {"status": "failed",
                                  "reason": "anchor missing key entities: top-K"}})
    writer = Composer(writer_payload(data, complete=True))
    localized = localize_report_content(readings=[reading], claims=[*facts, rejected], sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    assert localized.claims[-1] == rejected
    assert any(f.metadata.get("kind") == "publication_method_context_unavailable"
               for f in localized.findings)
    request = json.loads(writer.requests[0][1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert "method-gap" not in {f["claim_id"] for f in request["candidate_facts"]}
    assert request["unavailable_context"][0]["context_field"] == "problem_solution.mechanism"
