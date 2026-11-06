"""Unverified explanation prose cannot borrow publication eligibility from claim IDs."""

import json
from dataclasses import replace

import pytest
from test_paper_reading import _artifact, _claim_units_fixture

from research_radar.analysis.explanation_policy import public_explanation
from research_radar.analysis.paper_reading import (
    PaperReading,
    ReaderExplanation,
    ReaderExplanationParagraph,
    parse_paper_reading,
)
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.paper import render_paper_brief
from research_radar.compose.wechat import render_wechat_html
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor

FACT = "The benchmark evaluated 12 questions."
UNRELATED = "Competing memory systems do not implement forgetting."


@pytest.fixture
def approved_claims() -> list[Claim]:
    """Assume cited experiment claims passed verification, isolating prose publication."""
    source = _artifact().source
    return [
        Claim(
            text=f"Experiment: {text}", status=ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url=source.url, source_title=source.title, quote=text)],
            metadata={"paper_reading": {"claim_id": claim_id, "section": "experiment"}},
        )
        for claim_id, text in (("c20", FACT), ("c22", "The benchmark used two sessions."))
    ]


def _reading(text: str, ids: list[str]) -> PaperReading:
    payload = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    reading = parse_paper_reading(json.dumps(payload), _artifact())
    return replace(reading, reader_explanation=ReaderExplanation(
        opening_context=[ReaderExplanationParagraph(text=text, supporting_claim_ids=ids)],
    ))


@pytest.mark.parametrize("ids", [[], ["c404"], ["c20", "c404"]])
def test_missing_or_unknown_support_ids_do_not_publish(
    approved_claims: list[Claim], ids: list[str],
) -> None:
    public, audit = public_explanation(_reading(UNRELATED, ids).reader_explanation, approved_claims)

    assert public["opening_context"] == ""
    assert audit["dropped_count"] == 1


def test_one_rejected_support_id_blocks_the_whole_paragraph(approved_claims: list[Claim]) -> None:
    approved_claims[1] = replace(approved_claims[1], status=ClaimStatus.UNSUPPORTED)

    public, audit = public_explanation(
        _reading(UNRELATED, ["c20", "c22"]).reader_explanation, approved_claims,
    )

    assert public["opening_context"] == ""
    assert audit["dropped_count"] == 1


def test_verified_claims_remain_readable_without_approving_raw_explanation(
    approved_claims: list[Claim],
) -> None:
    reading = _reading(FACT, ["c20"])
    public, audit = public_explanation(reading.reader_explanation, approved_claims)

    assert public["opening_context"] == ""
    assert public["experiment_interpretation"] == f"{FACT}\n\nThe benchmark used two sessions."
    assert reading.reader_explanation.opening_context[0].text == FACT
    assert reading.reader_explanation.opening_context[0].supporting_claim_ids == ["c20"]
    assert audit == {
        "paragraph_count": 1, "kept_count": 0, "dropped_count": 1, "fallback_section_count": 1,
    }


def test_real_ids_cannot_authorize_an_unrelated_background(approved_claims: list[Claim]) -> None:
    # Minimized from the live answer: background assertions pointed to experiment c20/c22.
    public, _ = public_explanation(
        _reading(UNRELATED, ["c20", "c22"]).reader_explanation, approved_claims,
    )

    assert public["opening_context"] == ""


@pytest.mark.parametrize("surface", ["daily_markdown", "daily_html", "paper"])
@pytest.mark.parametrize("aligned", [True, False])
def test_public_output_keeps_aligned_content_but_blocks_unrelated_prose(
    approved_claims: list[Claim], surface: str, aligned: bool,
) -> None:
    text = FACT if aligned else UNRELATED
    reading = _reading(text, ["c20", "c22"])
    if surface == "paper":
        outputs = [render_paper_brief(reading, approved_claims)]
    else:
        source = _artifact().source
        draft = build_daily_draft(
            "offline", [source], approved_claims, readings=[reading], deep_read_sources=[source],
        )
        outputs = [
            render_markdown(draft) if surface == "daily_markdown" else render_wechat_html(draft)
        ]

    for output in outputs:
        assert FACT in output
        assert UNRELATED not in output
