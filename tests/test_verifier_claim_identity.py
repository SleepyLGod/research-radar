"""Offline regressions for stable claim IDs versus request-local review indexes."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS
from test_explanation_support_contract import _reading
from test_paper_reading import _artifact

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import (
    PaperReading,
    ReaderExplanation,
    ReaderExplanationParagraph,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import ModelReviewResult, model_review_publishable_claims
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

RECORD = json.loads((Path(__file__).parent / "fixtures/verifier_claim_identity.json").read_text(
    encoding="utf-8",
))
URL = RECORD["source_url"]
C13_EVIDENCE = [{**anchor, "source_title": None, "confidence": 1.0}
                for anchor in RECORD["claims"][11]["evidence"]]


class SavedReviewer:
    """Replay saved decisions at the model boundary, without evaluating new prose."""

    name = "offline-saved-review"
    reader_contexts = OFFLINE_READER_CONTEXTS

    def __init__(self, feedback: dict | None = None) -> None:
        self.feedback = RECORD["saved_feedback"] if feedback is None else feedback
        self.prompt = ""

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.prompt = messages[1].content
        return ModelResponse(model=model, content=json.dumps(self.feedback))


def saved_claims() -> list[Claim]:
    """Reconstruct the exact public claim identities, text and quotes, without approvals."""
    return [Claim(
        text=item["text"], status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(**anchor) for anchor in item["evidence"]],
        metadata={"paper_reading": {"claim_id": item["claim_id"]},
                  "localization": {"original_text": item["original_text"]}},
    ) for item in RECORD["claims"]]


def saved_reading() -> PaperReading:
    sections: dict[str, list[ReaderExplanationParagraph]] = {}
    for item in RECORD["paragraphs"]:
        section = item["paragraph_id"].split(".")[1]
        sections.setdefault(section, []).append(ReaderExplanationParagraph(
            text=item["text"], supporting_claim_ids=item["supporting_claim_ids"],
        ))
    return replace(_reading("", []), source_url=URL, title=RECORD["source_title"],
                   reader_explanation=ReaderExplanation(**sections))


def review(
    claims: list[Claim], readings: list[PaperReading] | None = None, feedback: dict | None = None,
) -> tuple[ModelReviewResult, list[dict], dict]:
    provider = SavedReviewer(feedback)
    # These are bounded source excerpts, not a new full-paper quality evaluation.
    artifact = replace(_artifact(), source=replace(_artifact().source, url=URL),
                       text="\n\n".join(a.quote for c in claims for a in c.evidence))
    result = model_review_publishable_claims(
        claims, provider, model="offline-model", readings=readings or [saved_reading()],
        artifacts=[artifact],
    )
    context = json.loads(provider.prompt.split(
        "FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n", 1,
    )[1])
    references = [json.loads(line.removeprefix("CLAIM REFERENCE: "))
                  for line in provider.prompt.splitlines() if line.startswith("CLAIM REFERENCE: ")]
    return result, references, context


def test_live_record_exposes_original_ids_next_to_filtered_review_positions() -> None:
    _, references, context = review(saved_claims())
    by_id = {item["claim_id"]: item for item in references}
    assert by_id["c13"] == {"claim_index": 12, "claim_id": "c13", "source_urls": [URL]}
    assert by_id["c37"] == {"claim_index": 33, "claim_id": "c37", "source_urls": [URL]}
    assert by_id["c21"]["claim_index"] == 19
    paragraph = context["paragraphs"][3]
    assert paragraph["supporting_claims"] == [{
        "claim_id": "c13", "claim_index": 12, "source_url": URL,
        "text": RECORD["claims"][11]["text"],
        "evidence": C13_EVIDENCE, "source_bindings": [],
    }]
    experiment = context["paragraphs"][6]
    references = [(item["claim_id"], item["claim_index"])
                  for item in experiment["supporting_claims"]]
    assert references == [
        ("c11", 11), ("c20", 18), ("c21", 19), ("c22", 20), ("c23", 21),
    ]


@pytest.mark.parametrize("reorder, expected", [(False, (11, 32)), (True, (22, 1))])
def test_filtering_and_reordering_change_positions_not_stable_ids(
    reorder: bool, expected: tuple[int, int],
) -> None:
    claims = saved_claims()
    if reorder:
        claims.reverse()
    else:
        claims[0] = replace(claims[0], status=ClaimStatus.NEEDS_REVIEW)
    _, references, context = review(claims)
    by_id = {item["claim_id"]: item["claim_index"] for item in references}
    assert (by_id["c13"], by_id["c37"]) == expected
    assert context["paragraphs"][3]["supporting_claims"][0]["claim_index"] == expected[0]
    assert context["paragraphs"][3]["supporting_claim_ids"] == ["c13"]


def test_same_id_in_another_paper_resolves_only_to_that_papers_claim() -> None:
    first = saved_claims()[11]
    other_url = "https://example.test/other-paper"
    second = replace(first, text="A different paper's assertion.", evidence=[
        replace(first.evidence[0], source_url=other_url),
    ])
    reading = replace(_reading(first.text, ["c13"]), source_url=URL)
    other = replace(_reading(second.text, ["c13"]), source_url=other_url)
    _, references, context = review([first, second], [reading, other])
    assert [item["source_urls"] for item in references] == [[URL], [other_url]]
    assert context["paragraphs"][0]["supporting_claims"] == [{
        "claim_id": "c13", "claim_index": 1, "source_url": URL, "text": first.text,
        "evidence": C13_EVIDENCE, "source_bindings": [],
    }]
    assert context["paragraphs"][1]["supporting_claims"] == [{
        "claim_id": "c13", "claim_index": 2, "source_url": other_url, "text": second.text,
        "evidence": [{**C13_EVIDENCE[0], "source_url": other_url}],
        "source_bindings": [],
    }]


def test_legacy_claim_without_id_does_not_acquire_a_positional_reader_id() -> None:
    legacy = replace(saved_claims()[11], metadata={})
    reading = replace(_reading(legacy.text, ["c1"]), source_url=URL)
    result, references, context = review([legacy], [reading], {
        "decisions": [{"claim_index": 1, "status": "supported"}],
        "explanation_decisions": [{"paragraph_id": "p1.opening_context.1",
                                  "status": "supported", "reason": "Offline control."}],
    })
    assert references == [{"claim_index": 1, "claim_id": None, "source_urls": [URL]}]
    assert context["paragraphs"][0]["supporting_claims"] == []
    public, _ = public_explanation(result.readings[0].reader_explanation, result.claims,
                                   source_url=URL)
    assert not public["opening_context"]


@pytest.mark.parametrize("case", ["suffix", "unknown", "foreign", "duplicate", "rejected"])
def test_reference_records_cannot_authorize_missing_ambiguous_or_rejected_support(
    case: str,
) -> None:
    claims = [saved_claims()[11]]
    ids = ["c13"]
    if case == "suffix":
        ids = ["c1"]
    elif case == "unknown":
        ids = ["c404"]
    elif case == "foreign":
        claims = [replace(claims[0], evidence=[replace(
            claims[0].evidence[0], source_url="https://example.test/foreign",
        )])]
    elif case == "duplicate":
        claims = claims * 2
    else:
        claims = [replace(claims[0], status=ClaimStatus.NEEDS_REVIEW), saved_claims()[0]]
    reading = replace(_reading("Unapproved prose.", ids), source_url=URL)
    feedback = {
        "decisions": [{"claim_index": i, "status": "supported"}
                      for i in range(1, len(claims) + 1)],
        "explanation_decisions": [{"paragraph_id": "p1.opening_context.1",
                                  "status": "supported", "reason": "Offline control."}],
    }
    result, _, context = review(claims, [reading], feedback)
    if case in ("suffix", "unknown", "foreign", "rejected"):
        assert context["paragraphs"][0]["supporting_claims"] == []
    public, audit = public_explanation(result.readings[0].reader_explanation, result.claims,
                                      source_url=URL)
    assert not public["opening_context"]
    assert audit["kept_count"] == 0


def test_replaying_saved_rejections_does_not_silently_reapprove_prose() -> None:
    result, _, _ = review(saved_claims())
    _, audit = public_explanation(result.readings[0].reader_explanation, result.claims,
                                  source_url=URL)
    assert audit["kept_count"] == 2
    assert audit["dropped_count"] == 9
    paragraph = result.readings[0].reader_explanation.solution_walkthrough[1]
    assert paragraph.supporting_claim_ids == ["c13"]
    assert paragraph.review.status == "needs_review"
    assert paragraph.review.reason == RECORD["saved_feedback"]["explanation_decisions"][3]["reason"]


def test_returned_decisions_still_address_review_positions_not_id_suffixes() -> None:
    feedback = {"decisions": [
        {"claim_index": i, "status": "needs_review" if i == 13 else "supported"}
        for i in range(1, 34)
    ]}
    result, _, _ = review(saved_claims(), feedback=feedback)
    by_id = {claim.metadata["paper_reading"]["claim_id"]: claim for claim in result.claims}
    assert by_id["c13"].is_publishable()
    assert not by_id["c14"].is_publishable()


@pytest.mark.parametrize("claim_id", ["c13", "method/main"])
def test_explicit_review_accepts_exact_support_without_renumbering_ids(claim_id: str) -> None:
    claim = saved_claims()[11]
    claim = replace(claim, metadata={"paper_reading": {"claim_id": claim_id}})
    reading = replace(_reading(claim.text, [claim_id]), source_url=URL)
    result, references, context = review([claim], [reading], {
        "decisions": [{"claim_index": 1, "status": "supported"}],
        "explanation_decisions": [{"paragraph_id": "p1.opening_context.1",
                                  "status": "supported", "reason": "Offline control."}],
    })
    assert references[0]["claim_id"] == claim_id
    assert context["paragraphs"][0]["supporting_claims"] == [{
        "claim_id": claim_id, "claim_index": 1, "source_url": URL, "text": claim.text,
        "evidence": C13_EVIDENCE, "source_bindings": [],
    }]
    public, _ = public_explanation(result.readings[0].reader_explanation, result.claims,
                                   source_url=URL)
    assert public["opening_context"] == claim.text
    assert result.claims[0].metadata["paper_reading"]["claim_id"] == claim_id
