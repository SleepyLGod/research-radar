import pytest

from research_radar.analysis.paper_reading import paper_reading_prompt
from research_radar.analysis.paper_sections import (
    PaperSectionChunk,
    build_paper_sections,
    build_reading_packet,
    render_reading_packet,
)
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, SourceCandidate, SourceType


def test_page_text_is_split_into_page_aware_chunks() -> None:
    artifact = _artifact(
        """
[page 1]
Abstract
This paper studies agent memory.

[page 2]
3 Method
The method stores retrieved memories.
"""
    )

    chunks = build_paper_sections(artifact)

    assert [(chunk.page_start, chunk.role) for chunk in chunks] == [
        (1, "abstract"),
        (2, "method"),
    ]


def test_reading_packet_preserves_late_experiment_quote_beyond_early_text() -> None:
    late_quote = "LATE_RESULT: LOCOMO accuracy improves after memory filtering."
    artifact = _artifact(
        "\n\n".join(
            [
                "[page 1]\nAbstract\n" + ("early intro filler " * 900),
                "[page 8]\n4 Experiments\n" + late_quote,
                "[page 9]\n5 Conclusion\nThe paper reports no deployment evaluation.",
            ]
        )
    )

    packet = build_reading_packet(artifact)
    packet_text = "\n".join(chunk.text for chunk in packet.chunks)

    assert late_quote not in artifact.text[:12_000]
    assert late_quote in packet_text
    assert any(chunk.role == "experiments_results" for chunk in packet.chunks)
    assert any(chunk.role == "limitations_conclusion" for chunk in packet.chunks)


def test_reading_packet_covers_core_section_roles() -> None:
    artifact = _artifact(
        """
[page 1]
Abstract
Agent memory needs structured comparison.

[page 2]
1 Introduction
Prior memory methods are hard to compare.

[page 4]
3 Framework
The method decomposes memory into extraction and retrieval.

[page 8]
4 Experiments
LOCOMO and LONGMEMEVAL are used for evaluation.

[page 12]
6 Conclusion
Future work should test deployed agents.
"""
    )

    packet = build_reading_packet(artifact)
    roles = {chunk.role for chunk in packet.chunks}

    assert {"method", "experiments_results", "limitations_conclusion"}.issubset(roles)
    assert roles.intersection({"abstract", "introduction"})
    assert packet.warnings == []


def test_plural_late_headings_are_classified_as_results_and_conclusions() -> None:
    artifact = _artifact(
        """
[page 1]
Memory in the LLM Era
ABSTRACT
This paper studies agent memory.

[page 6]
8 EXPERIMENTS
LOCOMO benchmark results are reported.

[page 12]
11 CONCLUSIONS
The paper reports future work.
"""
    )

    chunks = build_paper_sections(artifact)

    assert {chunk.page_start: chunk.role for chunk in chunks} == {
        1: "abstract",
        6: "experiments_results",
        12: "limitations_conclusion",
    }


def test_references_are_preserved_without_competing_with_body() -> None:
    artifact = _artifact(
        """
[page 1]
Abstract
Agent memory needs structured comparison.

[page 2]
3 Method
The method uses memory retrieval.

[page 3]
4 Experiments
LOCOMO benchmark results are reported.

[page 4]
5 Conclusion
The paper reports future work.

[page 5]
References
[1] Very long benchmark reference text with LOCOMO and LONGMEMEVAL repeated many times.
"""
    )

    packet = build_reading_packet(artifact, char_budget=6_000)

    assert any(chunk.role == "references" for chunk in packet.chunks)
    assert artifact.text in render_reading_packet(packet)


def test_references_continuation_stops_before_appendix() -> None:
    artifact = _artifact(
        """
[page 1]
Abstract
Agent memory needs structured comparison.

[page 14]
REFERENCES
[1] A paper about benchmark results.

[page 15]
[2] Another paper about memory methods and framework details.

[page 17]
A PROMPT TEMPLATES
Prompt for Graph-based Extraction.
"""
    )

    chunks = build_paper_sections(artifact)
    roles = {chunk.page_start: chunk.role for chunk in chunks}

    assert roles[14] == "references"
    assert roles[15] == "references"
    assert roles[17] != "references"


