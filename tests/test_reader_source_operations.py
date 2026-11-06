"""Source selection and operation roles stay separate from semantic approval."""

import copy
import importlib
import importlib.util
import json
from dataclasses import replace

import pytest
from test_method_flow import extract, fact_provider, fixture

from research_radar.analysis.method_flow import (
    apply_method_decisions,
    method_claim_ids,
    method_flow_payload,
    parse_method_flow,
    reviewed_method_flow,
)
from research_radar.analysis.paper_reading import parse_paper_reading
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import ReaderContextBudget
from research_radar.analysis.source_references import SourceReferenceError
from research_radar.exceptions import AnalysisError


def source_module():
    """Fail explicitly until the shared locator exists, without an import-time error."""
    name = "research_radar.analysis.source_references"
    assert importlib.util.find_spec(name) is not None, "Reader needs source-addressable evidence"
    return importlib.import_module(name)


def operations(name: str) -> dict:
    """Editorial role controls; no roles are inferred from legacy list position."""
    data = fixture(name)[2]
    return {"operations": copy.deepcopy(data["operation_records"]),
        "links": copy.deepcopy(data["method_flow"]["links"]), "gaps": []}


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_selected_source_ranges_materialize_exact_original_evidence(name: str) -> None:
    from reader_fixtures import source_response

    from research_radar.analysis.paper_reading import paper_reading_prompt

    artifact, response, _ = fixture(name)
    # Legacy analytical placeholders are not the subject of these extraction controls.
    for key in ("area_context", "problem_solution", "related_work", "experiments",
                "limitations", "critical_assessment"):
        if key in response["deep_readings"]:
            response["deep_readings"][key]["evidence"] = [{"quote": artifact.text.split("\n\n")[0]}]
    original = copy.deepcopy(response)
    referenced = json.loads(source_response(json.dumps(response), [
        Message('user', paper_reading_prompt(artifact))]))
    referenced["deep_readings"]["method_flow"] = operations(name)
    reading = parse_paper_reading(json.dumps(referenced), artifact)
    assert reading.claim_units
    assert response == original
    for unit in reading.claim_units:
        assert all(anchor.quote in artifact.text for anchor in unit.evidence)
        assert all("source block" in anchor.location for anchor in unit.evidence)
    assert reading.method_flow.operations
    assert all(op.scope for op in reading.method_flow.operations)


@pytest.mark.parametrize("bad", ["foreign", "reverse", "oversize", "extra", "cross_page"])
def test_source_reference_cannot_select_another_source_or_unbounded_context(bad: str) -> None:
    module = source_module()
    artifact = replace(fixture("memguide")[0], text="[page 1]\n" + "a\n" * 800
                       + "[page 2]\nOther source line.\n")
    index = module.build_source_index(artifact)
    reference = index.reference_for_span(artifact.text.index("a\n"), artifact.text.index("a\n")+1)
    if bad == "foreign":
        foreign = module.build_source_index(replace(artifact, source=replace(
            artifact.source, url="https://other.test/paper")))
        reference = foreign.reference_for_span(
            artifact.text.index("a\n"), artifact.text.index("a\n")+1)
    elif bad == "reverse":
        reference = {"start": index.units[-1].identity, "end": index.units[0].identity}
    elif bad == "oversize":
        reference = {"start": index.units[0].identity, "end": index.units[-2].identity}
    elif bad == "extra":
        reference["quote"] = "Invented replacement."
    else:
        reference = {"start": index.units[0].identity, "end": index.units[-1].identity}
    with pytest.raises(AnalysisError):
        index.resolve(reference)


def test_source_labels_preserve_every_character_including_formula_layout() -> None:
    module = source_module()
    artifact = replace(fixture("memconflict")[0], text="[page 1]\nAA= 1\n𝑁∑︁\n𝑖=1\n\n末尾  ")
    index = module.build_source_index(artifact)
    assert "".join(artifact.text[u.start:u.end] for u in index.units) == artifact.text
    resolved = [index.resolve(ref)['quote']
                for ref in index.references_for_span(0, len(artifact.text))]
    assert ''.join(resolved) == artifact.text


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_operation_flow_reuses_claim_ledger_and_existing_review(name: str) -> None:
    artifact, _, claims, data = extract(name)
    proposed = operations(name)
    flow = parse_method_flow(proposed, claim_ids={c["claim_id"] for c in data["claim_units"]})
    assert method_flow_payload(flow) == proposed
    payload = fact_provider(data).payloads[0]
    reviewed = apply_method_decisions(flow, claims, payload, source_url=artifact.source.url)
    assert reviewed_method_flow(reviewed, claims, source_url=artifact.source.url) == proposed
    assert set(method_claim_ids(flow)) == {x["claim_id"] for x in data["claim_units"]}
    changed = replace(reviewed, operations=[replace(reviewed.operations[0], scope="Different task"),
                                           *reviewed.operations[1:]])
    with pytest.raises(AnalysisError, match="roles"):
        reviewed_method_flow(changed, claims, source_url=artifact.source.url)


