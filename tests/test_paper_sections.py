from research_radar.analysis.paper_reading import paper_reading_prompt
from research_radar.analysis.paper_sections import build_paper_sections, build_reading_packet
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

    packet = build_reading_packet(artifact, char_budget=8_000)
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


def test_references_only_chunks_are_not_prioritized() -> None:
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

    assert all(chunk.role != "references" for chunk in packet.chunks)


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