def test_paper_reading_prompt_uses_structured_packet_not_raw_prefix_truncation() -> None:
    artifact = _artifact(
        "\n\n".join(
            [
                "[page 1]\nAbstract\n" + ("early intro filler " * 900),
                "[page 7]\n4 Experiments\nLATE_RESULT: late-page result is retained.",
                "[page 8]\n5 Conclusion\nThe paper reports no deployment evaluation.",
            ]
        )
    )

    prompt = paper_reading_prompt(artifact)

    assert "FULL PAPER READING PACKET" in prompt
    assert "role=experiments_results" in prompt
    assert "LATE_RESULT: late-page result is retained." in prompt
    assert "TEXT:\n" not in prompt


@pytest.mark.parametrize("heading", ["Appendix A", "APPENDIX A", "appendix b", "Appendix"])
def test_appendix_heading_releases_reference_continuation(heading: str) -> None:
    artifact = _artifact(
        "[page 1]\nAbstract\nA memory method.\n"
        "[page 8]\nReferences\nA paper about evaluation.\n"
        "[page 9]\nSee Appendix A for details in the cited paper.\nAppendix material\n"
        f"[page 10]\n{heading}\nEvaluation protocol\n"
        "Final success is measured after clarification.\n"
        "[page 11]\nMore evaluation conditions."
    )

    sections = build_paper_sections(artifact)
    roles = {section.page_start: section.role for section in sections}
    packet = build_reading_packet(artifact)

    assert roles[8] == roles[9] == "references"
    assert roles[10] != "references"
    assert roles[11] != "references"
    assert any("Final success is measured after clarification." in c.text for c in packet.chunks)


