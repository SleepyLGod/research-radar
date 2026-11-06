"""Saved source conflicts and table scope stay distinct from automatic factual approval."""

import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from test_lotus_numeric_notation import SAVED
from test_method_contract_pipeline import Reading, Writing
from test_paper_reading import _claim_units_fixture
from test_review_targets import SchemaReviewer

from research_radar.analysis.anchor_repair import (
    apply_anchor_resolution,
    is_evidence_review_candidate,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
from research_radar.analysis.source_references import build_source_index
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)
from research_radar.pipeline import paper
from research_radar.security.secrets import KeychainSecretBackend

CONFLICT = json.loads((Path(__file__).parent / "fixtures/lotus_source_conflict.json").read_text())


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs) -> None:
        raise AssertionError("No live model, network or credential in source-context controls")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def table_input(
    dataset: str = "BioDEX", *, wrong_value: bool = False, wrong_dataset: bool = False,
) -> tuple[Artifact, Claim]:
    """Literal table scope and values; no declared semantic approval."""
    source = SourceCandidate("Public table excerpt", CONFLICT["source_url"],
                             SourceType.PAPER, "fixture")
    text = (f"[page 9]\nTable 3: Results on {dataset}.\nMethod Score\n"
            "LOTUS 0.265\nBaseline 0.280\n")
    name = "OtherBenchmark" if wrong_dataset else dataset
    value = "0.280" if wrong_value else "0.265"
    claim = Claim(f"Experiment: On {name}, LOTUS achieves Score {value}.", ClaimStatus.SUPPORTED,
        [EvidenceAnchor(source.url, "LOTUS 0.265")], metadata={"paper_reading": {
            "claim_id": "c35", "source": "claim_units", "claim_kind": "fact",
            "section": "experiment", "publishable_default": True}})
    return Artifact(source, text), claim


@pytest.mark.parametrize("dataset", ["BioDEX", "FreshCorpus"])
def test_caption_entity_is_reviewable_not_guessed_to_be_a_method_row(dataset: str) -> None:
    artifact, claim = table_input(dataset)
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "needs_review"
    assert checked[0].status == ClaimStatus.NEEDS_REVIEW
    assert is_evidence_review_candidate(checked[0], artifact)
    assert not fact_is_reviewed(checked[0])


@pytest.mark.parametrize("wrong", ["value", "dataset"])
def test_wrong_row_value_or_missing_dataset_stays_nonreviewable(wrong: str) -> None:
    artifact, claim = table_input(wrong_value=wrong == "value", wrong_dataset=wrong == "dataset")
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].status == ClaimStatus.UNSUPPORTED
    assert not is_evidence_review_candidate(checked[0], artifact)


@pytest.mark.parametrize("status", ["supported", "unsupported", "needs_review"])
def test_caption_role_ambiguity_requires_an_explicit_independent_fact_decision(status: str) -> None:
    artifact, claim = table_input()
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    reviewer = SchemaReviewer()
    original = reviewer.complete_with_schema

    def decide(*args, **kwargs) -> ModelResponse:
        response = original(*args, **kwargs)
        rows = json.loads(response.content)
        for row in rows["decisions"].values():
            row.update(status=status, reason="Explicit offline table-role decision.")
        return replace(response, content=json.dumps(rows))

    reviewer.complete_with_schema = decide
    result = review_publication_facts(checked, reviewer, model="offline",
                                     readings=[], artifacts=[artifact])
    assert len(reviewer.requests) == 1
    assert fact_is_reviewed(result.claims[0]) is (status == "supported")
    assert result.claims[0].text == claim.text
    assert result.claims[0].evidence == claim.evidence
    assert not checked[0].is_publishable()


def test_caption_role_ambiguity_cannot_hide_a_missing_model_identity() -> None:
    artifact, claim = table_input()
    claim = replace(claim, text=claim.text + " The model is Llama-70B.")
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].status == ClaimStatus.UNSUPPORTED
    assert resolutions[0].reason == "anchor missing key entities: Llama-70B"
    assert not is_evidence_review_candidate(checked[0], artifact)


def test_caption_cannot_substitute_for_missing_column_mapping() -> None:
    artifact, claim = table_input()
    artifact = replace(artifact, text=artifact.text.replace("Method Score", "Method Score Extra"))
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].status == ClaimStatus.UNSUPPORTED
    assert not is_evidence_review_candidate(checked[0], artifact)


def test_caption_does_not_hide_a_known_method_quoted_from_another_row() -> None:
    artifact, claim = table_input()
    artifact = replace(artifact, text=artifact.text.replace(
        "Results on BioDEX.", "Results on BioDEX using LOTUS."))
    claim = replace(claim, text="Experiment: On BioDEX, LOTUS achieves Score 0.280.",
                    evidence=[replace(claim.evidence[0], quote="Baseline 0.280")])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].status == ClaimStatus.UNSUPPORTED
    assert resolutions[0].reason == "table anchor row missing method entity: LOTUS"
    assert not is_evidence_review_candidate(checked[0], artifact)


