"""Offline regressions for experimental evidence lost to PDF layout noise."""

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_resolution, resolve_claim_anchors
from research_radar.analysis.prompts import verifier_prompt
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)


def artifact(text: str) -> Artifact:
    return Artifact(
        source=SourceCandidate(
            title="Memory evaluation",
            url="https://example.test/paper",
            source_type=SourceType.PAPER,
            source_name="offline",
        ),
        text=text,
    )


def claim(text: str, quote: str) -> Claim:
    return Claim(
        text=text,
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.test/paper", quote=quote)],
    )


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("The paper reports a 23.8 percentage-point improvement.", "+23.8pp improvement."),
        ("The paper reports a 14.9 percentage-point regression.", "Regression: −14.9pp."),
        ("The simulation used 170 facts over 30 days.", "Setup.170 facts over 30 days."),
        ("The hot group had a 6.7× strength difference.", "The hot group had a6.7×difference."),
        ("The mean reliability was 0.96.", "The mean reliability was 0 .96."),
        ("The paper reports a 22.7% improvement.", "The paper reports +22 .7% improvement."),
        ("The score was 2.5 EM.", "The score was 2.5EM."),
    ],
)
def test_numeric_anchor_accepts_literal_values_with_pdf_layout_noise(text: str, quote: str) -> None:
    result = resolve_claim_anchors([claim(text, quote)], artifact(f"[page 1]\n{quote}"))

    assert result[0].status == "matched"


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("The score was 23.8%.", "The score was 238%."),
        ("The score was 23.8%.", "The score was 23.8pp."),
        ("The simulation used 170 facts.", "The simulation used 1700 facts."),
        ("The mean was 0.96.", "The mean was 0 .69."),
    ],
)
def test_numeric_anchor_still_rejects_changed_values_and_percent_scale(
    text: str, quote: str,
) -> None:
    result = resolve_claim_anchors([claim(text, quote)], artifact(f"[page 1]\n{quote}"))

    assert result[0].status == "failed"
    assert result[0].reason == "numeric anchor missing claim values"


def test_same_section_context_reaches_verifier_without_losing_original_anchor() -> None:
    quote = "The method reaches 70.4% overall (214/304)."
    heading = "2.1 LoCoMo evaluation"
    text = (
        f"[page 1]\n{heading}\nSetup: 2 of 10 conversations.\n"
        "We use a fixed evaluation protocol.\nThe judge scores the same questions.\n"
        "No additional examples are sampled.\nResults follow below.\n"
        f"{quote}\n2.2 Other experiments\nPrivate unrelated result: 99.9%."
    )
    original = claim("The paper reports 70.4% LoCoMo accuracy (214 of 304).", quote)

    checked, resolutions, _ = apply_anchor_resolution([original], artifact(text))

    assert checked[0].is_publishable()
    assert resolutions[0].quote == quote
    assert checked[0].evidence[0].quote == quote
    prompt = verifier_prompt(checked)
    assert heading in prompt
    assert quote in prompt
    assert "Private unrelated result" not in prompt


@pytest.mark.parametrize("boundary", ["2.2 LongMemEval evaluation", "[page 2]"])
def test_context_cannot_borrow_benchmark_from_previous_section_or_page(boundary: str) -> None:
    quote = "The method reaches 70.4% overall."
    text = f"[page 1]\n2.1 LoCoMo evaluation\nThe score is 62.8%.\n{boundary}\n{quote}"

    checked, _, _ = apply_anchor_resolution(
        [claim("The method reaches 70.4% on LoCoMo.", quote)], artifact(text),
    )

    assert not checked[0].is_publishable()


def test_each_evidence_anchor_keeps_its_own_context() -> None:
    text = (
        "[page 1]\n2.1 Evaluation protocol\nThe evaluation used 304 questions.\n"
        "[page 2]\n2.2 Evaluation result\nThe accuracy was 70.4%."
    )
    original = claim("The evaluation used 304 questions and accuracy was 70.4%.",
                     "The evaluation used 304 questions.")
    original.evidence.append(EvidenceAnchor(
        source_url=original.evidence[0].source_url, quote="The accuracy was 70.4%.",
    ))

    checked, _, _ = apply_anchor_resolution([original], artifact(text))

    assert checked[0].is_publishable()
    assert len(checked[0].evidence) == 2
    prompt = verifier_prompt(checked)
    assert "2.1 Evaluation protocol" in prompt
    assert "2.2 Evaluation result" in prompt
    assert all(anchor.quote in text for anchor in checked[0].evidence)


