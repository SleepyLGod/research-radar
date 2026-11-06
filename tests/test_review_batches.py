"""Budgeted review batches retain the global checklist and exact source evidence."""

import copy
import json
from dataclasses import replace

import pytest
from test_review_evidence_selection import mixed_claim, selection_reply
from test_review_presentation import expand_presentation
from test_review_targets import SchemaReviewer

from research_radar.analysis import review
from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
from research_radar.analysis.reader_input import ReaderContextBudget, ReaderInputError
from research_radar.analysis.reading_review import paragraph_is_public
from research_radar.analysis.review import model_review, model_review_publishable_claims
from research_radar.analysis.review_targets import ReviewTargets, build_review_targets
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, Claim, ClaimStatus, SourceCandidate, SourceType


def _inputs() -> tuple[list[Claim], dict]:
    first = mixed_claim()
    second = copy.deepcopy(first)
    second.metadata["paper_reading"]["claim_id"] = "c48"
    second = replace(second, text="Independent assertion. " * 250)
    return [first, second], {"full_sources": [{"reading_packet": "Full source " * 400}],
        "paragraphs": [{"paragraph_id": "context-only", "text": "K=3 elsewhere in the report.",
                       "supporting_claim_ids": ["c48"]}]}


def _context(content: str) -> dict:
    records = content.split("SHARED SOURCE RECORDS (JSON):\n")[1].split(
        "\nFULL SOURCE CONTEXT (JSON):\n")[0]
    source = content.split("FULL SOURCE CONTEXT (JSON):\n")[1].split(
        "\nREVIEW TARGETS (JSON):\n")[0]
    return expand_presentation({"source_records": json.loads(records),
                                "source_context": json.loads(source), "targets": {}})


class LimitedReviewer(SchemaReviewer):
    reader_contexts = {"offline": ReaderContextBudget(20_900, 1000, 1000)}


def test_oversize_review_splits_targets_without_losing_full_context_or_evidence() -> None:
    claims, context = _inputs()
    # The extra prose is context, not a review target in this factual pass.
    paragraphs = context.pop("paragraphs")
    context["candidate_context"] = paragraphs
    provider = LimitedReviewer()
    text = json.dumps(context)
    expected = build_review_targets(claims, text)
    reviewed, _, raw, _ = model_review(claims, provider, model="offline", reading_context=text)
    assert len(provider.requests) == 2
    offered = {}
    for messages, _, targets in provider.requests:
        assert not offered.keys() & targets.keys()
        offered.update(targets)
        assert _context(messages[-1].content)["source_context"] == context
    assert offered == expand_presentation(expected.presentation(text))["targets"]
    assert all(claim.status == ClaimStatus.SUPPORTED for claim in reviewed)
    assert len(json.loads(raw)["structured_review"]["receipts"]) == 2


def test_all_batches_are_budget_checked_before_first_request() -> None:
    claims, context = _inputs()
    del context["paragraphs"]
    claims[-1] = replace(claims[-1], text="Indivisible assertion. " * 2000)
    provider = LimitedReviewer()
    with pytest.raises(ReaderInputError, match="reader_context_exceeded"):
        model_review(claims, provider, model="offline", reading_context=json.dumps(context))
    assert provider.requests == []


def test_packing_reuses_shared_table_across_nonadjacent_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = [replace(mixed_claim(), text=f"Assertion {i}.") for i in range(4)]
    contract = build_review_targets(claims, "")
    ids = list(contract.targets)
    groups = {identity: i % 2 for i, identity in enumerate(ids)}
    real_scope = type(contract).context_for_batch

    def scope(batch: ReviewTargets, context: dict) -> dict:
        result = real_scope(batch, context)
        result["table_sources"] = {str(groups[key]): {"caption": "Table " + str(groups[key]),
            "cells": [{"value": str(groups[key]) * 5200}]} for key in batch.targets}
        return result

    monkeypatch.setattr(type(contract), "context_for_batch", scope)

    class Provider(SchemaReviewer):
        reader_contexts = {"offline": ReaderContextBudget(24_500, 1000, 1000)}

    raw = json.dumps({"full_sources": [{"reading_packet": "Original source. " * 360}],
                      "table_sources": {str(i): {"cells": [{"value": str(i) * 5200}]}
                                        for i in range(2)}})
    batches = review._plan_review_batches(contract, raw, Provider(), model="offline",
                                          topic_id=None, queries=None)
    assert [list(b.targets.targets) for b in batches] == [ids[::2], ids[1::2]]
    assert all(b.targets == contract.select(set(b.targets.targets)) for b in batches)


