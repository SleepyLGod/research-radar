"""Method extraction and composition keep each operation and connection source-bound."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_paper_reading import _claim_units_fixture
from test_publication_composition import Composer

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.paper_reading import (
    PaperReading,
    parse_paper_reading,
    validate_paper_reading,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import model_review_publishable_claims, review_publication_facts
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, Claim, ClaimStatus, SourceCandidate, SourceType

FIXTURES = Path(__file__).parent / "fixtures/method_flow"


def fixture(name: str) -> tuple[Artifact, dict, dict]:
    """Editorial extraction controls cite verbatim saved source excerpts, not live outputs."""
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    source = SourceCandidate(data["title"], data["source_url"], SourceType.PAPER, "offline")
    artifact = Artifact(source, "\n\n".join(data["source_excerpts"]))
    response = json.loads(_claim_units_fixture([data["source_excerpts"][0].splitlines()[0]]))
    body = response["deep_readings"]
    for key in ("area_context", "problem_solution", "related_work", "limitations",
                "critical_assessment"):
        body[key]["evidence"] = [{"quote": data["source_excerpts"][0]}]
    body["claim_units"] = data["claim_units"]
    body["reader_explanation"] = {}
    body["problem_solution"]["mechanism"] = "unknown"
    body["method_flow"] = data["method_flow"]
    return artifact, response, data


def fact_provider(data: dict, *, link_status: str = "supported") -> Composer:
    return Composer({"decisions": [{"claim_index": i, "status": "supported",
        "reason": "Offline editorial fact control, not live review."}
        for i in range(1, len(data["claim_units"]) + 1)], "method_flow_decisions": [{
            "source_url": data["source_url"], "status": "supported",
            "reason": "Offline check of actual input, operation and output roles."}],
        "method_operation_decisions": [{
            "source_url": data["source_url"], "operation_claim_id": op["operation_claim_id"],
            "status": "supported", "reason": "Offline identified operation control."}
            for op in data["operation_records"]],
        "method_link_decisions": [{
            "source_url": data["source_url"], "from_claim_id": link["from_claim_id"],
            "to_claim_id": link["to_claim_id"], "status": link_status,
            "reason": "Offline link check against quoted source."}
            for link in data["method_flow"]["links"]]})


def extract(name: str) -> tuple[Artifact, PaperReading, list[Claim], dict]:
    artifact, response, data = fixture(name)
    reading = parse_paper_reading(json.dumps(response), artifact)
    claims, _ = validate_paper_reading(reading, artifact)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    assert all(c.is_publishable() for c in claims)
    contextual, _ = validate_paper_reading(reading, artifact, include_context_claims=True)
    assert len(contextual) == len(claims)  # The broad summary is not a second method assertion.
    return artifact, reading, claims, data


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_saved_source_steps_reach_verified_connected_chinese_prose(name: str) -> None:
    artifact, reading, claims, data = extract(name)
    provider = fact_provider(data)
    facts = review_publication_facts(claims, provider, model="offline",
                                    readings=[reading], artifacts=[artifact])
    assert facts.readings[0].method_flow.links[0].review.status == "supported"
    writer = Composer(data["writer_control"])
    localized = localize_report_content(readings=facts.readings, claims=facts.claims, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    prompt = json.loads(writer.requests[0][1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert prompt["method_flow"]["links"] == data["method_flow"]["links"]
    final = model_review_publishable_claims(localized.claims, Composer({"decisions": [
        {"claim_index": i, "status": "supported", "reason": "Offline final fact control."}
        for i in range(1, len(claims) + 1)], "explanation_decisions": [
            {"paragraph_id": f"p1.solution_walkthrough.{i}", "status": "supported",
             "reason": "Offline control for the exact Chinese flow and its conditions.",
             "covered_claim_ids": paragraph["supporting_claim_ids"]}
            for i, paragraph in enumerate(data["writer_control"]["reader_explanation"][
                "solution_walkthrough"], 1)]}), model="offline", readings=localized.readings,
        artifacts=[artifact], analysis_claims=facts.claims)
    public, _ = public_explanation(final.readings[0].reader_explanation, final.claims,
                                   source_url=artifact.source.url)
    assert public["solution_walkthrough"] == "\n\n".join(p["text"] for p in data[
        "writer_control"]["reader_explanation"]["solution_walkthrough"])


@pytest.mark.parametrize("bad", ["unknown", "duplicate", "string_list", "self_approval"])
def test_method_index_does_not_invent_or_reassign_claims(bad: str) -> None:
    artifact, response, _ = fixture("memguide")
    flow = response["deep_readings"]["method_flow"]
    if bad == "unknown":
        flow["links"][0]["to_claim_id"] = "invented"
    elif bad == "duplicate":
        flow["step_claim_ids"] *= 2
    elif bad == "string_list":
        flow["step_claim_ids"] = "m2"
    else:
        flow["links"][0]["review"] = {"status": "supported"}
    with pytest.raises(AnalysisError, match="[Mm]ethod"):
        parse_paper_reading(json.dumps(response), artifact)


@pytest.mark.parametrize("bad", ["missing", "duplicate", "foreign", "reversed", "unsupported"])
def test_individually_valid_facts_cannot_authorize_an_unreviewed_connection(bad: str) -> None:
    artifact, reading, claims, data = extract("memguide")
    provider = fact_provider(data)
    decisions = provider.payloads[0]["method_link_decisions"]
    if bad == "missing":
        decisions.clear()
    elif bad == "duplicate":
        decisions.append(copy.deepcopy(decisions[0]))
    elif bad == "foreign":
        decisions[0]["source_url"] = "https://other.test/paper"
    elif bad == "reversed":
        decisions[0]["from_claim_id"], decisions[0]["to_claim_id"] = (
            decisions[0]["to_claim_id"], decisions[0]["from_claim_id"])
    else:
        decisions[0]["status"] = "unsupported"
    facts = review_publication_facts(claims, provider, model="offline",
                                    readings=[reading], artifacts=[artifact])
    writer = Composer(data["writer_control"])
    localized = localize_report_content(readings=facts.readings, claims=facts.claims, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert writer.requests == []
    assert all(c.is_publishable() for c in facts.claims)  # Do not downgrade true node facts.


def test_unknown_order_is_not_inferred_from_step_list_position() -> None:
    artifact, response, data = fixture("memguide")
    flow = response["deep_readings"]["method_flow"]
    flow["links"] = []
    flow["step_claim_ids"].reverse()
    flow["gaps"] = ["Execution order has not been established by the extracted claims."]
    response["deep_readings"]["claim_units"] = [c for c in data["claim_units"]
                                               if not c["claim_id"].startswith("r")]
    data["claim_units"] = response["deep_readings"]["claim_units"]
    data["writer_control"] = {
        "reader_explanation": {"solution_walkthrough": [{
            "text": "输入包括当前对话与长期记忆库。方法包含意图对齐检索与缺失槽位筛选；"
                    "响应模型接收对话、核心记忆事实和缺失槽位，省略辅助问题。",
            "supporting_claim_ids": ["m1", "m2", "m3", "m4"]}]},
        "claims": [c for c in data["writer_control"]["claims"]
                   if not c["claim_id"].startswith("r")]}
    reading = parse_paper_reading(json.dumps(response), artifact)
    claims, _ = validate_paper_reading(reading, artifact)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    facts = review_publication_facts(claims, fact_provider({**data, "method_flow": flow}),
                                    model="offline", readings=[reading], artifacts=[artifact])
    assert facts.readings[0].method_flow.links == []
    writer = Composer(data["writer_control"])
    localized = localize_report_content(readings=facts.readings, claims=facts.claims, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(localized)
    prompt = json.loads(writer.requests[0][1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert prompt["method_flow"]["links"] == []
    assert prompt["method_flow"]["gaps"] == flow["gaps"]


@pytest.mark.parametrize("bad", ["missing", "unsupported"])
def test_true_facts_and_connections_do_not_approve_wrong_input_output_roles(bad: str) -> None:
    artifact, reading, claims, data = extract("memguide")
    provider = fact_provider(data)
    if bad == "missing":
        provider.payloads[0]["method_flow_decisions"] = []
    else:
        provider.payloads[0]["method_flow_decisions"][0]["status"] = "unsupported"
    facts = review_publication_facts(claims, provider, model="offline",
                                    readings=[reading], artifacts=[artifact])
    writer = Composer(data["writer_control"])
    localized = localize_report_content(readings=facts.readings, claims=facts.claims, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert not writer.requests
    assert all(c.is_publishable() for c in facts.claims)


def test_partial_quote_cannot_approve_the_rest_of_a_method_operation() -> None:
    artifact, response, data = fixture("memguide")
    # This source phrase mentions missing slots, but does not establish re-ranking.
    response["deep_readings"]["claim_units"][2]["evidence"] = [{
        "quote": "Then, Missing-Slot Guided Filtering identifies unfilled task\nslots",
        "location": "PDF p.4, incomplete excerpt"}]
    reading = parse_paper_reading(json.dumps(response), artifact)
    claims, _ = validate_paper_reading(reading, artifact)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    provider = fact_provider(data)
    provider.payloads[0]["decisions"][2].update(status="needs_review",
        reason="The selected quote does not support the operation's re-ranking clause.")
    facts = review_publication_facts(claims, provider, model="offline",
                                    readings=[reading], artifacts=[artifact])
    writer = Composer(data["writer_control"])
    localized = localize_report_content(readings=facts.readings, claims=facts.claims, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert not writer.requests
    assert not facts.claims[2].is_publishable()
    assert len(facts.claims) == len(claims)  # No synthetic split or invented replacement step.


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
@pytest.mark.parametrize("entry", ["paper", "daily"])
@pytest.mark.parametrize("broken_link", [False, True])
def test_actual_pipeline_preserves_method_review_before_writing(
    name: str, entry: str, broken_link: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_radar.config import parse_config
    from research_radar.discovery.base import DiscoveryContext
    from research_radar.pipeline import daily, paper
    from research_radar.storage.files import read_jsonl

    artifact, response, data = fixture(name)
    artifact = replace(artifact, source=replace(artifact.source, score=1,
        summary="Agent memory retrieval and evaluation with source-grounded methods."))
    response["deep_readings"]["method_flow"] = {
        "operations": data["operation_records"],
        "links": data["method_flow"]["links"], "gaps": []}
    order: list[str] = []

    class Stage(Composer):
        def __init__(self, stage: str, payload: dict | list[dict]) -> None:
            super().__init__(payload)
            self.stage = stage

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            order.append(self.stage)
            return super().complete(messages, model=model)

    class Connector:
        name = "offline"

        def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
            return [artifact.source]

    facts = fact_provider(data,
        link_status="unsupported" if broken_link else "supported").payloads[0]
    final = {"decisions": facts["decisions"], "explanation_decisions": [{
        "paragraph_id": f"p1.solution_walkthrough.{i}", "status": "supported",
        "reason": "Offline complete method control.",
        "covered_claim_ids": p["supporting_claim_ids"]}
        for i, p in enumerate(data["writer_control"]["reader_explanation"][
            "solution_walkthrough"], 1)]}
    reader = Stage("reader", response)
    verifier = Stage("verifier", [facts, final])
    writer = Stage("writer", data["writer_control"])
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    module = paper if entry == "paper" else daily
    monkeypatch.setattr(module, "ingest_source", lambda *_args, **_kwargs: artifact)
    options = dict(verifier=verifier, verifier_model="offline", localizer=writer,
                   localization_model="offline", language="zh")

    def execute() -> Path:
        if entry == "paper":
            return paper.run_paper(tmp_path, config, "memory", artifact.source.url,
                                   reader, model="offline", **options)
        return daily.run_daily(tmp_path, config, "memory", [Connector()], deep_reader=reader,
            deep_model="offline", deep_limit=1, figure_extractor=lambda *_args, **_kwargs: [],
            **options)

    if broken_link:
        with pytest.raises(AnalysisError):
            execute()
        assert order == ["reader", "verifier"]
        assert not list(tmp_path.rglob("article_draft.json"))
        return
    run = execute()
    assert order == ["reader", "verifier", "writer", "verifier"]
    readings = read_jsonl(run / "localized_readings.jsonl")
    assert readings[0]["method_flow"]["links"][0]["review"]["status"] == "supported"
    report = (run / ("paper.md" if entry == "paper" else "wechat.html")).read_text()
    assert data["writer_control"]["reader_explanation"]["solution_walkthrough"][0]["text"] in report


@pytest.mark.parametrize("bad_link", [False, True])
def test_english_final_review_checks_the_same_flow_without_a_new_fact_review_call(
    bad_link: bool,
) -> None:
    artifact, response, data = fixture("memguide")
    body = response["deep_readings"]
    text = ("The method receives the dialogue context and memory bank. Intent-aligned retrieval "
            "extracts the current intent and retrieves aligned QA memories. Missing-slot filtering "
            "then identifies unfilled slots and re-ranks those memories. Response generation uses "
            "the filtered core facts, dialogue context and missing slots, "
            "omitting auxiliary questions.")
    support = [c["claim_id"] for c in data["claim_units"]]
    body["reader_explanation"] = {"solution_walkthrough": [{
        "text": text, "supporting_claim_ids": support}]}
    reading = parse_paper_reading(json.dumps(response), artifact)
    claims, _ = validate_paper_reading(reading, artifact)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    provider = fact_provider(data, link_status="unsupported" if bad_link else "supported")
    provider.payloads[0]["explanation_decisions"] = [{
        "paragraph_id": "p1.solution_walkthrough.1", "status": "supported",
        "reason": "Offline exact English flow control.", "covered_claim_ids": support}]
    if bad_link:
        with pytest.raises(AnalysisError, match="[Mm]ethod"):
            model_review_publishable_claims(claims, provider, model="offline",
                readings=[reading], artifacts=[artifact], analysis_claims=claims)
    else:
        result = model_review_publishable_claims(claims, provider, model="offline",
            readings=[reading], artifacts=[artifact], analysis_claims=claims)
        public, _ = public_explanation(result.readings[0].reader_explanation,
                                      result.claims, source_url=artifact.source.url)
        assert public["solution_walkthrough"] == text
    assert len(provider.requests) == 1


@pytest.mark.parametrize("changed", ["text", "quote", "link", "status"])
def test_method_approval_cannot_survive_changed_evidence_or_flow(changed: str) -> None:
    artifact, reading, claims, data = extract("memguide")
    facts = review_publication_facts(claims, fact_provider(data), model="offline",
                                    readings=[reading], artifacts=[artifact])
    altered = list(facts.claims)
    method = facts.readings[0]
    if changed == "text":
        altered[1] = replace(altered[1], text="Solution: Filtering occurs before retrieval.")
    elif changed == "quote":
        altered[1] = replace(altered[1],
            evidence=[replace(altered[1].evidence[0], quote="Changed.")])
    elif changed == "status":
        altered[1] = replace(altered[1], status=ClaimStatus.NEEDS_REVIEW)
    else:
        link = method.method_flow.links[0]
        method = replace(method, method_flow=replace(method.method_flow,
            links=[replace(link, from_claim_id=link.to_claim_id, to_claim_id=link.from_claim_id),
                   *method.method_flow.links[1:]]))
    writer = Composer(data["writer_control"])
    localized = localize_report_content(readings=[method], claims=altered, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(localized)
    assert not writer.requests