def test_table_caption_and_late_overall_row_are_available_together() -> None:
    quote = "Round 3, best of 5 rounds"
    text = (
        "[page 1]\nTable 8: LoCoMo results (Round 3, best of 5 rounds).\n"
        "Category Baseline Selected\nSingle-hop 60.5% 65.1%\n"
        "Multi-hop 25.4% 49.2%\nTemporal 38.5% 53.8%\n"
        "Open-domain 86.8% 82.5%\nAdversarial 63.4% 76.1%\nOverall 62.8% 70.4%"
    )

    checked, _, _ = apply_anchor_resolution(
        [claim("The reported LoCoMo result is 70.4% in Round 3.", quote)], artifact(text),
    )

    assert checked[0].is_publishable()
    assert "Overall 62.8% 70.4%" in verifier_prompt(checked)


def test_scientific_notation_is_not_reduced_to_its_leading_integer() -> None:
    checked, _, _ = apply_anchor_resolution(
        [claim("The score was 1.", "The score was 1e3.")],
        artifact("[page 1]\nThe score was 1e3."),
    )

    assert not checked[0].is_publishable()


def test_table_metric_label_is_not_a_method_and_columns_bind_values() -> None:
    row = "MemGuide 0.80 3.19 0.99"
    text = f"[page 1]\nTable 3: Task evaluation.\nMethod JGA DTE SR\nFCP 0.73 6.03 0.88\n{row}"
    original = claim("MemGuide reports DTE of 3.19.", row)

    checked, _, _ = apply_anchor_resolution([original], artifact(text))

    assert checked[0].is_publishable()
    prompt = verifier_prompt(checked)
    assert "Method JGA DTE SR" in prompt
    assert "DTE" in prompt


def test_table_rejects_a_value_borrowed_from_another_metric_in_same_row() -> None:
    row = "MemGuide 0.80 3.19 0.99"
    text = f"[page 1]\nTable 3: Task evaluation.\nMethod JGA DTE SR\n{row}"

    checked, _, _ = apply_anchor_resolution([claim("MemGuide reports JGA of 0.99.", row)],
                                           artifact(text))

    assert not checked[0].is_publishable()


def test_far_table_row_preserves_header_and_exact_bounded_source_fragments() -> None:
    row = "MemGuide 0.80 3.19"
    text = "[page 1]\nTable 3: Fixed benchmark.\nMethod JGA DTE\n"
    text += "".join(f"Baseline-{i} 0.50 6.03\n" for i in range(90)) + row
    checked, _, _ = apply_anchor_resolution([claim("MemGuide reports JGA of 0.80.", row)],
                                           artifact(text))

    assert checked[0].is_publishable()
    contexts = checked[0].metadata["anchor_resolution"]["evidence_contexts"]
    assert contexts
    assert "Method JGA DTE" in verifier_prompt(checked)
    assert sum(len(segment["text"]) for segment in contexts[0]["segments"]) <= 1200
    for segment in contexts[0]["segments"]:
        assert text[segment["start"]:segment["end"]] == segment["text"]


def test_caption_below_table_and_explicit_model_group_reach_verifier() -> None:
    row = "MemGuide 0.80 3.19"
    text = f"[page 1]\nMethod JGA DTE\nModel-X\nFCP 0.73 6.03\n{row}\nTable 3: Fixed benchmark."
    original = claim("Under Model-X, MemGuide reports DTE of 3.19.", row)

    checked, _, _ = apply_anchor_resolution([original], artifact(text))

    assert checked[0].is_publishable()
    prompt = verifier_prompt(checked)
    assert "Model-X" in prompt
    assert "Table 3" in prompt


def test_grouped_table_cannot_borrow_values_from_another_model_block() -> None:
    row = "MemGuide 0.80 3.19"
    text = (
        f"[page 1]\nTable 3: Benchmark.\nMethod JGA DTE\nModel-X\n{row}\n"
        "Model-Y\nMemGuide 0.99 1.21"
    )

    checked, _, _ = apply_anchor_resolution(
        [claim("Under Model-X, MemGuide reports JGA of 0.99.", row)], artifact(text),
    )

    assert not checked[0].is_publishable()


@pytest.mark.parametrize("text", [
    "ours reports JGA of 3.19.", "ours reports JGA 3.19 / DTE 0.80.",
])
def test_lowercase_row_label_cannot_bypass_column_validation(text: str) -> None:
    row = "ours 0.80 3.19"
    table = f"[page 1]\nTable 3: Evaluation.\nMethod JGA DTE\n{row}"

    checked, _, _ = apply_anchor_resolution([claim(text, row)], artifact(table))

    assert not checked[0].is_publishable()


def test_lowercase_row_label_with_correct_single_metric_still_passes() -> None:
    row = "ours 0.80 3.19"
    table = f"[page 1]\nTable 3: Evaluation.\nMethod JGA DTE\n{row}"

    checked, _, _ = apply_anchor_resolution([claim("ours reports JGA of 0.80.", row)],
                                           artifact(table))

    assert checked[0].is_publishable()


