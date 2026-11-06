"""Real wrong-column replies cannot establish a complete table comparison."""

import copy
import json
import socket
from pathlib import Path

import pytest

from research_radar.analysis.review_targets import build_review_targets, validate_review_response
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor
from research_radar.security.secrets import KeychainSecretBackend

DATA = json.loads((Path(__file__).parent / "fixtures/method_flow/table_comparison_review.json")
                  .read_text())


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("No model, network or credentials in table comparison regression")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def contract(case: dict):
    row = case["claim"]
    claim = Claim(row["text"], ClaimStatus(row["status"]),
        [EvidenceAnchor(**e) for e in row["evidence"]], row["rationale"], row["metadata"])
    context = {"experimental_result_proposals": [{"source_url": DATA["source_url"],
        "results": [case["proposal"]], "bindings": [case["binding"]]}]}
    return build_review_targets([claim], json.dumps(context, ensure_ascii=False))


def approval(targets) -> dict:
    decisions = {}
    for identity, shape in targets.schema["properties"]["decisions"]["properties"].items():
        fields = shape["properties"]
        decisions[identity] = {"status": "supported", "reason": "Offline structural control.",
            "evidence_refs": fields["evidence_refs"]["items"].get("enum", [])}
        if "comparison_checks" in fields:
            decisions[identity]["comparison_checks"] = dict.fromkeys(
                fields["comparison_checks"]["properties"], True)
    return {"decisions": decisions}


@pytest.mark.parametrize("case", DATA["cases"], ids=["JGA", "Slot Accuracy"])
def test_actual_wrong_columns_become_complete_literal_metric_units(case: dict) -> None:
    targets = contract(case)
    target, = targets.targets.values()
    assert target["comparison_units"]
    ref, = target["comparison_units"]
    unit = target["direct_evidence"][ref]
    assert unit["complete"] is True
    assert unit["metric_binding"] == "exact"
    assert len(unit["tables"]) == 1
    table = unit["tables"][0]
    assert len(table["cells"]) == 8
    metric = case["proposal"]["metric"].casefold()
    assert all(" ".join(c["column_headers"]).casefold() == metric for c in table["cells"])
    missing_row = ["Mistral-7B", "MemGuide"]
    expected = "0.80" if metric == "jga" else "0.56"
    assert any(c["row_headers"] == missing_row and c["value"] == expected for c in table["cells"])
    assert unit["proposal"] == case["proposal"]  # Paired strings and directions are not inferred.
    reply = approval(targets)
    normalized = json.loads(targets.normalize(json.dumps(reply)))
    assert normalized["structured_review"]["schema_id"].endswith(":v5")
    assert normalized["structured_review"]["raw_response"] == json.dumps(reply)
    assert normalized["structured_review"]["selected_evidence"]


@pytest.mark.parametrize("case", DATA["cases"], ids=["wrong-JGA-cell", "duplicate-and-ROUGE"])
def test_actual_return_is_not_repaired_or_reinterpreted(case: dict) -> None:
    before = copy.deepcopy(case)
    targets = contract(case)
    key, = targets.targets
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps({"decisions": {key: case["original_decision"]}}))
    assert case == before


def test_deduplicating_the_old_invalid_reply_is_still_not_a_new_approval() -> None:
    case = DATA["cases"][1]
    reply = copy.deepcopy(case["original_decision"])
    reply["evidence_refs"] = list(dict.fromkeys(reply["evidence_refs"]))
    targets = contract(case)
    key, = targets.targets
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps({"decisions": {key: reply}}))


@pytest.mark.parametrize("defect", ["missing", "false", "unknown", "wrong_type", "scalar_ref"])
def test_complete_comparison_confirmation_is_required(defect: str) -> None:
    targets = contract(DATA["cases"][0])
    reply = approval(targets)
    decision, = reply["decisions"].values()
    refs = decision["comparison_checks"]
    key = next(iter(refs))
    if defect == "missing":
        del decision["comparison_checks"]
    elif defect == "false":
        refs[key] = False
    elif defect == "unknown":
        refs["foreign-unit"] = refs.pop(key)
    elif defect == "wrong_type":
        refs[key] = "true"
    else:
        decision["evidence_refs"] = ["old-flat-cell-id"]
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(reply))


@pytest.mark.parametrize("defect", ["missing_cell", "wrong_value", "foreign", "duplicate_cell",
                                    "wrong_page"])
def test_incomplete_or_inconsistent_source_does_not_form_an_approved_unit(defect: str) -> None:
    case = copy.deepcopy(DATA["cases"][0])
    cells = case["binding"]["source_evidence"]["cells"]
    chosen = next(c for c in cells if c["row_headers"] == ["Mistral-7B", "MemGuide"]
                  and c["column_headers"] == ["JGA"])
    if defect == "missing_cell":
        cells.remove(chosen)
    elif defect == "wrong_value":
        chosen["value"] = "2.08"
    elif defect == "foreign":
        chosen["source_url"] = "https://foreign.test"
    elif defect == "duplicate_cell":
        cells.append(copy.deepcopy(chosen))
    else:
        case["proposal"]["physical_page"] = 999
    targets = contract(case)
    target, = targets.targets.values()
    assert not all(target["direct_evidence"][r]["complete"] for r in target["comparison_units"])
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(approval(targets)))