def _artifact(text: str) -> Artifact:
    return Artifact(
        source=SourceCandidate(
            title="Memory Paper",
            url="https://example.com/paper.pdf",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text=text.strip(),
        content_type="application/pdf",
    )


def test_same_page_sections_keep_their_own_roles_and_exact_source_spans() -> None:
    artifact = _artifact(
        "[page 1]\nAbstract\nA benchmark.\n"
        "[page 4]\n3 Method\nThe pipeline reads inputs and filters records.\n"
        "4 Experiments\nWe evaluated 12 instances using macro-averages.\n"
        "5 Limitations\nControlled simulation is not a deployed population."
    )

    chunks = build_paper_sections(artifact)
    roles = {c.role for c in chunks if c.page_start == 4}
    assert {"method", "experiments_results", "limitations_conclusion"} <= roles
    for chunk in chunks:
        assert artifact.text[chunk.metadata["source_start"]:chunk.metadata["source_end"]] == (
            chunk.text
        )
    packet = build_reading_packet(artifact)
    assert "Controlled simulation" in render_reading_packet(packet)


def test_section_continues_across_pages_without_reclassifying_its_body() -> None:
    artifact = _artifact(
        "[page 1]\n3 Method\nThe algorithm has two stages.\n"
        "[page 2]\nA benchmark is mentioned to explain an algorithm input.\n"
        "4 Experiments\nWe use macro-averages."
    )

    chunks = build_paper_sections(artifact)
    continuation = next(c for c in chunks if "mentioned" in c.text)
    assert continuation.role == "method"
    assert continuation.metadata["heading"] == "3 Method"


def test_coverage_records_complete_sections_without_sampling() -> None:
    artifact = _artifact("3 Method\n" + "A complete sentence. " * 1000)
    packet = build_reading_packet(artifact)

    assert packet.coverage
    assert all(c["status"] == "complete" for c in packet.coverage)
    assert artifact.text in render_reading_packet(packet)


def test_explicit_character_cap_stops_instead_of_selecting_excerpts() -> None:
    text = "3 Method\n" + "The full algorithm step is preserved.\n" * 40
    with pytest.raises(AnalysisError, match="exceeds"):
        build_reading_packet(_artifact(text), char_budget=350)


def test_many_result_pages_do_not_starve_a_short_actual_limitations_section() -> None:
    text = "[page 1]\nAbstract\nA benchmark.\n[page 2]\n3 Method\nA pipeline.\n"
    for i in range(3, 12):
        text += f"[page {i}]\n4.{i} Results\n" + "The measured result is conditional.\n" * 100
    text += "[page 12]\n5 Limitations\nOnly 12 simulated instances were evaluated."

    packet = build_reading_packet(_artifact(text))

    assert "Only 12 simulated instances" in render_reading_packet(packet)
    assert text in render_reading_packet(packet)


def test_acronyms_author_lines_and_numeric_units_are_not_section_headings() -> None:
    artifact = _artifact(
        "[page 1]\n3 Method\nZHEN TAO, Example University\n"
        "LLM pipelines process long histories.\n10K tokens per history.\nBLEU\n"
        "The score is an experimental reference."
    )

    chunks = build_paper_sections(artifact)

    assert len(chunks) == 1
    assert chunks[0].metadata["heading"] == "3 Method"


def test_unnumbered_method_title_uses_its_own_body_not_previous_related_work() -> None:
    artifact = _artifact(
        "[page 1]\nRelated Work\nPrior work compares systems.\n"
        "[page 2]\nProposedSystem\nThis framework has two modules and a retrieval algorithm.\n"
        "Memory Selection\nThe method filters records using a retrieval module.\n"
        "[page 3]\nExperiments\nThe benchmark contains 12 instances."
    )

    packet = build_reading_packet(artifact, char_budget=1000)

    methods = [c for c in packet.chunks if c.role == "method"]
    assert methods
    assert any("two modules" in c.text for c in methods)
    assert any(c.metadata.get("heading") == "Memory Selection" for c in methods)


def test_bibliography_titles_and_years_cannot_end_reference_state() -> None:
    artifact = _artifact(
        "[page 1]\n3 Method\nA framework.\n[page 8]\nReferences\n"
        "2023. Another Framework for Experimental Evaluation\nA citation description.\n"
        "Memory Selection\nA cited paper describes a method.\n"
        "[page 10]\nAppendix A\nExtra evaluation protocol."
    )

    chunks = build_paper_sections(artifact)

    assert all(c.role == "references" for c in chunks if c.page_start == 8)
    assert any(c.role != "references" for c in chunks if c.page_start == 10)


def test_short_figure_labels_do_not_each_compete_for_a_section_budget() -> None:
    artifact = _artifact(
        "3 Method\nThe pipeline has several stages.\n"
        "Input Records\nCandidate Records\nOutput Records\n"
        "4 Experiments\nThe evaluation used 12 instances."
    )

    chunks = build_paper_sections(artifact)

    assert len(chunks) == 2


def test_unused_budget_extends_complete_sentences_not_partial_words() -> None:
    artifact = _artifact(
        "Abstract\nA study.\n3 Method\n" + "This is a complete method step.\n" * 8
        + "4 Results\n" + "This is a complete result statement.\n" * 8
        + "5 Limitations\nOnly simulated data were evaluated."
    )
    packet = build_reading_packet(artifact, char_budget=1000)

    assert sum(len(c.text) for c in packet.chunks) == sum(
        len(c.text) for c in build_paper_sections(artifact)
    )


def test_single_section_can_use_available_budget_without_old_page_prefix_cap() -> None:
    artifact = _artifact("3 Method\n" + "The pipeline has two explicit stages.\n" * 80)
    packet = build_reading_packet(artifact, char_budget=4000)

    assert packet.chunks[0].text == artifact.text
    assert not packet.warnings or all(
        "section heading not identified" in w for w in packet.warnings
    )


def test_supplied_section_index_does_not_replace_original_text() -> None:
    sections = [PaperSectionChunk(role=role, page_start=i, page_end=i, text=(
        f"{i} {role}\n" + "A complete statement about a fixed evaluation protocol. " * 3
    ))
                for i, role in enumerate(("abstract", "method", "experiments_results",
                                          "limitations_conclusion"), 1)]
    packet = build_reading_packet(_artifact("A study."), sections=sections, char_budget=600)

    assert packet.source_text == "A study."
    assert "SOURCE TEXT\nA study.\nEND SOURCE TEXT" in render_reading_packet(packet)
