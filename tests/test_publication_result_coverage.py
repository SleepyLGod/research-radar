"""The same reviewed-result obligations constrain writing and both final-review gates."""

import json
from dataclasses import replace

import pytest
from test_publication_composition import Composer
from test_publication_coverage import reviewed_fixture, writer_payload
from test_review_targets import SchemaReviewer

from research_radar.analysis.experimental_results import ExperimentalResult
from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
from research_radar.analysis.review import model_review_publishable_claims
from research_radar.exceptions import AnalysisError
from research_radar.models import ClaimStatus


def result_material() -> tuple:
    """Add a source-bound result reference to an already fact-reviewed fixture."""
    data, reading, facts, artifact = reviewed_fixture()
    result = ExperimentalResult("retrieval-setting", "What is the reported retrieval setup?",
        [], "retrieval setup", [], [], [], ["c12"], facts[1].evidence, "text", "setup", None,
        "text_bound")
    return data, replace(reading, experimental_results=[result]), facts, artifact


def test_translated_result_without_body_explanation_fails_writing() -> None:
    data, reading, facts, _ = result_material()
    payload = writer_payload(data, complete=True)
    payload["reader_explanation"]["experiment_interpretation"].pop(0)
    writer = Composer(payload)
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert "c12" in localized.attempts[0].error_message
    assert localized.claims == facts and len(writer.requests) == 1


def test_cached_incomplete_candidate_is_blocked_before_the_final_provider_call() -> None:
    data, reading, facts, artifact = result_material()
    paragraph = writer_payload(data, complete=True)["reader_explanation"][
        "experiment_interpretation"][1]
    reading = replace(reading, reader_explanation=ReaderExplanation(
        experiment_interpretation=[ReaderExplanationParagraph(**paragraph)]))
    final = SchemaReviewer()
    with pytest.raises(AnalysisError, match="coverage"):
        model_review_publishable_claims(facts, final, model="offline", readings=[reading],
                                       artifacts=[artifact], analysis_claims=facts)
    assert final.requests == []


def test_writer_and_final_share_the_same_result_obligation_without_appending_a_ledger() -> None:
    data, reading, facts, artifact = result_material()
    payload = writer_payload(data, complete=True)
    writer = Composer(payload)
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    reviewer = SchemaReviewer()
    result = model_review_publishable_claims(localized.claims, reviewer, model="offline",
        readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    written_requirements = json.loads(writer.requests[0][-1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])["required_coverage"]
    final_context = json.loads(reviewer.requests[0][0][-1].content.split(
        "FULL SOURCE CONTEXT (JSON):\n")[1].split("\nREVIEW TARGETS (JSON):\n")[0])
    assert final_context["required_coverage"][reading.source_url] == written_requirements
    assert "c12" in written_requirements["experiment_interpretation"]
    public, audit = public_explanation(result.readings[0].reader_explanation, result.claims,
                                       source_url=reading.source_url)
    assert public["experiment_interpretation"] == "\n\n".join(
        p["text"] for p in payload["reader_explanation"]["experiment_interpretation"])
    assert audit["fallback_section_count"] == 0 and audit["dropped_count"] == 0


def test_a_rejected_result_paragraph_cannot_be_replaced_by_its_translated_fact() -> None:
    data, reading, facts, artifact = result_material()
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=Composer(writer_payload(data, complete=True)), model="offline", language="zh",
        verified_facts=True)
    final = Composer({"decisions": [{"claim_index": i, "status": "supported",
        "reason": "Offline fact control."} for i in range(1, 5)],
        "explanation_decisions": [
            {"paragraph_id": "p1.experiment_interpretation.1", "status": "unsupported",
             "reason": "Offline negative paragraph control."},
            {"paragraph_id": "p1.experiment_interpretation.2", "status": "supported",
             "reason": "Offline setup control.", "covered_claim_ids": [
                 "context-8f706441703b6b46", "context-8495d05328c66338"]},
        ]})
    with pytest.raises(AnalysisError, match="c12"):
        model_review_publishable_claims(localized.claims, final, model="offline",
            readings=localized.readings, artifacts=[artifact], analysis_claims=facts)
    assert len(final.requests) == 1


def test_unapproved_results_do_not_acquire_prose_obligations_or_approval() -> None:
    data, reading, facts, _ = result_material()
    rejected = replace(facts[1], status=ClaimStatus.UNSUPPORTED)
    payload = writer_payload(data, complete=True)
    payload["reader_explanation"]["experiment_interpretation"].pop(0)
    payload["claims"] = [p for p in payload["claims"] if p["claim_id"] != "c12"]
    localized = localize_report_content(readings=[reading], claims=[facts[0], rejected, *facts[2:]],
        sources=[], provider=Composer(payload), model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    assert localized.claims[1] == rejected


@pytest.mark.parametrize("defect", ["foreign", "duplicate", "unknown"])
def test_result_obligations_require_unique_same_source_facts_before_writing(defect: str) -> None:
    data, reading, facts, _ = result_material()
    if defect == "foreign":
        reading = replace(reading, experimental_results=[replace(reading.experimental_results[0],
            supporting_claim_ids=["foreign-result"])])
        facts = [*facts, replace(facts[1], evidence=[replace(facts[1].evidence[0],
            source_url="https://other.test/paper")], metadata={"paper_reading": {
                "claim_id": "foreign-result", "section": "experiment"}})]
    elif defect == "duplicate":
        facts = [*facts, facts[1]]
    else:
        reading = replace(reading, experimental_results=[replace(reading.experimental_results[0],
            supporting_claim_ids=["unknown-result"])])
    writer = Composer(writer_payload(data, complete=True))
    localized = localize_report_content(readings=[reading], claims=facts, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert writer.requests == []
