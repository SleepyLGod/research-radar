"""Method approvals match explicit source-scoped operation and relation identities."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_radar.analysis.method_flow import (
    apply_method_decisions,
    method_flow_payload,
    parse_method_flow,
    reviewed_method_flow,
)
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

URL = "http://arxiv.org/abs/2605.20926v1"
SAVED = json.loads(
    (
        Path(__file__).parent / "fixtures/method_flow/unidentified_operation_decisions.json"
    ).read_text()
)


def proposal() -> dict:
    """An explicit editorial control, not a repaired real model answer."""
    return {
        "operations": [
            {
                "scope": "Build records",
                "operation_claim_id": "c3",
                "inputs": [],
                "outputs": [{"name": "records", "supporting_claim_ids": ["c3"]}],
                "conditions": [],
            },
            {
                "scope": "Index records",
                "operation_claim_id": "c4",
                "inputs": [{"name": "records", "supporting_claim_ids": ["c4"]}],
                "outputs": [{"name": "index", "supporting_claim_ids": ["c4"]}],
                "conditions": [],
            },
        ],
        "links": [{"from_claim_id": "c3", "to_claim_id": "c4", "supporting_claim_ids": ["c5"]}],
        "gaps": [],
    }


def facts() -> list[Claim]:
    return [
        Claim(
            text,
            ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(URL, text)],
            metadata={"paper_reading": {"claim_id": identity}},
        )
        for identity, text in [
            ("c3", "The builder produces records."),
            ("c4", "The indexer consumes records and produces an index."),
            ("c5", "The builder's records are then passed to the indexer."),
        ]
    ]


def decisions() -> dict:
    return {
        "method_operation_decisions": [
            {
                "source_url": URL,
                "operation_claim_id": identity,
                "status": "supported",
                "reason": "Offline explicitly identified operation control.",
            }
            for identity in ("c3", "c4")
        ],
        "method_link_decisions": [
            {
                "source_url": URL,
                "from_claim_id": "c3",
                "to_claim_id": "c4",
                "status": "supported",
                "reason": "Offline explicit dependency control.",
            }
        ],
    }


def apply(payload: dict):
    return apply_method_decisions(
        parse_method_flow(proposal(), claim_ids={"c3", "c4", "c5"}),
        facts(),
        payload,
        source_url=URL,
    )


def test_explicit_operation_decisions_match_ids_not_list_order() -> None:
    payload = decisions()
    payload["method_operation_decisions"].reverse()
    before = copy.deepcopy(payload)
    checked = apply(payload)
    assert reviewed_method_flow(checked, facts(), source_url=URL) == proposal()
    assert all(op.review.status == "supported" for op in checked.operations)
    assert payload == before
    assert all("review" not in op for op in method_flow_payload(checked)["operations"])


@pytest.mark.parametrize("key", ["method_flow_decisions", "method_operation_decisions"])
def test_original_ten_unidentified_decisions_never_become_operation_approvals(key: str) -> None:
    payload = decisions()
    payload.pop("method_operation_decisions")
    payload[key] = copy.deepcopy(SAVED["method_flow_decisions"])
    before = copy.deepcopy(payload)
    checked = apply(payload)
    with pytest.raises(AnalysisError, match="roles|operation"):
        reviewed_method_flow(checked, facts(), source_url=URL)
    assert payload == before
    assert all(op.review.status == "needs_review" for op in checked.operations)


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "duplicate",
        "foreign",
        "unknown",
        "extra_unknown",
        "missing_id",
        "wrong_type",
        "unsupported",
        "needs_review",
        "invalid_status",
        "blank_reason",
        "extra_field",
        "not_array",
    ],
)
def test_incomplete_or_ambiguous_operation_decisions_cannot_authorize_writing(bad: str) -> None:
    payload = decisions()
    rows = payload["method_operation_decisions"]
    if bad == "missing":
        rows.pop()
    elif bad == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif bad == "foreign":
        rows[0]["source_url"] = "https://other.test/paper"
    elif bad == "unknown":
        rows[0]["operation_claim_id"] = "unknown"
    elif bad == "extra_unknown":
        rows.append({**rows[0], "operation_claim_id": "unknown"})
    elif bad == "missing_id":
        rows[0].pop("operation_claim_id")
    elif bad == "wrong_type":
        rows[0]["operation_claim_id"] = 3
    elif bad in ("unsupported", "needs_review", "invalid_status"):
        rows[0]["status"] = bad
    elif bad == "blank_reason":
        rows[0]["reason"] = " "
    elif bad == "extra_field":
        rows[0]["approved"] = True
    else:
        payload["method_operation_decisions"] = {"c3": rows[0]}
    with pytest.raises(AnalysisError, match="roles|operation"):
        reviewed_method_flow(apply(payload), facts(), source_url=URL)
    assert all(c.is_publishable() for c in facts())


@pytest.mark.parametrize("bad", ["missing", "duplicate", "reversed", "unknown", "extra_field"])
def test_identified_operations_do_not_override_invalid_relation_decisions(bad: str) -> None:
    payload = decisions()
    rows = payload["method_link_decisions"]
    if bad == "missing":
        rows.clear()
    elif bad == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif bad == "reversed":
        rows[0]["from_claim_id"], rows[0]["to_claim_id"] = "c4", "c3"
    elif bad == "unknown":
        rows.append({**rows[0], "to_claim_id": "unknown"})
    else:
        rows[0]["approved"] = True
    with pytest.raises(AnalysisError, match="connection"):
        reviewed_method_flow(apply(payload), facts(), source_url=URL)


def test_operation_approval_cannot_be_swapped_or_survive_changed_support() -> None:
    checked = apply(decisions())
    first, second = checked.operations
    swapped = replace(checked, operations=[replace(first, review=second.review), second])
    with pytest.raises(AnalysisError, match="roles|operation"):
        reviewed_method_flow(swapped, facts(), source_url=URL)
    changed = facts()
    changed[0] = replace(changed[0], text="The builder produces unrelated data.")
    with pytest.raises(AnalysisError, match="roles|operation"):
        reviewed_method_flow(checked, changed, source_url=URL)


def test_same_operation_id_from_another_source_cannot_substitute_a_missing_decision() -> None:
    payload = decisions()
    foreign = {**payload["method_operation_decisions"][0], "source_url": "https://other.test/paper"}
    payload["method_operation_decisions"].append(foreign)
    assert reviewed_method_flow(apply(payload), facts(), source_url=URL) == proposal()
    payload["method_operation_decisions"].pop(0)
    with pytest.raises(AnalysisError, match="roles|operation"):
        reviewed_method_flow(apply(payload), facts(), source_url=URL)


@pytest.mark.parametrize("missing_operation", [False, True])
def test_first_final_review_checks_each_operation_before_authorizing_prose(
    missing_operation: bool,
) -> None:
    from test_method_flow import extract, fact_provider
    from test_publication_composition import Composer
    from test_reader_source_operations import operations

    from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
    from research_radar.analysis.review import model_review_publishable_claims

    artifact, reading, claims, data = extract("memguide")
    flow = parse_method_flow(
        operations("memguide"), claim_ids={c["claim_id"] for c in data["claim_units"]}
    )
    paragraphs = data["writer_control"]["reader_explanation"]["solution_walkthrough"]
    reading = replace(
        reading,
        method_flow=flow,
        reader_explanation=ReaderExplanation(
            solution_walkthrough=[ReaderExplanationParagraph(**p) for p in paragraphs]
        ),
    )
    payload = fact_provider(data).payloads[0]
    payload["explanation_decisions"] = [
        {
            "paragraph_id": f"p1.solution_walkthrough.{i}",
            "status": "supported",
            "reason": "Offline exact-prose control.",
            "covered_claim_ids": p["supporting_claim_ids"],
        }
        for i, p in enumerate(paragraphs, 1)
    ]
    if missing_operation:
        payload["method_operation_decisions"].pop()
    provider = Composer(payload)
    if missing_operation:
        with pytest.raises(AnalysisError, match="operation"):
            model_review_publishable_claims(
                claims, provider, model="offline", readings=[reading], artifacts=[artifact]
            )
    else:
        result = model_review_publishable_claims(
            claims, provider, model="offline", readings=[reading], artifacts=[artifact]
        )
        assert reviewed_method_flow(
            result.readings[0].method_flow, result.claims, source_url=artifact.source.url
        ) == operations("memguide")
    assert len(provider.requests) == 1
