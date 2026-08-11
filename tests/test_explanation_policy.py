from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import (
    ReaderExplanation,
    ReaderExplanationParagraph,
)
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor


def test_public_explanation_keeps_only_fully_supported_paragraphs() -> None:
    explanation = ReaderExplanation(
        solution_walkthrough=[
            ReaderExplanationParagraph(
                text="The system first retrieves candidates.",
                supporting_claim_ids=["c1"],
            ),
            ReaderExplanationParagraph(
                text="It then reranks them without an LLM.",
                supporting_claim_ids=["c1", "c2"],
            ),
        ]
    )
    claims = [
        _claim("c1", ClaimStatus.SUPPORTED),
        _claim("c2", ClaimStatus.NEEDS_REVIEW),
    ]

    public, audit = public_explanation(explanation, claims)

    assert public["solution_walkthrough"] == "The system first retrieves candidates."
    assert audit == {
        "paragraph_count": 2,
        "kept_count": 1,
        "dropped_count": 1,
        "fallback_section_count": 0,
    }


def test_public_explanation_drops_unbound_legacy_prose() -> None:
    explanation = ReaderExplanation(
        problem_walkthrough=[
            ReaderExplanationParagraph(text="Unbound explanation.")
        ]
    )

    public, audit = public_explanation(explanation, [_claim("c1", ClaimStatus.SUPPORTED)])

    assert public["problem_walkthrough"] == ""
    assert audit["dropped_count"] == 1


def _claim(claim_id: str, status: ClaimStatus) -> Claim:
    return Claim(
        text=f"Solution: {claim_id}",
        status=status,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote=claim_id)],
        metadata={"paper_reading": {"claim_id": claim_id, "section": "solution"}},
    )
