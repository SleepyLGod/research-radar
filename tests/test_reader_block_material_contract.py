"""Prebounded evidence and named role values remove copying and entity/action ambiguity."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_radar.analysis.method_flow import (
    apply_method_decisions,
    method_claim_ids,
    method_flow_payload,
    parse_method_flow,
    reviewed_method_flow,
)
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.analysis.source_references import SourceReferenceError, build_source_index
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

STOPPED = json.loads(
    (Path(__file__).parent / "fixtures/method_flow/stopped_source_contract.json").read_text()
)


def artifact(
    text: str = "The builder generates structured profiles from persona seeds.\n",
) -> Artifact:
    return Artifact(
        SourceCandidate(
            "Profile construction", "https://example.test/profiles", SourceType.PAPER, "offline"
        ),
        text,
    )


def proposal() -> dict:
    return {
        "operations": [
            {
                "scope": "Profile initialization",
                "operation_claim_id": "c5",
                "inputs": [{"name": "persona seeds", "supporting_claim_ids": ["c5"]}],
                "outputs": [{"name": "structured profiles", "supporting_claim_ids": ["c5"]}],
                "conditions": [],
            }
        ],
        "links": [],
        "gaps": [],
    }


def facts() -> list[Claim]:
    a = artifact()
    return [
        Claim(
            "Solution: " + a.text.strip(),
            ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url=a.source.url, quote=a.text.strip())],
            metadata={"paper_reading": {"claim_id": "c5"}},
        )
    ]


def decisions(status: str = "supported") -> dict:
    return {
        "method_operation_decisions": [
            {
                "source_url": artifact().source.url,
                "operation_claim_id": "c5",
                "status": status,
                "reason": "Offline check of named input, generated profile and source support.",
            }
        ]
    }


def test_every_offered_block_is_bounded_same_page_and_lossless() -> None:
    a = artifact("[page 1]\n" + "A source line.\n" * 300 + "\n[page 2]\nAA= 1\n𝑁∑︁\n𝑖=1\n")
    index = build_source_index(a)
    assert len(index.units) < 20  # Blocks, not hundreds of arbitrary line endpoints.
    assert "".join(a.text[u.start : u.end] for u in index.units) == a.text
    for unit in index.units:
        resolved = index.resolve({"source_id": unit.identity})
        assert resolved["quote"] == a.text[unit.start : unit.end]
        assert len(resolved["quote"]) <= 1200
    assert "source_id=" + index.units[0].identity in index.render()


def test_concrete_source_ids_are_bound_once_in_the_actual_schema() -> None:
    index = build_source_index(artifact())
    ids = [u.identity for u in index.units]
    schema = paper_reading_response_schema(facts_only=True, source_ids=ids)
    assert schema["$defs"]["source_id"]["enum"] == ids
    body = schema["properties"]["deep_readings"]["items"]["properties"]
    assert body["claim_units"]["items"]["properties"]["evidence"]["items"]["properties"] == {
        "source_id": {"$ref": "#/$defs/source_id"}
    }
    assert not any("[" in identity for identity in ids)


@pytest.mark.parametrize("kind", ["wrapped", "unknown", "foreign", "extra", "range"])
def test_block_selection_is_exact_not_a_bracket_stripping_fallback(kind: str) -> None:
    index = build_source_index(artifact())
    selection = {"source_id": index.units[0].identity}
    if kind == "wrapped":
        selection["source_id"] = "[" + selection["source_id"] + "]"
    elif kind == "unknown":
        selection["source_id"] = "b0000000000000000:1"
    elif kind == "foreign":
        other = build_source_index(artifact("A different original."))
        selection["source_id"] = other.units[0].identity
    elif kind == "extra":
        selection["quote"] = "A replacement."
    else:
        selection = copy.deepcopy(STOPPED["evidence"][0])
    before = copy.deepcopy(selection)
    with pytest.raises(SourceReferenceError):
        index.resolve(selection)
    assert selection == before


def test_stopped_real_shapes_are_not_silently_migrated() -> None:
    saved = copy.deepcopy(STOPPED)
    index = build_source_index(artifact())
    for selection in saved["evidence"]:
        with pytest.raises(SourceReferenceError):
            index.resolve(selection)
    with pytest.raises(AnalysisError):
        parse_method_flow(
            {"operations": saved["operations"], "links": [], "gaps": []}, claim_ids={"c5", "c6"}
        )
    assert saved == STOPPED


def test_action_and_named_output_can_share_a_fact_but_not_its_approval() -> None:
    value = proposal()
    flow = parse_method_flow(value, claim_ids={"c5"})
    assert method_flow_payload(flow) == value
    assert method_claim_ids(flow) == ["c5"]
    with pytest.raises(AnalysisError, match="roles"):
        reviewed_method_flow(flow, facts(), source_url=artifact().source.url)
    checked = apply_method_decisions(flow, facts(), decisions(), source_url=artifact().source.url)
    assert reviewed_method_flow(checked, facts(), source_url=artifact().source.url) == value
    changed_output = replace(checked.operations[0].outputs[0], name="published papers")
    changed = replace(
        checked, operations=[replace(checked.operations[0], outputs=[changed_output])]
    )
    with pytest.raises(AnalysisError, match="roles"):
        reviewed_method_flow(changed, facts(), source_url=artifact().source.url)


@pytest.mark.parametrize(
    "bad", ["bare_id", "unknown_support", "empty_support", "extra", "blank_name"]
)
def test_named_products_require_explicit_source_backed_support(bad: str) -> None:
    value = proposal()
    output = value["operations"][0]["outputs"][0]
    if bad == "bare_id":
        value["operations"][0]["outputs"] = ["c5"]
    elif bad == "unknown_support":
        output["supporting_claim_ids"] = ["unknown"]
    elif bad == "empty_support":
        output["supporting_claim_ids"] = []
    elif bad == "extra":
        output["approved"] = True
    else:
        output["name"] = " "
    with pytest.raises(AnalysisError):
        parse_method_flow(value, claim_ids={"c5"})


def test_wrong_product_does_not_inherit_a_true_action_decision() -> None:
    flow = parse_method_flow(proposal(), claim_ids={"c5"})
    checked = apply_method_decisions(
        flow, facts(), decisions("unsupported"), source_url=artifact().source.url
    )
    with pytest.raises(AnalysisError, match="roles"):
        reviewed_method_flow(checked, facts(), source_url=artifact().source.url)
    assert facts()[0].is_publishable()