@pytest.mark.parametrize("bad", ["unknown", "duplicate", "mixed", "self_approval", "bare_product"])
def test_operation_structure_is_strict_without_guessing_roles(bad: str) -> None:
    data = fixture("memguide")[2]
    value = operations("memguide")
    if bad == "unknown":
        value["operations"][0]["outputs"][0]["supporting_claim_ids"] = ["unknown"]
    elif bad == "duplicate":
        value["operations"].append(copy.deepcopy(value["operations"][0]))
    elif bad == "mixed":
        value["step_claim_ids"] = ["m2"]
    elif bad == "self_approval":
        value["operations"][0]["review"] = {"status": "supported"}
    else:
        value["operations"][0]["outputs"] = ["m2"]
    with pytest.raises(AnalysisError):
        parse_method_flow(value, claim_ids={c["claim_id"] for c in data["claim_units"]})


@pytest.mark.parametrize("changed", ["inputs", "outputs", "conditions"])
def test_every_operation_role_is_part_of_the_source_bound_review(changed: str) -> None:
    from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

    url = "https://example.test/operation"
    claims = [Claim(text, ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=url, quote=text)],
        metadata={"paper_reading": {"claim_id": identity}}) for identity, text in [
            ("input", "Input is a file."), ("action", "The process reads the file."),
            ("output", "Output consists of records."), ("condition", "A batch contains 12 rows.")]]
    value = {"operations": [{"scope": "File processing", "operation_claim_id": "action",
        "inputs": [{"name":"file","supporting_claim_ids":["input"]}],
        "outputs": [{"name":"records","supporting_claim_ids":["output"]}],
        "conditions": [{"name":"12 rows per batch","supporting_claim_ids":["condition"]}]}],
        "links": [], "gaps": []}
    flow = parse_method_flow(value, claim_ids={"input", "action", "output", "condition"})
    assert set(method_claim_ids(flow)) == {"input", "action", "output", "condition"}
    approved = apply_method_decisions(flow, claims, {"method_operation_decisions": [{
        "source_url": url, "operation_claim_id": "action", "status": "supported",
        "reason": "Offline synthetic role control."}]},
        source_url=url)
    assert reviewed_method_flow(approved, claims, source_url=url) == value
    modified = replace(approved, operations=[replace(approved.operations[0], **{changed: []})])
    with pytest.raises(AnalysisError, match="roles"):
        reviewed_method_flow(modified, claims, source_url=url)


@pytest.mark.parametrize("bad", ["quote", "foreign", "mixed"])
def test_fresh_reference_failure_does_not_request_repair_or_approve_a_claim(bad: str) -> None:
    from reader_fixtures import source_response
    from test_paper_reading import _artifact, _claim_units_fixture

    from research_radar.analysis.paper_reading import model_paper_reading_with_attempts

    artifact = _artifact()
    calls = []

    class Reader:
        name = "offline"
        reader_contexts = {"offline": ReaderContextBudget(1000000, 32768, 4096)}

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            calls.append(messages)
            body = json.loads(source_response(_claim_units_fixture([artifact.text]), messages))
            anchor = body["deep_readings"]["claim_units"][0]["evidence"][0]
            if bad == "quote":
                anchor.clear()
                anchor.update(quote="Paraphrased original.", location="page 1")
            elif bad == "foreign":
                anchor["source_id"] = "foreign:1"
            else:
                anchor["quote"] = "Model replacement."
            return ModelResponse(json.dumps(body), model)

    with pytest.raises(SourceReferenceError) as failure:
        model_paper_reading_with_attempts(artifact, Reader(), model="offline")
    assert len(calls) == 1
    assert failure.value.reader_attempts[0]["status"] == "failed"


def test_fresh_schema_does_not_fall_back_to_legacy_method_roles() -> None:
    from reader_fixtures import source_response
    from test_paper_reading import _artifact, _claim_units_fixture

    from research_radar.analysis.paper_reading import model_paper_reading_with_attempts

    artifact, calls = _artifact(), []

    class Reader:
        name = "offline"
        supports_response_schema = True
        reader_contexts = {"offline": ReaderContextBudget(1000000, 32768, 4096)}

        def complete_with_schema(self, messages, *, model, response_schema):
            body_schema = response_schema["properties"]["deep_readings"]["items"]["properties"]
            assert set(body_schema["method_flow"]["properties"]) == {"operations", "links", "gaps"}
            assert set(body_schema["claim_units"]["items"]["properties"]["evidence"][
                "items"]["properties"]) == {"source_id"}
            calls.append(messages)
            body = json.loads(source_response(_claim_units_fixture([artifact.text]), messages))
            body["deep_readings"]["method_flow"] = {"input_claim_ids": [],
                "step_claim_ids": [], "output_claim_ids": [], "links": [], "gaps": []}
            return ModelResponse(json.dumps(body), model)

    with pytest.raises(AnalysisError, match="scoped operation"):
        model_paper_reading_with_attempts(artifact, Reader(), model="offline")
    assert len(calls) == 1


