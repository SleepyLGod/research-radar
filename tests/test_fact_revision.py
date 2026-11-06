"""Bounded source-selected amendments stay separate from factual approval."""

import copy
import json
from dataclasses import replace

import pytest
from method_contract_controls import control
from reader_fixtures import OFFLINE_READER_CONTEXTS
from test_review_targets import SchemaReviewer

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.paper_reading import parse_paper_reading, validate_paper_reading
from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
from research_radar.analysis.source_references import build_source_index
from research_radar.exceptions import AnalysisError


class Reviewer(SchemaReviewer):
    """The initial uncertain decision and subsequent approvals are explicit offline controls."""

    def __init__(self, status="needs_review"):
        super().__init__()
        self.initial_status = status

    def complete_with_schema(self, messages, *, model, response_schema):
        first = not self.requests
        result = super().complete_with_schema(messages, model=model,
                                             response_schema=response_schema)
        if first:
            data = json.loads(result.content)
            for key, target in self.requests[-1][2].items():
                if target["kind"] == "fact" and target["claim_id"] == "m1":
                    data["decisions"][key].update(status=self.initial_status,
                        reason="Offline control: the proposed method detail is incomplete.")
            return replace(result, content=json.dumps(data))
        return result


class Reviser:
    """Return a declared amendment using only an offered source block."""

    name = "offline-reviser"
    supports_response_schema = True
    reader_contexts = OFFLINE_READER_CONTEXTS

    def __init__(self, artifact, unit, bad=""):
        self.artifact, self.unit, self.bad = artifact, unit, bad
        self.requests = []

    def complete_with_schema(self, messages, *, model, response_schema, **kwargs):
        self.requests.append((messages, response_schema))
        quote = self.unit["evidence"][0]["quote"]
        start = self.artifact.text.index(quote)
        references = build_source_index(self.artifact).references_for_span(
            start, start + len(quote))
        item = {"text": self.unit["text"], "evidence": references,
                "reason": "Offline source-bound amendment, not model acceptance."}
        payload = {"revisions": {self.unit["claim_id"]: item}}
        if self.bad == "declined":
            item.update(text=None, evidence=[], reason="No supported amendment offered.")
        elif self.bad == "missing":
            payload["revisions"] = {}
        elif self.bad == "unknown":
            payload["revisions"] = {"invented": item}
        elif self.bad == "foreign":
            item["evidence"] = [{"source_id": "b0000000000000000:1"}]
        elif self.bad == "empty":
            item["text"] = " "
        elif self.bad == "extra":
            item["status"] = "supported"
        elif self.bad == "duplicate":
            row = json.dumps(item)
            return ModelResponse('{"revisions":{"m1":' + row + ',"m1":' + row + '}}', model)
        elif self.bad == "transport":
            raise AnalysisError("Offline transport failure; do not retry.")
        content = json.dumps(payload)
        if "validate_response" in kwargs:
            kwargs["validate_response"](content)
        return ModelResponse(content, model)


def setup_review(status="needs_review"):
    """Start with real shared extraction/review code and an editorial model double."""
    artifact, payload, _ = control("memconflict")
    complete = copy.deepcopy(payload["deep_readings"]["claim_units"][0])
    payload["deep_readings"]["claim_units"][0]["text"] = (
        "Each user is initialized from a persona seed.")
    reading = parse_paper_reading(json.dumps(payload), artifact)
    claims, _ = validate_paper_reading(reading, artifact)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    reviewer = Reviewer(status)
    initial = review_publication_facts(claims, reviewer, model="offline",
                                     readings=[reading], artifacts=[artifact])
    return artifact, initial, reviewer, Reviser(artifact, complete)


def revise(initial, reviser, reviewer, artifact):
    from research_radar.analysis.fact_revision import revise_publication_facts

    return revise_publication_facts(initial, reviser, model="offline", verifier=reviewer,
                                    verifier_model="offline", artifacts=[artifact])