def test_batch_keeps_cross_paragraph_scope_and_complete_referenced_table() -> None:
    claim = mixed_claim()
    source = claim.evidence[0].source_url
    identity = claim.metadata["paper_reading"]["claim_id"]
    paragraphs = [
        {"paragraph_id": "p1.experiment_interpretation.1", "text": "主实验中准确率更高。",
         "source_url": source, "supporting_claim_ids": [identity],
         "required_covered_claim_ids": [identity], "supporting_claims": []},
        {"paragraph_id": "p1.experiment_interpretation.2", "text": "只比较 K=3 下的宏平均。",
         "source_url": source, "supporting_claim_ids": [identity], "supporting_claims": []},
    ]
    context = {"full_sources": [{"source_url": source, "reading_packet": "Whole original."}],
               "paragraphs": paragraphs, "required_coverage": {source: {"experiment": [identity]}}}
    contract = build_review_targets([claim], json.dumps(context))
    key, = [key for key, value in contract.targets.items()
            if value.get("paragraph_id") == paragraphs[0]["paragraph_id"]]
    subset = contract.select({key})

    def tables(value: object) -> set[str]:
        if isinstance(value, dict):
            return {value["table_id"]} if "table_id" in value else set().union(
                *(tables(v) for v in value.values()))
        return set().union(*(tables(v) for v in value)) if isinstance(value, list) else set()
    table, = tables(subset.targets)
    context["table_sources"] = {table: {"headers": ["AA", "A.I.C."], "footnote": "macro-average"},
                                "unrelated": {"headers": ["Other metric"]}}
    scoped = subset.context_for_batch(context)
    assert scoped["full_sources"] == context["full_sources"]
    assert scoped["required_coverage"] == context["required_coverage"]
    assert [row["text"] for row in scoped["paragraphs"]] == [row["text"] for row in paragraphs]
    assert scoped["table_sources"] == {table: context["table_sources"][table]}
    expanded = expand_presentation(subset.presentation(json.dumps(scoped)))
    assert expanded["targets"] == subset.targets
    assert subset.evidence_bindings[key] == contract.evidence_bindings[key]


def test_later_paragraph_approval_cannot_rescue_rejected_fact_from_earlier_batch() -> None:
    from test_publication_composition import candidates

    reading, claim = candidates()
    reading = replace(reading, reader_explanation=ReaderExplanation(core_thesis=[
        ReaderExplanationParagraph("The experiment used 12 simulated users.", ["c1"])]))
    artifact = Artifact(SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "offline"),
                        claim.evidence[0].quote + "\n" + "Source text. " * 400)

    class Reviewer(SchemaReviewer):
        reader_contexts = {"offline": ReaderContextBudget(17_000, 1000, 1000)}

        def complete_with_schema(self, *args, **kwargs):
            reply = super().complete_with_schema(*args, **kwargs)
            payload = json.loads(reply.content)
            for key, target in self.requests[-1][2].items():
                if target["kind"] == "fact":
                    payload["decisions"][key]["status"] = "unsupported"
            return replace(reply, content=json.dumps(payload))

    provider = Reviewer()
    result = model_review_publishable_claims([claim], provider, model="offline", readings=[reading],
                                            artifacts=[artifact], require_fact_receipts=False)
    assert [{t["kind"] for t in request[2].values()} for request in provider.requests] == [
        {"fact"}, {"paragraph"}]
    assert not result.claims[0].is_publishable()
    assert not paragraph_is_public(result.readings[0].reader_explanation.core_thesis[0],
                                   result.claims, source_url=reading.source_url)


@pytest.mark.parametrize("defect", ["missing_batch", "duplicate_batch", "changed_binding"])
def test_merge_requires_an_exact_disjoint_cover(defect: str) -> None:
    claims, _ = _inputs()
    contract = build_review_targets(claims, "")
    batches = [contract.select({key}) for key in contract.targets]
    receipts = [json.loads(batch.normalize(json.dumps(selection_reply(batch))))
                for batch in batches]
    if defect == "missing_batch":
        receipts.pop()
    elif defect == "duplicate_batch":
        receipts[1] = receipts[0]
    else:
        bindings, = receipts[1]["structured_review"]["evidence_bindings"].values()
        bindings[next(iter(bindings))] = "different-source-proof"
    with pytest.raises(AnalysisError):
        contract.assemble_batches(receipts)


@pytest.mark.parametrize("bad", ["missing", "unknown", "duplicate", "evidence"])
def test_invalid_second_batch_never_produces_merged_decisions(bad: str) -> None:
    class Reviewer(LimitedReviewer):
        def complete_with_schema(self, *args, **kwargs):
            if len(self.requests) == 1:
                self.bad = bad
            reply = super().complete_with_schema(*args, **kwargs)
            if self.bad == "evidence":
                payload = json.loads(reply.content)
                next(iter(payload["decisions"].values()))["evidence_refs"] = ["foreign"]
                return replace(reply, content=json.dumps(payload))
            return reply

    claims, context = _inputs()
    del context["paragraphs"]
    provider = Reviewer()
    with pytest.raises(AnalysisError) as error:
        model_review(claims, provider, model="offline", reading_context=json.dumps(context))
    assert not isinstance(error.value, ReaderInputError)
    assert len(provider.requests) == 2