@pytest.mark.parametrize("boundary", ["[page 2]\nTable 4: Other evaluation.",
                                      "Table 4: Other evaluation.", "Model-Y"])
def test_multi_block_quote_cannot_inherit_first_table_column_order(boundary: str) -> None:
    row = "MemGuide 0.80 3.19"
    quote = f"{row}\n{boundary}\nMethod DTE JGA\n{row}"
    table = f"[page 1]\nTable 3: Evaluation.\nMethod JGA DTE\n{quote}"

    checked, _, _ = apply_anchor_resolution(
        [claim("MemGuide reports JGA of 0.80 in Table 4.", quote)], artifact(table),
    )

    assert not checked[0].is_publishable()


def test_line_wrapped_numeric_prose_does_not_become_a_table() -> None:
    quote = "Removing filtering changes DTE\nfrom 3.19 to 4.30\nin this evaluation."
    checked, resolutions, _ = apply_anchor_resolution(
        [claim("DTE changes from 3.19 to 4.30.", quote)], artifact("[page 1]\n4 Results\n" + quote),
    )

    assert checked[0].is_publishable()
    assert resolutions[0].table is None


@pytest.mark.parametrize("attribution", ["Author-reported", "Author-cited", "Self-reported"])
def test_attribution_is_not_a_named_entity_requirement(attribution: str) -> None:
    quote = "The evaluation of MemTree used 304 questions."
    original = claim(f"{attribution}: MemTree was evaluated on 304 questions.", quote)

    checked, resolutions, _ = apply_anchor_resolution([original], artifact(f"[page 1]\n{quote}"))

    assert resolutions[0].status == "matched"
    assert checked[0].is_publishable()
    assert checked[0].text == original.text
    assert checked[0].evidence == original.evidence


@pytest.mark.parametrize("description", ["LLM-generated", "AI-generated", "LLM‑generated"])
def test_generation_description_is_not_a_model_name(description: str) -> None:
    quote = "MemTree uses a language model to generate dialogues for 12 sessions."
    original = claim(f"MemTree uses {description} dialogues for 12 sessions.", quote)
    checked, resolutions, _ = apply_anchor_resolution([original], artifact("[page 1]\n"+quote))
    assert resolutions[0].status == "matched"
    assert checked[0].is_publishable()
    assert checked[0].text == original.text
    assert checked[0].evidence == original.evidence


@pytest.mark.parametrize("text", [
    "OtherModel uses LLM-generated dialogues for 12 sessions.",
    "MemTree uses LLM-generated dialogues for 13 sessions.",
    "MemTree uses LLM-generated-2 for 12 sessions.",
    "MemTree uses LLM-Generated for 12 sessions.",
])
def test_generation_description_does_not_remove_real_model_or_quantity_checks(text: str) -> None:
    quote = "MemTree uses a language model to generate dialogues for 12 sessions."
    checked, _, _ = apply_anchor_resolution([claim(text, quote)], artifact("[page 1]\n"+quote))
    assert not checked[0].is_publishable()


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Author-reported: MemTree was evaluated on 304 questions.",
         "The evaluation used 304 questions."),
        ("Author-reported: MemTree was evaluated on 305 questions.",
         "The evaluation of MemTree used 304 questions."),
        ("Author-reported: Self-RAG was evaluated on 304 questions.",
         "The evaluation used 304 questions."),
    ],
)
def test_attribution_does_not_remove_real_entity_or_numeric_requirements(
    text: str, quote: str,
) -> None:
    checked, _, _ = apply_anchor_resolution([claim(text, quote)], artifact(f"[page 1]\n{quote}"))

    assert not checked[0].is_publishable()


PREFERENCE_ROWS = (
    "FRQAD (ours) 18,840 / 18,840 100.0%",
    "Cosine similarity 16,127 / 18,840 85.6%",
    "Fisher-Rao (standard) 13,316 / 18,840 70.7%",
)
PREFERENCE_TABLE = (
    "[page 13]\nTable 4: Mixed-precision preference.\n"
    "Method Correct pairs Accuracy\n" + "\n".join(PREFERENCE_ROWS)
)


def comparison_claim(text: str, quotes: tuple[str, ...] = PREFERENCE_ROWS) -> Claim:
    return Claim(
        text=text,
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(source_url="https://example.test/paper", quote=quote)
            for quote in quotes
        ],
    )


def test_comparison_uses_each_methods_own_table_anchor() -> None:
    original = comparison_claim(
        "On the mixed-precision preference task, FRQAD preferred the float32 embedding "
        "in 18,840/18,840 pairs (100.0%), versus 85.6% for cosine similarity and "
        "70.7% for standard Fisher-Rao."
    )

    checked, resolutions, _ = apply_anchor_resolution([original], artifact(PREFERENCE_TABLE))

    assert resolutions[0].status == "matched"
    assert checked[0].is_publishable()
    assert checked[0].evidence == original.evidence