def test_amended_fact_and_dependencies_are_rechecked_without_mutating_original() -> None:
    artifact, initial, reviewer, reviser = setup_review()
    original = copy.deepcopy(initial)

    result = revise(initial, reviser, reviewer, artifact)

    assert len(reviser.requests) == 1
    assert len(reviewer.requests) == 2
    assert initial == original
    amended = next(c for c in result.claims if c.metadata["paper_reading"]["claim_id"] == "m1")
    assert reviser.unit["text"] in amended.text
    assert fact_is_reviewed(amended)
    pending = reviewer.requests[-1][2].values()
    assert {t["claim_id"] for t in pending if t["kind"] == "fact"} == {"m1"}
    assert any(t["kind"] in {"operation", "link"} for t in pending)
    assert json.loads(result.raw_feedback)["structured_review"]["reused_target_ids"]
    assert result.revision_audit["status"] == "reviewed"
    # No second automatic amendment pass can be triggered on the returned attempt.
    assert revise(result, reviser, reviewer, artifact) is result
    assert len(reviser.requests) == 1


def test_complete_or_explicitly_rejected_facts_do_not_trigger_amendment() -> None:
    for status in ("supported", "unsupported"):
        artifact, initial, reviewer, reviser = setup_review(status)
        result = revise(initial, reviser, reviewer, artifact)
        assert result is initial
        assert not reviser.requests
        assert len(reviewer.requests) == 1


def test_declined_amendment_keeps_uncertainty_without_another_review_call() -> None:
    artifact, initial, reviewer, reviser = setup_review()
    reviser.bad = "declined"
    result = revise(initial, reviser, reviewer, artifact)
    assert result.claims == initial.claims
    assert result.revision_audit["status"] == "unresolved"
    assert result.revision_audit["attempts"][0]["decisions"]["m1"]["reason"] == (
        "No supported amendment offered.")
    assert len(reviser.requests) == len(reviewer.requests) == 1


@pytest.mark.parametrize("bad", ["missing", "unknown", "foreign", "empty", "extra",
                                 "duplicate", "transport"])
def test_invalid_or_failed_amendment_is_not_repaired_retried_or_approved(bad: str) -> None:
    artifact, initial, reviewer, reviser = setup_review()
    original = copy.deepcopy(initial)
    reviser.bad = bad
    with pytest.raises(AnalysisError) as failed:
        revise(initial, reviser, reviewer, artifact)
    assert initial == original
    assert len(reviser.requests) == 1
    assert len(reviewer.requests) == 1
    assert failed.value.fact_revision_audit["status"] == "failed"


def test_changed_full_source_stops_before_revision_or_receipt_reuse() -> None:
    artifact, initial, reviewer, reviser = setup_review()
    with pytest.raises(AnalysisError, match="source"):
        revise(initial, reviser, reviewer, replace(artifact, text=artifact.text + " changed"))
    assert not reviser.requests
    assert len(reviewer.requests) == 1


def test_amendment_cannot_retry_an_uncertain_second_decision(monkeypatch) -> None:
    artifact, initial, reviewer, reviser = setup_review()
    original_review = reviewer.complete_with_schema

    def uncertain(messages, *, model, response_schema):
        response = original_review(messages, model=model, response_schema=response_schema)
        rows = json.loads(response.content)
        for key, target in reviewer.requests[-1][2].items():
            if target["kind"] == "fact" and target["claim_id"] == "m1":
                rows["decisions"][key].update(status="needs_review",
                    reason="Offline control: the amendment remains uncertain.")
        return replace(response, content=json.dumps(rows))

    monkeypatch.setattr(reviewer, "complete_with_schema", uncertain)
    result = revise(initial, reviser, reviewer, artifact)
    fact = next(c for c in result.claims if c.metadata["paper_reading"]["claim_id"] == "m1")
    assert not fact.is_publishable()
    assert not fact_is_reviewed(fact)
    assert revise(result, reviser, reviewer, artifact) is result
    assert len(reviser.requests) == 1 and len(reviewer.requests) == 2


def test_complete_revision_budget_is_checked_before_any_new_call() -> None:
    artifact, initial, reviewer, reviser = setup_review()
    reviser.reader_contexts = {}
    with pytest.raises(AnalysisError, match="reader_context_unknown") as failed:
        revise(initial, reviser, reviewer, artifact)
    assert not reviser.requests
    assert len(reviewer.requests) == 1
    assert failed.value.fact_revision_audit["status"] == "failed"


