"""A review decision cites its own assertion, not a neighbour with a valid-looking ID."""

import copy
import json

import pytest
from method_contract_controls import control

from research_radar.analysis.paper_reading import parse_paper_reading, validate_paper_reading
from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.analysis.review_targets import build_review_targets
from research_radar.exceptions import AnalysisError


def contract(name="memconflict"):
    artifact, response, _ = control(name)
    reading = parse_paper_reading(json.dumps(response), artifact, require_method_assertions=True)
    claims, _ = validate_paper_reading(reading, artifact, include_context_claims=True)
    context, _ = build_reading_review_context([reading], claims, [artifact])
    return build_review_targets(claims, context)


def approval(targets):
    return {"decisions": {key: {"status": "supported", "reason": "Explicit offline judgment.",
        "evidence_refs": list(value["direct_evidence"])}
        for key, value in targets.targets.items()}}


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_operation_target_contains_only_its_assertion_and_explicit_roles(name):
    targets = contract(name)
    operation = next(t for t in targets.targets.values() if t["kind"] == "operation")
    required = {operation["operation_claim_id"]} | {
        i for role in ("inputs", "outputs", "conditions") for v in operation[role]
        for i in v["supporting_claim_ids"]
    }
    assert {c["claim_id"] for c in operation["supporting_claims"]} == required
    assert operation["direct_evidence"]
    assert operation["assertion"]["claim_id"] == operation["operation_claim_id"]


def test_link_target_uses_relation_fact_and_exact_endpoint_records():
    targets = contract()
    link = next(t for t in targets.targets.values() if t["kind"] == "link")
    assert link["assertion"]["claim_id"] == link["relation_claim_id"]
    assert {c["claim_id"] for c in link["supporting_claims"]} == {
        link["from_claim_id"], link["to_claim_id"], link["relation_claim_id"],
    }


@pytest.mark.parametrize("bad", ["neighbour", "missing", "unknown", "wrong_type", "empty"])
def test_structurally_valid_status_cannot_cite_another_assertions_evidence(bad):
    targets = contract()
    operations = [(k, t) for k, t in targets.targets.items() if t["kind"] == "operation"]
    key, current = operations[0]
    other = next(t for _, t in operations
                 if set(t["direct_evidence"]) != set(current["direct_evidence"]))
    reply = approval(targets)
    if bad == "missing":
        reply["decisions"][key].pop("evidence_refs")
    elif bad == "neighbour":
        reply["decisions"][key]["evidence_refs"] = list(other["direct_evidence"])
    elif bad == "unknown":
        reply["decisions"][key]["evidence_refs"].append("made-up-source")
    elif bad == "wrong_type":
        reply["decisions"][key]["evidence_refs"] = dict.fromkeys(current["direct_evidence"], True)
    else:
        reply["decisions"][key]["evidence_refs"] = []
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(reply))


def test_valid_target_evidence_is_preserved_without_reinterpreting_free_text():
    targets = contract()
    reply = approval(targets)
    key = next(k for k, t in targets.targets.items() if t["kind"] == "operation")
    # Deliberately contradictory prose remains a model-quality defect, not an ID-remapping hint.
    reply["decisions"][key]["reason"] = "Discusses a different operation; intentionally retained."
    normalized = json.loads(targets.normalize(json.dumps(reply)))
    record = next(r for r in normalized["method_operation_decisions"]
                  if r["operation_claim_id"] == targets.targets[key]["operation_claim_id"])
    assert record["reason"] == reply["decisions"][key]["reason"]
    saved = json.loads(normalized["structured_review"]["raw_response"])
    assert saved["decisions"][key]["evidence_refs"] == reply["decisions"][key]["evidence_refs"]


def test_selected_table_cells_change_fact_target_identity():
    from research_radar.models import Claim, ClaimStatus, EvidenceAnchor
    base = Claim("MemOS has AA of 0.4375.", ClaimStatus.SUPPORTED,
                 evidence=[EvidenceAnchor("https://example.test", "MemOS 0.4375")])
    current = build_review_targets([base], "")
    changed = copy.deepcopy(base)
    changed.metadata["anchor_resolution"] = {"evidence_contexts": [{"positioned": {
        "table": {"table_id": "document-bound-source", "physical_page": 1,
                  "cells": [{"cell_id": "c1", "row_headers": ["MemOS"],
                             "column_headers": ["AA"], "value": "0.4375"}]},
        "selected_cell_ids": ["c1"],
    }, "source_url": "https://example.test", "quote": "MemOS 0.4375"}]}
    assert set(build_review_targets([changed], "").targets) != set(current.targets)


@pytest.mark.parametrize("bad", [[{}], [None], [1]])
def test_nonstring_evidence_references_fail_as_a_contract_error(bad):
    targets = contract()
    reply = approval(targets)
    key = next(iter(reply["decisions"]))
    reply["decisions"][key]["evidence_refs"] = bad
    with pytest.raises(AnalysisError):
        targets.normalize(json.dumps(reply))


def test_changed_cell_content_invalidates_existing_factual_approval(tmp_path):
    from test_positioned_tables import positioned
    from test_review_targets import SchemaReviewer

    from research_radar.analysis.anchor_repair import apply_anchor_resolution
    from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
    from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

    artifact = positioned("conflict3", tmp_path)
    quote = artifact.text.split("AA UOCS AA CRS AA AA\n")[1]
    candidate = Claim("MemOS reports Static AA of 0.4375.", ClaimStatus.SUPPORTED,
                      evidence=[EvidenceAnchor(artifact.source.url, quote)])
    checked, _, _ = apply_anchor_resolution([candidate], artifact)
    fact, = review_publication_facts(checked, SchemaReviewer(), model="offline",
                                   readings=[], artifacts=[artifact]).claims
    assert fact_is_reviewed(fact)
    changed = copy.deepcopy(fact)
    table = changed.metadata["anchor_resolution"]["evidence_contexts"][0]["positioned"]["table"]
    table["cells"][0]["value"] = "0.9999"
    assert not fact_is_reviewed(changed)
