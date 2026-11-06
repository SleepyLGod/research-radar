"""A well-formed abstention is not malformed JSON or permission to publish its dependants."""

import json
from dataclasses import replace

import pytest
from test_publication_composition import candidates
from test_review_evidence_selection import mixed_claim, selection_reply
from test_review_targets import SchemaReviewer

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import ReaderExplanation, ReaderExplanationParagraph
from research_radar.analysis.review import model_review_publishable_claims, review_publication_facts
from research_radar.analysis.review_targets import build_review_targets
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType


@pytest.mark.parametrize("status", ["needs_review", "unsupported", "speculative"])
def test_well_formed_nonpublic_decision_may_select_no_evidence(status):
    contract = build_review_targets([mixed_claim()], "")
    payload = selection_reply(contract, status=status)
    decision = next(iter(payload["decisions"].values()))
    decision["evidence_refs"] = []
    raw = json.dumps(payload, indent=2)
    result = json.loads(contract.normalize(raw))
    assert result["decisions"][0]["status"] == status
    assert result["decisions"][0]["reason"] == decision["reason"]
    assert result["structured_review"]["raw_response"] == raw
    assert all(not values for values in result["structured_review"]["selected_evidence"].values())


def test_supported_without_selected_evidence_still_cannot_authorize():
    contract = build_review_targets([mixed_claim()], "")
    payload = selection_reply(contract)
    decision = next(iter(payload["decisions"].values()))
    decision["evidence_refs"] = []
    with pytest.raises(AnalysisError):
        contract.normalize(json.dumps(payload))


@pytest.mark.parametrize("bad", ["missing", "foreign", "nonstring"])
def test_abstention_does_not_excuse_malformed_evidence_references(bad):
    contract = build_review_targets([mixed_claim()], "")
    payload = selection_reply(contract, status="needs_review")
    decision = next(iter(payload["decisions"].values()))
    if bad == "missing":
        decision.pop("evidence_refs")
    elif bad == "foreign":
        decision["evidence_refs"] = ["not-offered"]
    else:
        decision["evidence_refs"] = [False]
    with pytest.raises(AnalysisError):
        contract.normalize(json.dumps(payload))


class AbstainingReviewer(SchemaReviewer):
    """Reproduce the real fact/paragraph disagreement without changing the paragraph reply."""

    def __init__(self, claim_id="c1", status="needs_review"):
        super().__init__()
        self.claim_id, self.status = claim_id, status
        self.answers = []

    def complete_with_schema(self, messages, *, model, response_schema):
        answer = super().complete_with_schema(messages, model=model,
                                              response_schema=response_schema)
        payload = json.loads(answer.content)
        for key, target in self.requests[-1][2].items():
            if target["kind"] == "fact" and target["claim_id"] == self.claim_id:
                decision = payload["decisions"][key]
                decision["status"] = self.status
                decision["reason"] = "The metric is also covered by another target."
                decision["evidence_refs"] = []
        self.answers.append(json.dumps(payload))
        return replace(answer, content=self.answers[-1])


def setup(*, required=False, mixed=False):
    reading, first = candidates()
    second = replace(first, text="Experiment: The authors report a separate held-out test.",
        metadata={"paper_reading": {"claim_id": "c2", "section": "experiment"}},
        evidence=[replace(first.evidence[0], quote="The authors report a separate held-out test.")])
    if required:
        first = replace(first, metadata={"paper_reading": {"claim_id": "c1",
            "source": "reading_context", "context_field": "evaluation_context.outcome_measurement",
            "section": "experiment"}})
    reading = replace(reading, reader_explanation=ReaderExplanation(
        experiment_interpretation=[
            ReaderExplanationParagraph("作者评估12个模拟用户。", ["c1", "c2"] if mixed else ["c1"]),
            ReaderExplanationParagraph("作者还报告了独立的留出测试。", ["c2"]),
        ]))
    artifact = Artifact(SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "fixture"),
                        first.evidence[0].quote + "\n" + second.evidence[0].quote)
    return reading, [first, second], artifact


@pytest.mark.parametrize("status", ["needs_review", "unsupported", "speculative"])
def test_nonpublic_fact_blocks_only_dependent_paragraph_and_keeps_raw_judgment(status):
    reading, claims, artifact = setup()
    provider = AbstainingReviewer(status=status)
    result = model_review_publishable_claims(claims, provider, model="offline",
        readings=[reading], artifacts=[artifact])
    assert result.claims[0].status == ClaimStatus(status)
    blocked, retained = result.readings[0].reader_explanation.experiment_interpretation
    assert blocked.review.status == "needs_review"
    assert not blocked.review.binding_sha256
    assert "support" in blocked.review.reason.lower()
    assert blocked.text == reading.reader_explanation.experiment_interpretation[0].text
    assert blocked.supporting_claim_ids == ["c1"]
    assert retained.review.status == "supported" and retained.review.binding_sha256
    public, _ = public_explanation(result.readings[0].reader_explanation, result.claims,
                                   source_url=reading.source_url)
    assert blocked.text not in public["experiment_interpretation"]
    assert retained.text in public["experiment_interpretation"]
    audit = json.loads(result.raw_feedback)["structured_review"]
    assert audit["raw_response"] == provider.answers[0]
    raw = json.loads(audit["raw_response"])["decisions"]
    target = next(k for k, t in audit["targets"].items() if t.get("paragraph_id")
                  == "p1.experiment_interpretation.1")
    assert raw[target]["status"] == "supported"
    assert len(provider.requests) == 1