def test_invalid_amendment_does_not_enter_the_existing_model_cache(tmp_path) -> None:
    from research_radar.analysis.model_cache import CachedLLMProvider

    artifact, initial, reviewer, reviser = setup_review()
    reviser.bad = "unknown"
    cached = CachedLLMProvider(reviser, cache_dir=tmp_path, task_name="deep_reading")
    with pytest.raises(AnalysisError):
        revise(initial, cached, reviewer, artifact)
    assert len(reviser.requests) == 1 and len(reviewer.requests) == 1
    assert not list(tmp_path.rglob("*.json"))


def test_old_local_numeric_rejections_are_rechecked_without_rewriting_the_reader() -> None:
    from test_lotus_numeric_notation import SAVED
    from test_paper_reading import _claim_units_fixture

    from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType

    units = [{"claim_id": identity, "section": "experiment", "claim_kind": "fact",
              "text": SAVED["cases"][identity]["text"],
              "evidence": [{"quote": SAVED["cases"][identity]["quote"]}],
              "publishable_default": True} for identity in ("c32", "c48")]
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    payload["deep_readings"]["claim_units"] = units
    artifact = Artifact(SourceCandidate("LOTUS v3", SAVED["source_url"], SourceType.PAPER,
                                        "offline"), "\n\n".join(u["evidence"][0]["quote"]
                                                                   for u in units))
    reading = parse_paper_reading(json.dumps(payload), artifact)
    fresh, _ = validate_paper_reading(reading, artifact)
    # Reproduce stored pre-fix local failures, not negative model decisions.
    old = [replace(c, status=ClaimStatus.UNSUPPORTED, metadata={**c.metadata,
        "anchor_resolution": {"status": "failed", "reason": "numeric anchor missing claim values"}})
        for c in fresh]
    reviewer = Reviewer()
    initial = review_publication_facts(old, reviewer, model="offline", readings=[reading],
                                       artifacts=[artifact])
    assert not reviewer.requests
    reviser = Reviser(artifact, units[0])
    result = revise(initial, reviser, reviewer, artifact)
    assert not reviser.requests
    assert len(reviewer.requests) == 1
    assert all(fact_is_reviewed(c) for c in result.claims)
    assert all(c.status == ClaimStatus.UNSUPPORTED for c in initial.claims)
    assert result.readings[0].claim_units == initial.readings[0].claim_units


