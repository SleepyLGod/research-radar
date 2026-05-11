from dataclasses import replace

from research_radar.discovery.source_role import classify_source_role
from research_radar.discovery.source_selection import (
    IMPLEMENTATION_SCAN,
    RESEARCH_BRIEF,
    select_deep_candidates,
)
from research_radar.models import SourceCandidate, SourceType


def test_research_brief_selects_paper_over_comparable_repo() -> None:
    paper = _candidate(
        "Careful Agent Memory Paper",
        SourceType.PAPER,
        "A paper about agent memory benchmark evaluation.",
        relevance=0.7,
    )
    repo = _candidate(
        "agent-memory-benchmark",
        SourceType.REPOSITORY,
        "Benchmark implementation for agent memory.",
        relevance=0.9,
    )

    selected = select_deep_candidates([repo, paper], 1, source_intent=RESEARCH_BRIEF)

    assert selected == [paper]


def test_research_brief_selects_benchmark_paper_over_benchmark_repo() -> None:
    paper = _candidate(
        "LLM Reasoning Evaluation Benchmark",
        SourceType.PAPER,
        "A reasoning benchmark paper for evaluating LLMs.",
        relevance=0.65,
    )
    repo = _candidate(
        "reasoning-agent-benchmark",
        SourceType.REPOSITORY,
        "Benchmark code for reasoning agents.",
        relevance=0.8,
    )

    selected = select_deep_candidates([repo, paper], 1, source_intent=RESEARCH_BRIEF)

    assert selected == [paper]


def test_research_brief_falls_back_to_repo_without_viable_paper() -> None:
    low_relevance_paper = _candidate(
        "Agentic Discovery for Test-Time Scaling",
        SourceType.PAPER,
        "A paper about test-time scaling.",
        relevance=0.47,
    )
    repo = _candidate(
        "go-agent-memory",
        SourceType.REPOSITORY,
        "Agent memory implementation with persistent recall.",
        relevance=0.9,
    )

    selected = select_deep_candidates(
        [low_relevance_paper, repo],
        1,
        source_intent=RESEARCH_BRIEF,
    )

    assert selected == [repo]


def test_implementation_scan_keeps_relevance_first_repo_selection() -> None:
    paper = _candidate(
        "Agent Memory Benchmark Paper",
        SourceType.PAPER,
        "A benchmark paper.",
        relevance=0.7,
    )
    repo = _candidate(
        "agent-memory-benchmark",
        SourceType.REPOSITORY,
        "Benchmark implementation for agent memory.",
        relevance=0.9,
    )

    selected = select_deep_candidates([paper, repo], 1, source_intent=IMPLEMENTATION_SCAN)

    assert selected == [repo]


def _candidate(
    title: str,
    source_type: SourceType,
    summary: str,
    *,
    relevance: float,
) -> SourceCandidate:
    candidate = classify_source_role(
        SourceCandidate(
            title=title,
            url=f"https://example.com/{title.lower().replace(' ', '-')}",
            source_type=source_type,
            source_name="arxiv" if source_type == SourceType.PAPER else "github",
            summary=summary,
        )
    )
    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "relevance": {"status": "relevant", "score": relevance},
        },
    )