def conflict_control() -> tuple[Artifact, dict, str, dict]:
    """Both real source excerpts; amended prose/decisions are explicitly editorial controls."""
    prose, algorithm = SAVED["cases"]["c8"]["quote"], CONFLICT["algorithm_quote"]
    artifact = Artifact(SourceCandidate("LOTUS conflict excerpt", CONFLICT["source_url"],
        SourceType.PAPER, "fixture"), f"[page 5]\n{algorithm}\n\n[page 6]\n{prose}")
    payload = json.loads(_claim_units_fixture(["Offline source conflict control."]))
    body = payload["deep_readings"]
    body["title"] = "LOTUS source-conflict control"
    for key in ("area_context", "problem_solution", "related_work", "limitations",
                "critical_assessment"):
        body[key]["evidence"] = [{"quote": prose}]
    body["claim_units"] = [{"claim_id": "c8", "section": "solution", "claim_kind": "fact",
        "text": SAVED["cases"]["c8"]["text"], "evidence": [{"quote": prose}],
        "publishable_default": True,
        "method": {"kind": "operation", "from_claim_id": None, "to_claim_id": None}}]
    body["method_flow"] = {"operations": [{"scope": "Apply proxy thresholds with oracle fallback",
        "operation_claim_id": "c8", "inputs": [], "outputs": [], "conditions": []}],
        "links": [], "gaps": []}
    body["evaluation_context"] = {
        "data_construction": [], "available_inputs": [], "outcome_measurement": []}
    body["reader_explanation"] = {}
    qualified = ("The paper's filter uses proxy thresholds with oracle fallback. Its prose rejects "
        "scores at or below the lower threshold, whereas its algorithm consults the oracle at "
        "equality when the lower threshold is below the upper threshold; the two descriptions "
        "disagree at this boundary.")
    chinese = ("过滤器利用代理得分阈值分流，必要时交给 oracle。正文将小于或等于下阈值的记录"
        "直接拒绝；算法在上下阈值不相等时，却把恰好等于下阈值的记录交给 oracle。"
        "两处描述在这个边界上不一致，不能当成已经统一的规则。")
    writing = {"claims": [{"claim_id": "c8", "text": "Solution: " + chinese}],
        "reader_explanation": {"solution_walkthrough": [
            {"text": chinese, "supporting_claim_ids": ["c8"]}]}}
    return artifact, payload, qualified, writing


def execute_conflict(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, bad: str = "", check_contract: bool = False,
) -> tuple[Path, list[str]]:
    """Editorial amendment and explicit review controls through the production paper entry."""
    artifact, payload, qualified, writing = conflict_control()
    order = []

    class AmendingReader(Reading):
        def complete_with_schema(
            self, messages: list[Message], *, model: str, response_schema: dict,
        ) -> ModelResponse:
            if "revisions" not in response_schema["properties"]:
                return super().complete_with_schema(messages, model=model,
                                                    response_schema=response_schema)
            order.append("amend")
            if check_contract:
                prompt = "\n".join(m.content for m in messages)
                assert "If source descriptions disagree" in prompt
                assert "Do not add unrelated result values" in prompt
            index = build_source_index(artifact)
            quotes = [SAVED["cases"]["c8"]["quote"]]
            if bad != "one_side":
                quotes.append(CONFLICT["algorithm_quote"])
            references = []
            for quote in quotes:
                start = artifact.text.index(quote)
                references.extend(index.references_for_span(start, start + len(quote)))
            return ModelResponse(json.dumps({"revisions": {"c8": {"text": qualified,
                "evidence": references,
                "reason": "Editorial control preserves both conflicting descriptions."}}}), model)

    class Reviewing(SchemaReviewer):
        def complete_with_schema(
            self, messages: list[Message], *, model: str, response_schema: dict,
        ) -> ModelResponse:
            first = not self.requests
            order.append("review")
            response = super().complete_with_schema(messages, model=model,
                                                   response_schema=response_schema)
            if check_contract:
                assert "conflicting source statements" in "\n".join(m.content for m in messages)
            rows = json.loads(response.content)
            for key, target in self.requests[-1][2].items():
                if (target["kind"] == "fact" and target["claim_id"] == "c8"
                        and (first or bad in {"one_side", "still_uncertain"})):
                    rows["decisions"][key].update(status="needs_review",
                                                 reason=CONFLICT["review_reason"])
                if bad == "final_rejected" and target["kind"] == "paragraph":
                    rows["decisions"][key].update(status="needs_review",
                        reason="Offline control withholds final paragraph approval.")
            return replace(response, content=json.dumps(rows))

    monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
    config = parse_config({"topics": [{"id": "lotus", "queries": ["semantic operators"]}]})
    run = paper.run_paper(root, config, "lotus", artifact.source.url,
        AmendingReader(payload, order), model="offline", verifier=Reviewing(),
        verifier_model="offline", localizer=Writing(writing, order),
        localization_model="offline", language="zh")
    return run, order


def test_existing_contract_can_publish_a_reviewed_attributed_source_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, order = execute_conflict(tmp_path, monkeypatch)
    assert order == ["reader", "review", "amend", "review", "writer", "review"]
    text = (run / "paper.md").read_text()
    assert "两处描述在这个边界上不一致" in text
    assert "## 方法与机制" in text
    audit = json.loads((run / "fact_revision.json").read_text())
    candidate = audit["attempts"][0]["candidates"]["c8"]
    assert len(candidate["evidence"]) == 2
    assert audit["initial_readings"][0]["claim_units"][0]["text"] == SAVED["cases"]["c8"]["text"]


def test_amendment_and_verifier_contracts_explain_conflicts_without_resolving_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_conflict(tmp_path, monkeypatch, check_contract=True)


@pytest.mark.parametrize("bad", ["one_side", "still_uncertain", "final_rejected"])
def test_conflict_wording_never_bypasses_fact_or_final_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    with pytest.raises(AnalysisError):
        execute_conflict(tmp_path, monkeypatch, bad=bad)
    assert not list(tmp_path.rglob("paper.md"))