def test_minimized_lotus_amendments_reach_chinese_report_with_explicit_evidence(
    tmp_path, monkeypatch,
) -> None:
    from test_lotus_numeric_notation import SAVED
    from test_method_contract_pipeline import Reading, Writing
    from test_paper_reading import _claim_units_fixture

    from research_radar.config import parse_config
    from research_radar.models import Artifact, SourceCandidate, SourceType
    from research_radar.pipeline import paper

    # Four saved assertions with human-authored amendments/writing, not a full live report.
    ids = ["c8", "c32", "c35", "c48"]
    artifact = Artifact(SourceCandidate("LOTUS v3", SAVED["source_url"], SourceType.PAPER,
        "offline"), "\n\n".join(SAVED["cases"][key]["quote"] for key in ids))
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    body = payload["deep_readings"]
    body["title"] = "LOTUS offline amendment control"
    for key in ("area_context", "problem_solution", "related_work", "limitations",
                "critical_assessment"):
        body[key]["evidence"] = [{"quote": SAVED["cases"]["c8"]["quote"]}]
    body["claim_units"] = [{"claim_id": key,
        "section": "solution" if key == "c8" else "experiment", "claim_kind": "fact",
        "text": SAVED["cases"][key]["text"],
        "evidence": [{"quote": SAVED["cases"][key]["quote"]}], "publishable_default": True,
        "method": {"kind": "operation", "from_claim_id": None, "to_claim_id": None}
                  if key == "c8" else None} for key in ids]
    body["method_flow"] = {"operations": [{"scope": "Threshold dispatch",
        "operation_claim_id": "c8", "inputs": [], "outputs": [], "conditions": []}],
        "links": [], "gaps": []}
    body["evaluation_context"] = {"data_construction": ["c32"], "available_inputs": [],
                                  "outcome_measurement": ["c35"]}
    body["reader_explanation"] = {}
    revised_text = ("The filter optimizer accepts tuples at or above the upper proxy threshold, "
        "rejects tuples at or below the lower threshold, and sends intermediate tuples "
        "to the oracle model.")
    chinese_claims = [
        "Solution: 代理得分达到或超过上阈值时接受，达到或低于下阈值时拒绝，中间区间交给 oracle。",
        "Experiment: BioDEX 语料有 65,000 篇生物医学文章和 24,000 个可能的药物反应标签。",
        "Experiment: BioDEX 的结果指标是 rank-precision at 5 和 rank-precision at 10。",
        "Experiment: 作者报告，两项排序任务中 quick-select top-k 的执行时间比 heap top-k 少 "
        "16% 至 32%；原文未将区间端点对应到具体任务。",
    ]
    chinese = {"claims": [{"claim_id": key, "text": text}
                          for key, text in zip(ids, chinese_claims, strict=True)],
        "reader_explanation": {"solution_walkthrough": [{"text": chinese_claims[0][10:],
            "supporting_claim_ids": ["c8"]}], "experiment_interpretation": [{
                "text": " ".join(text[12:] for text in chinese_claims[1:]),
                "supporting_claim_ids": ["c32", "c35", "c48"]}]}}
    order = []

    class AmendingReader(Reading):
        def complete_with_schema(self, messages, *, model, response_schema):
            if "revisions" not in response_schema["properties"]:
                return super().complete_with_schema(messages, model=model,
                                                    response_schema=response_schema)
            order.append("amend")
            index = build_source_index(artifact)
            proposed = {}
            for identity in response_schema["properties"]["revisions"]["properties"]:
                quotes = [SAVED["cases"][identity]["quote"]]
                if identity == "c35":
                    quotes.append(SAVED["cases"]["c32"]["quote"])
                refs = []
                for quote in quotes:
                    start = artifact.text.index(quote)
                    refs.extend(index.references_for_span(start, start + len(quote)))
                proposed[identity] = {"text": revised_text if identity == "c8"
                    else SAVED["cases"][identity]["text"], "evidence": refs,
                    "reason": "Editorial control preserves boundaries and explicit topic identity."}
            return ModelResponse(json.dumps({"revisions": proposed}), model)

    class Reviewing(SchemaReviewer):
        def complete_with_schema(self, messages, *, model, response_schema):
            first = not self.requests
            order.append("review")
            response = super().complete_with_schema(messages, model=model,
                                                    response_schema=response_schema)
            if first:
                rows = json.loads(response.content)
                for key, target in self.requests[-1][2].items():
                    if target["kind"] == "fact" and target["claim_id"] == "c8":
                        rows["decisions"][key].update(status="needs_review",
                            reason=SAVED["cases"]["c8"]["review_reason"])
                return replace(response, content=json.dumps(rows))
            return response

    monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
    config = parse_config({"topics": [{"id": "lotus", "queries": ["semantic operators"]}]})
    run = paper.run_paper(tmp_path, config, "lotus", artifact.source.url,
        AmendingReader(payload, order), model="offline", verifier=Reviewing(),
        verifier_model="offline", localizer=Writing(chinese, order),
        localization_model="offline", language="zh")
    assert order == ["reader", "review", "amend", "review", "writer", "review"]
    report = (run / "paper.md").read_text()
    assert "达到或超过上阈值" in report
    assert "65,000" in report and "24,000" in report
    assert "16%" in report and "32%" in report
    audit = json.loads((run / "fact_revision.json").read_text())
    assert audit["attempts"][0]["accepted_candidate_ids"] == ["c8", "c35"]
    assert audit["initial_readings"][0]["claim_units"][0]["text"] == SAVED["cases"]["c8"]["text"]


