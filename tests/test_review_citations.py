"""Sparse evidence citations retain target coverage and the exact positive-approval boundary."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_review_evidence_selection import mixed_claim

from research_radar.analysis.review_targets import (
    ReviewContractError,
    ReviewTargets,
    build_review_targets,
    validate_review_response,
)


def citations_reply(contract: ReviewTargets, *, status: str = "supported") -> dict:
    """Explicit test judgments; only the offered references are cited."""
    return {"decisions": {key: {"status": status, "reason": "Offline editorial control.",
        "evidence_refs": list(target["direct_evidence"])}
        for key, target in contract.targets.items()}}


def v3_schema(contract: ReviewTargets) -> dict:
    """The prior fixed-boolean request shape, retained solely for historical validation."""
    schema = copy.deepcopy(contract.schema)
    schema["$id"] = "urn:research-radar:review-targets:v3"
    for key, target in contract.targets.items():
        item = schema["properties"]["decisions"]["properties"][key]
        item["properties"].pop("evidence_refs", None)
        item["properties"]["evidence_selection"] = {"type": "object",
            "properties": {ref: {"type": "boolean"} for ref in target["direct_evidence"]},
            "required": list(target["direct_evidence"]), "additionalProperties": False}
        item["required"] = list(item["properties"])
    return schema


def test_new_schema_requires_short_citations_not_one_boolean_per_offered_record() -> None:
    contract = build_review_targets([mixed_claim()], "")
    assert contract.schema["$id"] == "urn:research-radar:review-targets:v4"
    key, target = next(iter(contract.targets.items()))
    shape = contract.schema["properties"]["decisions"]["properties"][key]
    assert set(shape["required"]) == {"status", "reason", "evidence_refs"}
    assert shape["properties"]["evidence_refs"]["items"]["enum"] == list(target["direct_evidence"])
    assert shape["additionalProperties"] is False


def test_subset_citations_preserve_exact_raw_text_and_canonical_proof_identity() -> None:
    contract = build_review_targets([mixed_claim()], "")
    reply = citations_reply(contract)
    key = next(iter(contract.targets))
    chosen = next(iter(contract.targets[key]["direct_evidence"]))
    reply["decisions"][key]["evidence_refs"] = [chosen]
    raw = json.dumps(reply, ensure_ascii=False, indent=2)
    result = json.loads(contract.normalize(raw))
    assert result["decisions"][0]["status"] == "supported"
    assert result["structured_review"]["raw_response"] == raw
    assert result["structured_review"]["schema_id"] == contract.schema["$id"]
    assert result["structured_review"]["selected_evidence"][key] == [
        contract.evidence_bindings[key][chosen]]
    assert result["structured_review"]["targets"] == contract.targets


@pytest.mark.parametrize("bad", ["duplicate", "unknown", "wrong_type", "object", "empty_positive"])
def test_invalid_citations_are_rejected_without_deduplication_or_inference(bad: str) -> None:
    contract = build_review_targets([mixed_claim()], "")
    reply = citations_reply(contract)
    row = next(iter(reply["decisions"].values()))
    if bad == "duplicate":
        row["evidence_refs"].append(row["evidence_refs"][0])
    elif bad == "unknown":
        row["evidence_refs"] = ["not-offered"]
    elif bad == "wrong_type":
        row["evidence_refs"] = [1]
    elif bad == "object":
        row["evidence_refs"] = {}
    else:
        row["evidence_refs"] = []
    before = copy.deepcopy(reply)
    with pytest.raises(ReviewContractError):
        contract.normalize(json.dumps(reply))
    assert reply == before


@pytest.mark.parametrize("status", ["needs_review", "unsupported", "speculative"])
def test_nonpublic_status_can_abstain_without_fabricating_a_citation(status: str) -> None:
    contract = build_review_targets([mixed_claim()], "")
    reply = citations_reply(contract, status=status)
    next(iter(reply["decisions"].values()))["evidence_refs"] = []
    result = json.loads(contract.normalize(json.dumps(reply)))
    assert result["decisions"][0]["status"] == status
    assert not any(result["structured_review"]["selected_evidence"].values())


def test_another_target_or_registry_identifier_is_not_a_valid_citation() -> None:
    left = mixed_claim()
    right = replace(copy.deepcopy(left), text="Another exact assertion.")
    right.metadata["paper_reading"]["claim_id"] = "c48"
    contract = build_review_targets([left, right], "")
    first, other = contract.targets
    for foreign in [next(iter(contract.targets[other]["direct_evidence"])), "s1"]:
        reply = citations_reply(contract)
        reply["decisions"][first]["evidence_refs"] = [foreign]
        with pytest.raises(ReviewContractError):
            contract.normalize(json.dumps(reply))


def test_target_order_does_not_route_reasons_or_claims_by_position() -> None:
    left = mixed_claim()
    right = replace(copy.deepcopy(left), text="Different assertion.")
    right.metadata["paper_reading"]["claim_id"] = "c48"
    contract = build_review_targets([left, right], "")
    reply = citations_reply(contract)
    for index, row in enumerate(reply["decisions"].values()):
        row["reason"] = f"Explicit control {index}"
    reversed_reply = {"decisions": dict(reversed(list(reply["decisions"].items())))}
    assert json.loads(contract.normalize(json.dumps(reply)))["decisions"] == json.loads(
        contract.normalize(json.dumps(reversed_reply)))["decisions"]


def test_complete_target_coverage_is_required_and_no_decision_is_filled_in() -> None:
    contract = build_review_targets([mixed_claim()], "")
    with pytest.raises(ReviewContractError, match="target_set_mismatch"):
        contract.normalize('{"decisions":{}}')


def test_old_boolean_answer_is_not_silently_converted_for_new_request() -> None:
    contract = build_review_targets([mixed_claim()], "")
    key, target = next(iter(contract.targets.items()))
    raw = json.dumps({"decisions": {key: {"status": "supported", "reason": "Historical control",
        "evidence_selection": dict.fromkeys(target["direct_evidence"], True)}}})
    validate_review_response(raw, v3_schema(contract))
    with pytest.raises(ReviewContractError, match="decision_fields"):
        contract.normalize(raw)


def test_legacy_v3_positive_without_evidence_remains_invalid() -> None:
    contract = build_review_targets([mixed_claim()], "")
    key, target = next(iter(contract.targets.items()))
    raw = json.dumps({"decisions": {key: {"status": "supported", "reason": "Observed failure shape",
        "evidence_selection": dict.fromkeys(target["direct_evidence"], False)}}})
    with pytest.raises(ReviewContractError, match="supported_without_evidence"):
        validate_review_response(raw, v3_schema(contract))


@pytest.mark.parametrize("status", ["needs_review", "unsupported", "speculative"])
def test_legacy_v3_abstention_keeps_original_status_and_no_selected_proof(status: str) -> None:
    contract = build_review_targets([mixed_claim()], "")
    key, target = next(iter(contract.targets.items()))
    raw = json.dumps({"decisions": {key: {"status": status, "reason": "Historical uncertainty",
        "evidence_selection": dict.fromkeys(target["direct_evidence"], False)}}})
    result = validate_review_response(raw, v3_schema(contract))
    assert result["decisions"][key]["status"] == status
    assert not any(result["decisions"][key]["evidence_selection"].values())


@pytest.mark.parametrize("mask", range(4))
@pytest.mark.parametrize("status", ["supported", "needs_review"])
def test_sparse_and_boolean_forms_have_the_same_approval_boundary(mask: int, status: str) -> None:
    contract = build_review_targets([mixed_claim()], "")
    key, target = next(iter(contract.targets.items()))
    refs = list(target["direct_evidence"])
    selected = [ref for index, ref in enumerate(refs) if mask & (1 << index)]
    row = {"status": status, "reason": "Explicit equivalent offline controls."}
    current = {"decisions": {key: {**row, "evidence_refs": selected}}}
    legacy = {"decisions": {key: {**row, "evidence_selection": {
        ref: ref in selected for ref in refs}}}}
    outcomes = []
    for payload, schema in ((legacy, v3_schema(contract)), (current, contract.schema)):
        try:
            validate_review_response(json.dumps(payload), schema)
        except ReviewContractError as error:
            outcomes.append(error.diagnostics["code"])
        else:
            outcomes.append("valid")
    assert outcomes[0] == outcomes[1]
    if outcomes[1] == "valid":
        normalized = json.loads(contract.normalize(json.dumps(current)))
        assert normalized["structured_review"]["selected_evidence"][key] == [
            contract.evidence_bindings[key][ref] for ref in selected]


@pytest.mark.parametrize("legacy", [False, True])
def test_invalid_current_and_legacy_reviews_never_enter_cache(tmp_path: Path, legacy: bool) -> None:
    from research_radar.analysis.model_cache import CachedLLMProvider
    from research_radar.analysis.providers import Message, ModelResponse

    contract = build_review_targets([mixed_claim()], "")
    key, target = next(iter(contract.targets.items()))

    class Invalid:
        name = "offline-invalid"
        supports_response_schema = True
        calls = 0

        def complete_with_schema(
            self, messages: list[Message], *, model: str, response_schema: dict,
        ) -> ModelResponse:
            self.calls += 1
            field, refs = (("evidence_selection", dict.fromkeys(target["direct_evidence"], False))
                           if legacy else ("evidence_refs", []))
            return ModelResponse(json.dumps({"decisions": {key: {"status": "supported",
                "reason": "Offline invalid control", field: refs}}}), model)

    provider = Invalid()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="review")
    with pytest.raises(ReviewContractError):
        cached.complete_with_schema([Message("user", "Offline exact target")], model="offline",
            response_schema=v3_schema(contract) if legacy else contract.schema)
    assert provider.calls == 1
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
@pytest.mark.parametrize("bad", ["empty", "duplicate", "foreign"])
def test_invalid_final_citations_keep_candidate_but_never_publish_or_retry(
    name: str, bad: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_evaluation_fact_index import paper_control
    from test_method_contract_pipeline import Reading, Reviewing, Writing

    from research_radar.config import parse_config
    from research_radar.pipeline import paper

    artifact, response, chinese, _ = paper_control(name)
    order: list[str] = []

    class Reviewer(Reviewing):
        def complete_with_schema(self, *args, **kwargs):
            answer = super().complete_with_schema(*args, **kwargs)
            if len(self.requests) == 2:
                payload = json.loads(answer.content)
                row = next(iter(payload["decisions"].values()))
                row["evidence_refs"] = ([] if bad == "empty" else ["s1"] if bad == "foreign"
                                        else [row["evidence_refs"][0]] * 2)
                return replace(answer, content=json.dumps(payload))
            return answer

    reviewer = Reviewer(order)
    monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
    with pytest.raises(ReviewContractError):
        paper.run_paper(tmp_path, parse_config({"topics": [{"id": "memory",
            "queries": ["agent memory"]}]}), "memory", artifact.source.url,
            Reading(response, order), model="offline", verifier=reviewer, verifier_model="offline",
            localizer=Writing(chinese, order), localization_model="offline", language="zh")
    assert order == ["reader", "review", "writer", "review"]
    assert len(reviewer.requests) == 2
    assert list(tmp_path.rglob("publication_candidates.jsonl"))
    assert not list(tmp_path.rglob("paper.md"))
    assert not list(tmp_path.rglob("wechat.html"))
