"""Method roles and relation endpoints are explicit assertions in the existing claim ledger."""

import copy
import json

import pytest
from test_method_flow import fixture
from test_reader_source_operations import operations

from research_radar.analysis.paper_reading import parse_paper_reading
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.exceptions import AnalysisError


def typed_reading():
    artifact, response, data = fixture("memconflict")
    body = response["deep_readings"]
    body["method_flow"] = operations("memconflict")
    for unit in body["claim_units"]:
        unit["method"] = None
    ids = {op["operation_claim_id"] for op in body["method_flow"]["operations"]}
    for unit in body["claim_units"]:
        if unit["claim_id"] in ids:
            unit["method"] = {"kind": "operation", "from_claim_id": None, "to_claim_id": None}
    for link in body["method_flow"]["links"]:
        identity = link.pop("supporting_claim_ids")[0]
        link["relation_claim_id"] = identity
        unit = next(unit for unit in body["claim_units"] if unit["claim_id"] == identity)
        unit["method"] = {
            "kind": "precedes",
            "from_claim_id": link["from_claim_id"],
            "to_claim_id": link["to_claim_id"],
        }
    return artifact, response


def test_typed_relations_share_the_canonical_fact_and_literal_evidence():
    artifact, response = typed_reading()
    reading = parse_paper_reading(json.dumps(response), artifact)
    assert reading.method_flow.links[0].relation_claim_id
    identity = reading.method_flow.links[0].relation_claim_id
    unit = next(unit for unit in reading.claim_units if unit.claim_id == identity)
    assert unit.method.kind == "precedes" and unit.evidence


@pytest.mark.parametrize(
    "bad",
    [
        "wrong_endpoint",
        "condition_as_operation",
        "missing_relation",
        "unknown_relation",
        "same_node",
        "wrong_type",
    ],
)
def test_explicit_wrong_roles_and_relation_bindings_fail_without_language_guessing(bad):
    artifact, response = typed_reading()
    body = response["deep_readings"]
    link = body["method_flow"]["links"][0]
    unit = next(
        unit for unit in body["claim_units"] if unit["claim_id"] == link["relation_claim_id"]
    )
    if bad == "wrong_endpoint":
        unit["method"]["from_claim_id"] = link["to_claim_id"]
    elif bad == "condition_as_operation":
        op = body["method_flow"]["operations"][0]
        node = next(
            unit for unit in body["claim_units"] if unit["claim_id"] == op["operation_claim_id"]
        )
        node["method"]["kind"] = "condition"
    elif bad == "missing_relation":
        unit["method"] = None
    elif bad == "unknown_relation":
        link["relation_claim_id"] = "not-a-fact"
    elif bad == "same_node":
        unit["method"]["to_claim_id"] = unit["method"]["from_claim_id"]
    else:
        unit["method"] = "precedes"
    original = copy.deepcopy(response)
    with pytest.raises(AnalysisError, match="[Mm]ethod|relation|operation"):
        parse_paper_reading(json.dumps(response), artifact)
    assert response == original


def test_reader_schema_requires_method_assertions_and_single_relation_fact_identity():
    body = paper_reading_response_schema(facts_only=True)["properties"]["deep_readings"]["items"]
    unit = body["properties"]["claim_units"]["items"]
    assert "method" in unit["required"]
    link = body["properties"]["method_flow"]["properties"]["links"]["items"]
    assert set(link["required"]) == {"from_claim_id", "to_claim_id", "relation_claim_id"}


def test_new_schema_path_cannot_silently_accept_an_untyped_old_method():
    artifact, response, _ = fixture("memconflict")
    response["deep_readings"]["method_flow"] = operations("memconflict")
    parse_paper_reading(json.dumps(response), artifact)  # Saved legacy records are still readable.
    with pytest.raises(AnalysisError, match="operation assertion"):
        parse_paper_reading(json.dumps(response), artifact, require_method_assertions=True)


@pytest.mark.parametrize("target", ["c5", "c6", "c7", "c8"])
def test_actual_c37_quote_cannot_be_reused_as_a_different_timeline_edge(target):
    from research_radar.analysis.method_flow import (
        MethodAssertion,
        parse_method_flow,
        validate_method_assertions,
    )

    # Explicit editorial annotation: c37 asserts c8 -> c9, not c4 -> any insertion node.
    assertions = {
        identity: MethodAssertion("operation") for identity in ("c4", "c5", "c6", "c7", "c8", "c9")
    }
    assertions["c37"] = MethodAssertion("precedes", "c8", "c9")
    flow = {
        "operations": [
            {
                "scope": "Offline operation control",
                "operation_claim_id": identity,
                "inputs": [],
                "outputs": [],
                "conditions": [],
            }
            for identity in ("c4", "c5", "c6", "c7", "c8", "c9")
        ],
        "links": [{"from_claim_id": "c4", "to_claim_id": target, "relation_claim_id": "c37"}],
        "gaps": [],
    }
    parsed = parse_method_flow(flow, claim_ids=set(assertions))
    with pytest.raises(AnalysisError, match="endpoints"):
        validate_method_assertions(parsed, assertions)
    flow["links"] = [{"from_claim_id": "c8", "to_claim_id": "c9", "relation_claim_id": "c37"}]
    validate_method_assertions(parse_method_flow(flow, claim_ids=set(assertions)), assertions)