def test_initial_batched_receipts_and_nested_reuse_keep_original_provenance() -> None:
    from research_radar.analysis.review_targets import ReviewTargets

    artifact, initial, reviewer, reviser = setup_review()
    saved = json.loads(initial.raw_feedback)["structured_review"]
    contract = ReviewTargets(saved["targets"], saved["evidence_bindings"])
    answers = json.loads(saved["raw_response"])["decisions"]
    keys = list(contract.targets)
    groups = [keys[:len(keys) // 2], keys[len(keys) // 2:]]
    receipts = [json.loads(contract.select(set(group)).normalize(json.dumps({
        "decisions": {key: answers[key] for key in group}}))) for group in groups]
    initial = replace(initial, raw_feedback=json.dumps(contract.assemble_batches(receipts)))
    result = revise(initial, reviser, reviewer, artifact)
    assert len(reviser.requests) == 1 and len(reviewer.requests) == 2
    current = json.loads(result.raw_feedback)
    assert current["structured_review"]["receipts"][0] == json.loads(initial.raw_feedback)
    target = ReviewTargets(current["structured_review"]["targets"],
                           current["structured_review"]["evidence_bindings"])
    assert target.reuse_supported(current)
    for defect in ("status", "duplicate_batch", "missing_batch"):
        corrupted = copy.deepcopy(json.loads(initial.raw_feedback))
        if defect == "status":
            corrupted["decisions"][0]["status"] = "unsupported"
        elif defect == "duplicate_batch":
            corrupted["structured_review"]["receipts"].append(receipts[0])
        else:
            corrupted["structured_review"]["receipts"].pop()
        with pytest.raises(AnalysisError):
            contract.reuse_supported(corrupted)


def test_source_bound_table_amendment_reaches_review_without_local_promotion() -> None:
    from reader_fixtures import current_source_anchors
    from test_paper_reading import _claim_units_fixture
    from test_saved_memguide_evidence import DATA

    from research_radar.analysis.fact_revision import _local_candidates
    from research_radar.analysis.figures import PdfPageBbox, PdfTextWord
    from research_radar.analysis.paper_reading import EvaluationContext
    from research_radar.evidence.pdf_tables import attach_table_evidence
    from research_radar.models import Artifact, SourceCandidate, SourceType, dataclass_to_dict

    case = next(c for c in DATA["claims"] if c["claim_id"] == "c51")
    boxes = {p["page"]: PdfPageBbox(p["width"], p["height"],
        [PdfTextWord(*w) for w in p["words"]]) for p in DATA["pages"]}
    artifact = Artifact(SourceCandidate(DATA["title"], DATA["source_url"], SourceType.PAPER,
        "offline"), "".join(p["text"] for p in DATA["pages"]),
        "tests/fixtures/method_flow/memguide_evidence_rejections.json", "application/pdf")
    artifact = attach_table_evidence(artifact, page_reader=lambda _path, n: boxes.get(n))
    payload = json.loads(_claim_units_fixture(["Offline fixture."]))
    payload["deep_readings"]["claim_units"] = [{"claim_id": "c51", "section": "experiment",
        "claim_kind": "fact", "text": case["text"], "evidence": case["evidence"],
        "publishable_default": True}]
    reading = parse_paper_reading(json.dumps(payload), artifact)
    unit = replace(reading.claim_units[0],
        evidence=current_source_anchors(artifact, case["evidence"]))
    reading = replace(reading, claim_units=[unit],
        evaluation_context=EvaluationContext(claim_references={
            "data_construction": ["c51"], "available_inputs": [], "outcome_measurement": []}))
    class TableReviewer(SchemaReviewer):
        def complete_with_schema(self, messages, *, model, response_schema):
            first = not self.requests
            reply = super().complete_with_schema(messages, model=model,
                                                response_schema=response_schema)
            if first:
                rows = json.loads(reply.content)
                for key, target in self.requests[-1][2].items():
                    if target["kind"] == "fact":
                        rows["decisions"][key].update(status="needs_review",
                            reason="Offline control requests a clarified table assertion.")
                return replace(reply, content=json.dumps(rows))
            return reply

    reviewer = TableReviewer()
    initial = review_publication_facts(list(_local_candidates(reading, artifact).values()),
        reviewer, model="offline", readings=[reading], artifacts=[artifact])
    amendment = dataclass_to_dict(replace(unit,
        text=unit.text.replace("the paper reports", "the authors report")))
    reviser = Reviser(artifact, amendment)
    result = revise(initial, reviser, reviewer, artifact)
    assert len(reviser.requests) == 1 and len(reviewer.requests) == 2
    assert result.revision_audit["attempts"][0]["accepted_candidate_ids"] == ["c51"]