@pytest.mark.parametrize(
    "text",
    [
        "FRQAD scores 100.0%, cosine similarity scores 85.6%, and Fisher-Rao scores 70.7%.",
        "FRQAD scores 100.0%; Fisher-Rao scores 70.7%.",
        "Table 4 reports 100.0% for FRQAD versus 70.7% for Fisher-Rao.",
    ],
)
def test_comparison_preserves_numeric_binding_for_common_clause_orders(text: str) -> None:
    checked, _, _ = apply_anchor_resolution([comparison_claim(text)], artifact(PREFERENCE_TABLE))

    assert checked[0].is_publishable()


@pytest.mark.parametrize(
    "text",
    [
        "FRQAD scores 70.7%, whereas Fisher-Rao scores 100.0%.",
        "FRQAD scores 100.0%, versus 70.7% for cosine similarity and 85.6% for Fisher-Rao.",
        "FRQAD scores 100.0% and 70.7% accuracy, whereas Fisher-Rao scores 70.7%.",
        "MemTree scores 100.0%, versus 70.7% for Fisher-Rao.",
        "FRQAD scores 99.9%, versus 70.7% for Fisher-Rao.",
    ],
)
def test_comparison_rejects_swapped_or_unsupported_method_values(text: str) -> None:
    checked, _, _ = apply_anchor_resolution([comparison_claim(text)], artifact(PREFERENCE_TABLE))

    assert not checked[0].is_publishable()


def test_comparison_cannot_borrow_an_unquoted_method_row_from_table_context() -> None:
    original = comparison_claim(
        "FRQAD scores 100.0%, versus 70.7% for Fisher-Rao.",
        quotes=PREFERENCE_ROWS[:1],
    )

    checked, _, _ = apply_anchor_resolution([original], artifact(PREFERENCE_TABLE))

    assert not checked[0].is_publishable()


def test_comparison_accepts_one_exact_quote_spanning_multiple_rows() -> None:
    original = comparison_claim(
        "FRQAD scores 100.0%, versus 70.7% for Fisher-Rao.",
        quotes=("\n".join(PREFERENCE_ROWS),),
    )

    checked, resolutions, _ = apply_anchor_resolution([original], artifact(PREFERENCE_TABLE))

    assert resolutions[0].status == "matched"
    assert checked[0].is_publishable()


def test_multiline_comparison_cannot_hide_swapped_values() -> None:
    original = comparison_claim(
        "FRQAD scores 70.7%, versus 100.0% for Fisher-Rao.",
        quotes=("\n".join(PREFERENCE_ROWS),),
    )

    checked, _, _ = apply_anchor_resolution([original], artifact(PREFERENCE_TABLE))

    assert not checked[0].is_publishable()


def test_category_rows_are_not_treated_as_method_names() -> None:
    first = "single-hop 60.5% 65.1%"
    second = "multi-hop 25.4% 49.2%"
    text = (
        "[page 15]\nTable 8: LoCoMo category results (Round 3).\n"
        f"Category Baseline Selected\n{first}\n{second}\n"
        "Overall 62.8% 70.4%\nThe overall result is 214/304."
    )
    original = comparison_claim(
        "LoCoMo category results (Round 3): single-hop 65.1%, multi-hop 49.2%, "
        "overall 70.4% (214/304).",
        quotes=(first, second),
    )

    checked, _, _ = apply_anchor_resolution([original], artifact(text))

    assert checked[0].is_publishable()


@pytest.mark.parametrize("method", ["frqad", "FRQAD"])
@pytest.mark.parametrize("fisher", ["Fisher-Rao", "Fisher–Rao"])
def test_comparison_normalizes_method_case_and_pdf_hyphens(method: str, fisher: str) -> None:
    rows = (f"{method} (ours) 18,840 100.0%", f"{fisher} (standard) 13,316 70.7%")
    text = "[page 1]\nTable 4: Preference\nMethod Correct Accuracy\n" + "\n".join(rows)
    original = comparison_claim(
        "FRQAD scores 100.0%, versus 70.7% for Fisher-Rao.", quotes=rows,
    )

    checked, _, _ = apply_anchor_resolution([original], artifact(text))

    assert checked[0].is_publishable()


def test_ambiguous_comparison_does_not_guess_which_value_belongs_to_which_method() -> None:
    original = comparison_claim("FRQAD / Fisher-Rao: 100.0% / 70.7%.")

    checked, resolutions, _ = apply_anchor_resolution([original], artifact(PREFERENCE_TABLE))

    assert not checked[0].is_publishable()
    assert "ambiguous" in resolutions[0].reason
