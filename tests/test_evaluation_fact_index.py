"""Evaluation roles index one factual ledger instead of paraphrased context claims."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from method_contract_controls import control
from test_method_contract_pipeline import Reading, Reviewing, Writing
from test_paper_reading import SequenceProvider, _artifact, _claim_units_fixture

from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.paper_reading import (
    model_paper_reading_with_attempts,
    parse_paper_reading,
    reading_to_claims,
    reading_to_dict,
)
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.analysis.reading_review import context_coverage_requirements
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact
from research_radar.pipeline import daily, paper

DIMENSIONS = ("data_construction", "available_inputs", "outcome_measurement")


def indexed_fixture() -> dict:
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."] * 3))
    body = payload["deep_readings"]
    for unit, identity in zip(body["claim_units"], ("c23", "c24", "c25"), strict=True):
        unit["claim_id"] = identity
        unit["method"] = None
    body["problem_solution"]["mechanism"] = "Memory benchmark fixture."
    body["method_flow"] = {"operations": [], "links": [], "gaps": []}
    body["evaluation_context"] = {"data_construction": [], "available_inputs": ["c23"],
                                  "outcome_measurement": ["c23", "c24", "c25"]}
    return payload


def test_reader_schema_indexes_claim_ids_not_a_second_text_and_evidence_list() -> None:
    shape = paper_reading_response_schema()["properties"]["deep_readings"]["items"][
        "properties"]["evaluation_context"]
    assert set(shape["properties"]) == set(DIMENSIONS)
    assert all(value["type"] == "array" and value["items"] == {"type": "string"}
               for value in shape["properties"].values())


def test_metrics_covered_by_atomic_facts_do_not_create_a_second_summary_target() -> None:
    payload = indexed_fixture()
    reading = parse_paper_reading(json.dumps(payload), _artifact())
    claims = reading_to_claims(reading, include_context_claims=True)
    assert [c.metadata["paper_reading"]["claim_id"] for c in claims] == ["c23", "c24", "c25"]
    required = context_coverage_requirements(claims, source_url=reading.source_url,
                                            evaluation_context=reading.evaluation_context)
    assert required == {"experiment_interpretation": ["c23", "c24", "c25"]}
    assert reading_to_dict(reading)["evaluation_context"] == payload["deep_readings"][
        "evaluation_context"]


@pytest.mark.parametrize("bad", [["missing"], ["c23", "c23"], ["c23", 1], [""], "c23"])
def test_invalid_role_references_are_not_guessed_or_coerced(bad: object) -> None:
    payload = indexed_fixture()
    payload["deep_readings"]["evaluation_context"]["outcome_measurement"] = bad
    with pytest.raises(AnalysisError, match="[Ee]valuation"):
        parse_paper_reading(json.dumps(payload), _artifact())


@pytest.mark.parametrize("bad", ["interpretation", "missing_evidence", "implicit_id", "dropped"])
def test_role_reference_requires_an_explicit_existing_anchored_fact(bad: str) -> None:
    payload = indexed_fixture()
    unit = payload["deep_readings"]["claim_units"][0]
    if bad == "interpretation":
        unit["claim_kind"] = "interpretation"
    elif bad == "missing_evidence":
        unit["evidence"] = []
    elif bad == "implicit_id":
        unit.pop("claim_id")
        payload["deep_readings"]["evaluation_context"]["available_inputs"] = ["legacy-c1"]
    else:
        unit["text"] = ""
    with pytest.raises(AnalysisError, match="[Ee]valuation"):
        parse_paper_reading(json.dumps(payload), _artifact())


def test_mixed_legacy_assertions_and_new_role_ids_are_not_implicitly_merged() -> None:
    payload = indexed_fixture()
    payload["deep_readings"]["evaluation_context"]["data_construction"] = [
        {"text": "Memory benchmark fixture.", "evidence": [{"quote": "Memory benchmark fixture."}]}]
    with pytest.raises(AnalysisError, match="[Ee]valuation"):
        parse_paper_reading(json.dumps(payload), _artifact())


def test_unknown_role_reference_stops_reader_once_without_a_json_repair_request() -> None:
    payload = indexed_fixture()
    payload["deep_readings"]["evaluation_context"]["outcome_measurement"] = ["unknown"]
    provider = SequenceProvider([json.dumps(payload)])
    with pytest.raises(AnalysisError, match="[Ee]valuation"):
        model_paper_reading_with_attempts(_artifact(), provider, model="fake-reader")
    assert len(provider.messages) == 1


def test_fresh_output_cannot_use_legacy_context_assertions_instead_of_ids() -> None:
    payload = indexed_fixture()
    payload["deep_readings"]["evaluation_context"] = {key: [
        {"text": "Memory benchmark fixture.", "evidence": [{"quote": "Memory benchmark fixture."}]}]
        for key in DIMENSIONS}
    provider = SequenceProvider([json.dumps(payload)])
    with pytest.raises(AnalysisError, match="[Ee]valuation"):
        model_paper_reading_with_attempts(_artifact(), provider, model="fake-reader")
    assert len(provider.messages) == 1


def test_role_index_does_not_create_or_transfer_fact_approval() -> None:
    reading = parse_paper_reading(json.dumps(indexed_fixture()), _artifact())
    claims = reading_to_claims(reading)
    assert all("fact_review" not in c.metadata for c in claims)
    rejected = [replace(claims[0], status="needs_review"), *claims[1:]]
    with pytest.raises(AnalysisError, match="[Ee]valuation"):
        context_coverage_requirements(rejected, source_url=reading.source_url,
                                      evaluation_context=reading.evaluation_context)


def test_old_context_stays_old_without_assigning_equivalent_atomic_ids() -> None:
    payload = indexed_fixture()
    context = {key: [] for key in DIMENSIONS}
    context["outcome_measurement"] = [{"text": "Memory benchmark fixture.",
        "evidence": [{"quote": "Memory benchmark fixture."}]}]
    payload["deep_readings"]["evaluation_context"] = copy.deepcopy(context)
    reading = parse_paper_reading(json.dumps(payload), _artifact())
    saved = reading_to_dict(reading)["evaluation_context"]
    assert saved["outcome_measurement"][0]["text"] == context["outcome_measurement"][0]["text"]
    assert saved["outcome_measurement"][0]["evidence"][0]["quote"] == "Memory benchmark fixture."
    assert reading.evaluation_context.claim_references is None


def paper_control(name: str) -> tuple[Artifact, dict, dict, dict]:
    """Assign explicit editorial evaluation roles to the existing two-paper controls."""
    artifact, response, chinese = control(name)
    roles = ({"data_construction": ["m1"], "available_inputs": ["m5", "e1"],
              "outcome_measurement": ["m6", "e2"]} if name == "memconflict" else
             {"data_construction": ["e1"], "available_inputs": ["m1", "m4"],
              "outcome_measurement": ["e2"]})
    response["deep_readings"]["evaluation_context"] = roles
    return artifact, response, chinese, roles


@pytest.mark.parametrize("entry", ["paper", "daily"])
@pytest.mark.parametrize("rejected", [False, True])
def test_english_indexed_conditions_reach_verifier_and_require_approval(
    entry: str, rejected: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, response, _, roles = paper_control("memconflict")
    artifact = replace(artifact, source=replace(artifact.source, score=1,
        summary="Agent memory retrieval and evaluation with source-grounded methods."))
    body = response["deep_readings"]
    body["reader_explanation"] = {"solution_walkthrough": [
        {"text": unit["text"], "supporting_claim_ids": [unit["claim_id"]]}
        for unit in body["claim_units"]]}
    order: list[str] = []

    class Reviewer(Reviewing):
        def complete_with_schema(self, *args, **kwargs):
            result = super().complete_with_schema(*args, **kwargs)
            if not rejected:
                return result
            decisions = json.loads(result.content)
            key, = [key for key, target in self.requests[-1][2].items()
                    if target["kind"] == "fact" and target["claim_id"] == "e2"]
            decisions["decisions"][key]["status"] = "needs_review"
            return replace(result, content=json.dumps(decisions))

    class Connector:
        name = "offline"

        def discover(self, _context):
            return [artifact.source]

    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    module = paper if entry == "paper" else daily
    monkeypatch.setattr(module, "ingest_source", lambda *_: artifact)
    reader, verifier = Reading(response, order), Reviewer(order)
    options = dict(verifier=verifier, verifier_model="offline", language="en")

    def execute() -> Path:
        if entry == "paper":
            return paper.run_paper(tmp_path, config, "memory", artifact.source.url,
                                   reader, model="offline", **options)
        return daily.run_daily(tmp_path, config, "memory", [Connector()], deep_reader=reader,
            deep_model="offline", deep_limit=1, figure_extractor=lambda *_: [], **options)

    if rejected:
        with pytest.raises(AnalysisError, match="omitted reviewed context coverage"):
            execute()
        assert not list(tmp_path.rglob("paper.md"))
        assert not list(tmp_path.rglob("article_draft.json"))
    else:
        run = execute()
        report = (run / ("paper.md" if entry == "paper" else "wechat.html")).read_text()
        assert body["reader_explanation"]["solution_walkthrough"][0]["text"] in report
    assert order == ["reader", "review"]
    manifest = verifier.requests[0][2]
    required = {identity for target in manifest.values()
                for identity in target.get("required_covered_claim_ids", [])}
    assert {identity for ids in roles.values() for identity in ids} <= required


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_indexed_reader_to_final_chinese_uses_one_fact_ledger(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, response, chinese, roles = paper_control(name)
    order = []
    verifier = Reviewing(order)
    writer = Writing(chinese, order)
    monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
    run = paper.run_paper(tmp_path, parse_config({"topics": [{"id": "memory",
        "queries": ["agent memory"]}]}), "memory", artifact.source.url,
        Reading(response, order), model="offline", verifier=verifier, verifier_model="offline",
        localizer=writer, localization_model="offline", language="zh")
    assert order == ["reader", "review", "writer", "review"]
    ids = {t["claim_id"] for t in verifier.requests[0][2].values() if t["kind"] == "fact"}
    assert ids == {u["claim_id"] for u in response["deep_readings"]["claim_units"]}
    assert not any(i.startswith("context-") for i in ids)
    body = (run / "paper.md").read_text().split("## 证据链")[0]
    assert all(s in body for s in (("top-3", "宏平均") if name == "memconflict"
                                  else ("Mistral-7B", "0.73", "0.80", "2.52", "1.21")))
    assert "## 方法与机制" in body and "## 局限与未来工作" in body
    saved = json.loads((run / "readings.jsonl").read_text().splitlines()[0])
    assert saved["evaluation_context"] == roles


@pytest.mark.parametrize("bad", ["missing", "foreign_source", "ambiguous"])
def test_coverage_never_borrows_another_sources_or_duplicate_fact(bad: str) -> None:
    reading = parse_paper_reading(json.dumps(indexed_fixture()), _artifact())
    claims = reading_to_claims(reading)
    if bad == "missing":
        claims = claims[1:]
    elif bad == "foreign_source":
        claims[0] = replace(claims[0], evidence=[
            replace(claims[0].evidence[0], source_url="https://other.test/paper")])
    else:
        claims.append(claims[0])
    with pytest.raises(AnalysisError, match="Evaluation context"):
        context_coverage_requirements(claims, source_url=reading.source_url,
                                      evaluation_context=reading.evaluation_context)


def test_no_eligible_facts_cannot_skip_required_context_or_call_writer() -> None:
    reading = parse_paper_reading(json.dumps(indexed_fixture()), _artifact())
    claims = [replace(c, status="needs_review") for c in reading_to_claims(reading)]
    writer = SequenceProvider([])
    result = localize_report_content(readings=[reading], claims=claims, sources=[],
        provider=writer, model="offline", language="zh", verified_facts=True)
    assert localization_failed(result)
    assert "Evaluation context" in result.attempts[0].error_message
    assert not writer.messages


@pytest.mark.parametrize("stage", ["facts", "final"])
def test_required_indexed_fact_cannot_be_overruled_by_approved_chinese_paragraphs(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, response, chinese, _ = paper_control("memconflict")
    order: list[str] = []

    class Reviewer(Reviewing):
        def complete_with_schema(self, *args, **kwargs):
            result = super().complete_with_schema(*args, **kwargs)
            if len(self.requests) == (1 if stage == "facts" else 2):
                decisions = json.loads(result.content)
                key, = [key for key, target in self.requests[-1][2].items()
                        if target["kind"] == "fact" and target["claim_id"] == "e2"]
                decisions["decisions"][key]["status"] = "needs_review"
                return replace(result, content=json.dumps(decisions))
            return result

    monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
    with pytest.raises(AnalysisError):
        paper.run_paper(tmp_path, parse_config({"topics": [{"id": "memory",
            "queries": ["agent memory"]}]}), "memory", artifact.source.url,
            Reading(response, order), model="offline", verifier=Reviewer(order),
            verifier_model="offline", localizer=Writing(chinese, order),
            localization_model="offline", language="zh")
    assert order == (["reader", "review"] if stage == "facts"
                     else ["reader", "review", "writer", "review"])
    assert not list(tmp_path.rglob("paper.md"))