def test_legacy_experiment_evidence_alias_cannot_bypass_fresh_source_selection() -> None:
    from research_radar.analysis.source_references import resolve_reader_evidence

    with pytest.raises(SourceReferenceError, match="source IDs"):
        resolve_reader_evidence({"experiment_evidence": [{"quote": "Generated quote."}]},
                                fixture("memguide")[0], require_references=True)


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
@pytest.mark.parametrize("entry", ["paper", "daily"])
@pytest.mark.parametrize("decision", ["supported", "wrong_role", "wrong_link"])
def test_source_operations_reach_chinese_body_through_actual_pipeline(
    name: str, entry: str, decision: str, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    from test_publication_composition import Composer

    from research_radar.config import parse_config
    from research_radar.pipeline import daily, paper
    from research_radar.security.secrets import KeychainSecretBackend
    from research_radar.storage.files import read_jsonl

    artifact, response, data = fixture(name)
    response["deep_readings"]["method_flow"] = operations(name)
    artifact = replace(artifact, source=replace(artifact.source, score=1,
        summary="Agent memory retrieval and evaluation with source-grounded methods."))
    facts = fact_provider(data).payloads[0]
    if decision == "wrong_role":
        # Every node fact can be true while its proposed operation role is not.
        first = response["deep_readings"]["method_flow"]["operations"][0]
        first["outputs"][0]["name"] = 'deployed autonomous research assistants'
        facts["method_operation_decisions"][0]["status"] = "unsupported"
    elif decision == "wrong_link":
        facts["method_link_decisions"][0]["status"] = "unsupported"
    final = {"decisions": facts["decisions"], "explanation_decisions": [{
        "paragraph_id": f"p1.solution_walkthrough.{i}", "status": "supported",
        "reason": "Offline editorial control, not real model review.",
        "covered_claim_ids": p["supporting_claim_ids"]}
        for i, p in enumerate(data["writer_control"]["reader_explanation"][
            "solution_walkthrough"], 1)]}
    order = []

    class Stage(Composer):
        def __init__(self, name, payload):
            super().__init__(payload)
            self.stage = name

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            order.append(self.stage)
            return super().complete(messages, model=model)

    class Connector:
        name = "offline"

        def discover(self, context):
            return [artifact.source]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline operation regression must not access services or credentials")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)
    module = paper if entry == "paper" else daily
    monkeypatch.setattr(module, "ingest_source", lambda *_a, **_k: artifact)
    reader = Stage("reader", response)
    reviewer = Stage("verifier", [facts, final])
    writer = Stage("writer", data["writer_control"])
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    options = dict(verifier=reviewer, verifier_model="offline", localizer=writer,
                   localization_model="offline", language="zh")

    def execute():
        if entry == "paper":
            return paper.run_paper(tmp_path, config, "memory", artifact.source.url,
                                   reader, model="offline", **options)
        return daily.run_daily(tmp_path, config, "memory", [Connector()], deep_reader=reader,
            deep_model="offline", deep_limit=1, figure_extractor=lambda *_a, **_k: [], **options)

    if decision != "supported":
        with pytest.raises(AnalysisError):
            execute()
        assert order == ["reader", "verifier"]
        assert not list(tmp_path.rglob("article_draft.json"))
        reviewed_facts = read_jsonl(next(tmp_path.rglob("fact_claims.jsonl")))
        assert reviewed_facts and all(c["status"] == "supported" for c in reviewed_facts)
        return
    run = execute()
    assert order == ["reader", "verifier", "writer", "verifier"]
    loaded = read_jsonl(run / "localized_readings.jsonl")[0]
    saved_operations = loaded["method_flow"]["operations"]
    assert [{key: value for key, value in op.items() if key != "review"}
            for op in saved_operations] == operations(name)["operations"]
    assert all(op["review"]["status"] == "supported" for op in saved_operations)
    prompt = json.loads(writer.requests[0][1].content.split(
        "FACT-REVIEWED CANDIDATES (JSON):\n")[1])
    assert prompt["method_flow"]["operations"] == operations(name)["operations"]
    report = (run / ("paper.md" if entry == "paper" else "wechat.html")).read_text()
    assert data["writer_control"]["reader_explanation"]["solution_walkthrough"][0]["text"] in report
