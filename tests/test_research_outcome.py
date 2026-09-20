"""Research completion is distinct from successfully writing report files."""

import pytest

from research_radar.analysis.research_outcome import assess_research_outcome, parse_research_outcome


@pytest.mark.parametrize(
    ("changes", "status", "reasons"),
    [
        ({}, "no_new_content", ["no_eligible_papers"]),
        ({"discovery_failed": True}, "incomplete", ["discovery_failed", "no_eligible_papers"]),
        (
            {"eligible_count": 1, "reading_statuses": ["insufficient_full_text"]},
            "incomplete",
            ["full_text_unavailable"],
        ),
        (
            {"eligible_count": 1, "reading_statuses": ["reading_failed"]},
            "incomplete",
            ["reading_failed"],
        ),
        (
            {"eligible_count": 1, "reading_statuses": ["succeeded"]},
            "incomplete",
            ["evidence_insufficient"],
        ),
        (
            {"eligible_count": 1, "reading_statuses": ["succeeded"], "verifier_reviewed_count": 2},
            "incomplete",
            ["verification_no_public_claims"],
        ),
        (
            {
                "eligible_count": 2,
                "deep_read_count": 1,
                "publishable_claim_count": 3,
                "reading_statuses": ["succeeded", "reading_failed"],
            },
            "ready",
            ["reading_failed"],
        ),
    ],
)
def test_research_outcome_uses_actual_stages(changes, status, reasons) -> None:
    arguments = dict(
        eligible_count=0,
        deep_read_count=0,
        publishable_claim_count=0,
        discovery_failed=False,
        reading_statuses=[],
        verifier_reviewed_count=0,
    )
    outcome = assess_research_outcome(**(arguments | changes))
    assert outcome == {"status": status, "reasons": reasons}


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"status": "other", "reasons": []},
        {"status": "ready", "reasons": [], "secret": "fixture"},
        {"status": "ready", "reasons": ["unrecognized"]},
        {"status": "ready", "reasons": ["reading_failed", "reading_failed"]},
        {"status": "ready", "reasons": [{}]},
    ],
)
def test_outcome_contract_rejects_malformed_values(value) -> None:
    with pytest.raises(ValueError, match="Invalid research outcome"):
        parse_research_outcome(value)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_empty_report_text_preserves_language_and_does_not_invent_verification(language) -> None:
    from research_radar.compose.draft import apply_research_outcome, build_daily_draft

    draft = build_daily_draft("memory", [], [], language=language, readings=[])
    original_lede = draft.lede
    updated = apply_research_outcome(
        draft, {"status": "no_new_content", "reasons": ["no_eligible_papers"]}
    )
    assert draft.lede == original_lede
    assert "核验" not in updated.lede and "verification" not in updated.lede
    assert updated.digest == updated.lede[:120]
    assert (
        next(
            section for section in updated.sections if section.metadata["kind"] == "today_summary"
        ).body
        == updated.lede
    )