def test_unknown_metric_alias_is_not_silently_mapped_to_JGA() -> None:
    case = copy.deepcopy(DATA["cases"][0])
    case["proposal"]["metric"] = "Joint Goal Accuracy"
    targets = contract(case)
    target, = targets.targets.values()
    unit = target["direct_evidence"][target["comparison_units"][0]]
    assert unit["metric_binding"] == "semantic_review_required"
    assert unit["proposal"]["metric"] == "Joint Goal Accuracy"
    assert len({tuple(c["column_headers"]) for c in unit["tables"][0]["cells"]}) > 1


def test_original_v4_duplicate_reply_still_fails_its_original_contract() -> None:
    case = DATA["cases"][1]
    key = case["original_target_id"]
    schema = {"properties": {"decisions": {"properties": {key: case["original_schema"]}}}}
    with pytest.raises(AnalysisError, match="review_invalid_evidence_refs"):
        validate_review_response(
            json.dumps({"decisions": {key: case["original_decision"]}}), schema)


def test_v4_accepts_the_actual_wrong_column_reply_but_does_not_prove_entailment() -> None:
    case = DATA["cases"][0]
    key = case["original_target_id"]
    schema = {"properties": {"decisions": {"properties": {key: case["original_schema"]}}}}
    assert validate_review_response(
        json.dumps({"decisions": {key: case["original_decision"]}}), schema)


def test_prose_only_metric_definition_is_not_forced_into_a_table_comparison() -> None:
    case = copy.deepcopy(DATA["cases"][0])
    case["claim"]["metadata"].pop("anchor_resolution")
    targets = contract(case)
    target, = targets.targets.values()
    assert "comparison_units" not in target


def test_a_paragraph_inherits_the_closed_units_not_the_old_flat_choices() -> None:
    case = DATA["cases"][0]
    row = case["claim"]
    claim = Claim(row["text"], ClaimStatus(row["status"]),
        [EvidenceAnchor(**e) for e in row["evidence"]], row["rationale"], row["metadata"])
    context = {"experimental_result_proposals": [{"source_url": DATA["source_url"],
        "results": [case["proposal"]], "bindings": [case["binding"]]}],
        "paragraphs": [{"paragraph_id": "p1.experiment_interpretation.1",
            "source_url": DATA["source_url"], "text": claim.text,
            "supporting_claim_ids": ["c33"]}]}
    targets = build_review_targets([claim], json.dumps(context))
    fact, paragraph = targets.targets.values()
    assert fact["comparison_units"] == paragraph["comparison_units"]
    assert fact["direct_evidence"] == paragraph["direct_evidence"]
    reply = approval(targets)
    paragraph_id = next(k for k, t in targets.targets.items() if t["kind"] == "paragraph")
    reply["decisions"][paragraph_id]["covered_claim_ids"] = ["c33"]
    assert targets.normalize(json.dumps(reply))
    reply["decisions"][paragraph_id]["comparison_checks"][paragraph["comparison_units"][0]] = False
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(reply))


def test_unchanged_v5_receipt_retains_explicit_unit_confirmation() -> None:
    targets = contract(DATA["cases"][0])
    reply = approval(targets)
    receipt = json.loads(targets.normalize(json.dumps(reply)))
    reused = targets.reuse_supported(receipt)
    assert reused == reply["decisions"]
    assembled = targets.assemble(receipt, None)
    assert assembled["structured_review"]["receipts"] == [receipt]
    assert "raw_response" not in assembled["structured_review"]


def test_an_invalid_v5_comparison_response_cannot_enter_model_cache(tmp_path: Path) -> None:
    from research_radar.analysis.model_cache import CachedLLMProvider
    from research_radar.analysis.providers import ModelResponse

    targets = contract(DATA["cases"][0])
    reply = approval(targets)
    decision, = reply["decisions"].values()
    decision["comparison_checks"][next(iter(decision["comparison_checks"]))] = False

    class Provider:
        name = "offline"
        supports_response_schema = True
        calls = 0

        def complete_with_schema(self, _messages, *, model, response_schema):
            self.calls += 1
            return ModelResponse(json.dumps(reply), model)

    provider = Provider()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="review")
    with pytest.raises(AnalysisError):
        cached.complete_with_schema([], model="offline", response_schema=targets.schema)
    assert provider.calls == 1
    assert not list(tmp_path.rglob("*.json"))


def test_rejection_remains_rejection_without_affirmative_comparison_checks() -> None:
    targets = contract(DATA["cases"][0])
    reply = approval(targets)
    decision, = reply["decisions"].values()
    decision["status"] = "needs_review"
    decision["comparison_checks"] = dict.fromkeys(decision["comparison_checks"], False)
    normalized = json.loads(targets.normalize(json.dumps(reply)))
    assert normalized["decisions"][0]["status"] == "needs_review"
    assert not any(normalized["structured_review"]["selected_evidence"].values())


def test_duplicate_comparison_keys_are_rejected_not_silently_deduplicated() -> None:
    targets = contract(DATA["cases"][0])
    identity, = targets.targets
    ref, = targets.targets[identity]["comparison_units"]
    raw = ('{"decisions":{' + json.dumps(identity) + ': {"status":"supported",'
           '"reason":"Duplicate control", "evidence_refs":[], "comparison_checks":{'
           + json.dumps(ref) + ':true,' + json.dumps(ref) + ':true}}}}')
    with pytest.raises(AnalysisError, match="review_duplicate_key"):
        targets.normalize(raw)