def test_no_support_id_is_removed_to_salvage_a_mixed_paragraph():
    reading, claims, artifact = setup(mixed=True)
    result = model_review_publishable_claims(claims, AbstainingReviewer(), model="offline",
        readings=[reading], artifacts=[artifact])
    blocked = result.readings[0].reader_explanation.experiment_interpretation[0]
    assert blocked.review.status == "needs_review"
    assert blocked.supporting_claim_ids == ["c1", "c2"]
    assert blocked.text == reading.reader_explanation.experiment_interpretation[0].text


def test_uncertain_required_condition_still_stops_complete_report_publication():
    reading, claims, artifact = setup(required=True)
    facts = review_publication_facts(claims, SchemaReviewer(), model="offline",
        readings=[reading], artifacts=[artifact]).claims
    provider = AbstainingReviewer()
    with pytest.raises(AnalysisError, match="Final report omitted reviewed context coverage"):
        model_review_publishable_claims(facts, provider, model="offline", readings=[reading],
            artifacts=[artifact], analysis_claims=facts)
    assert len(provider.requests) == 1
    assert "raw_response" not in claims[0].metadata


def test_valid_abstention_can_be_cached_without_becoming_approval(tmp_path):
    from research_radar.analysis.model_cache import CachedLLMProvider

    reading, claims, artifact = setup()
    provider = AbstainingReviewer()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="review")
    for _ in range(2):
        result = model_review_publishable_claims(claims, cached, model="offline",
            readings=[reading], artifacts=[artifact])
        assert not result.claims[0].is_publishable()
        assert result.readings[0].reader_explanation.experiment_interpretation[0].review.status \
            == "needs_review"
    assert cached.hit_count == 1 and len(provider.requests) == 1


def test_minimized_saved_metric_disagreement_does_not_become_a_format_failure():
    """Preserve observed wording/decisions; the source below is an explicit offline control."""
    reading, claims, artifact = setup()
    identity = "context-6997de9bf7bf49b9"
    text = ("Experiment: 协议报告查询级答案准确率、支持证据命中与排名度量、"
            "动态冲突的更新顺序一致性，以及静态冲突的冲突识别。")
    source = ("The offline protocol measures answer accuracy, evidence hits and ranking, "
              "update-order consistency for dynamic conflicts and recognition of static conflicts.")
    claims[0] = replace(claims[0], text=text,
        metadata={"paper_reading": {"claim_id": identity, "section": "experiment"}},
        evidence=[replace(claims[0].evidence[0], quote=source)])
    artifact = replace(artifact, text=source + "\n" + claims[1].evidence[0].quote)
    paragraph = ReaderExplanationParagraph(
        "评测报告答案准确率、支持证据命中与排名、动态冲突的 UOCS 和静态冲突的 CRS。",
        [identity])
    reading = replace(reading, reader_explanation=ReaderExplanation(
        experiment_interpretation=[paragraph]))
    provider = AbstainingReviewer(claim_id=identity)
    result = model_review_publishable_claims(claims, provider, model="offline",
        readings=[reading], artifacts=[artifact])
    review = result.readings[0].reader_explanation.experiment_interpretation[0].review
    assert review.status == "needs_review" and not review.binding_sha256
    assert result.claims[0].rationale == "The metric is also covered by another target."
    assert len(provider.requests) == 1


def test_no_new_review_is_required_to_preserve_original_paragraph_text_and_reason():
    reading, claims, artifact = setup()
    provider = AbstainingReviewer()
    result = model_review_publishable_claims(claims, provider, model="offline",
        readings=[reading], artifacts=[artifact])
    paragraph = result.readings[0].reader_explanation.experiment_interpretation[0]
    assert paragraph.text == reading.reader_explanation.experiment_interpretation[0].text
    assert paragraph.review.reason.startswith("Offline source-bound control.")
    assert result.claims[0].metadata["model_review"]["requested_status"] == "needs_review"
    assert len(provider.requests) == 1


def test_legacy_v2_empty_reference_lists_keep_their_original_strict_validation():
    from research_radar.analysis.review_targets import ReviewTargets, validate_review_response

    legacy = ReviewTargets({"original-target": {"kind": "fact", "claim_index": 1,
        "direct_evidence": {"original-evidence": {"quote": "Offline source."}}}})
    raw = json.dumps({"decisions": {"original-target": {"status": "needs_review",
        "reason": "Original legacy response.", "evidence_ids": []}}})
    with pytest.raises(AnalysisError):
        validate_review_response(raw, legacy.schema)
