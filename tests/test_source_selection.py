from dataclasses import replace

from research_radar.config import TopicConfig
from research_radar.discovery.source_centrality import score_source_centrality
from research_radar.discovery.source_role import classify_source_role
from research_radar.discovery.source_selection import (
    IMPLEMENTATION_SCAN,
    RESEARCH_BRIEF,
    select_deep_candidates,
)
from research_radar.discovery.wide_scan import build_source_selection_report
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


def test_research_brief_does_not_fallback_to_repo_without_viable_paper() -> None:
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

    assert selected == []


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


def test_research_brief_prefers_central_rag_paper_over_domain_application() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation evaluation benchmark"],
        concept_groups={
            "agent_context": ["RAG", "retrieval augmented generation"],
            "memory_mechanism": ["retrieval pipeline", "grounded generation system"],
            "evaluation_signal": ["RAG benchmark", "RAG evaluation"],
        },
    )
    general = score_source_centrality(
        _candidate(
            "RAG Systems Evaluation Benchmark",
            SourceType.PAPER,
            "A general retrieval augmented generation evaluation benchmark for RAG systems.",
            relevance=0.72,
        ),
        topic,
    )
    legal = score_source_centrality(
        _candidate(
            "Fine-grained Claim-level RAG Benchmark for Law",
            SourceType.PAPER,
            "A legal RAG benchmark for law documents and legal retrieval tasks.",
            relevance=0.9,
        ),
        topic,
    )

    selected = select_deep_candidates([legal, general], 1, source_intent=RESEARCH_BRIEF)

    assert selected == [general]
    assert general.metadata["source_centrality"]["score"] > legal.metadata[
        "source_centrality"
    ]["score"]
    assert legal.metadata["source_centrality"]["negative_signals"]


def test_high_relevance_paper_beats_barely_viable_high_centrality_paper() -> None:
    high_relevance = _candidate(
        "Specific Agent Memory Benchmark",
        SourceType.PAPER,
        "A strongly matching paper about agent memory benchmark evaluation.",
        relevance=0.95,
        centrality=0.10,
    )
    barely_viable = _candidate(
        "Broad Memory Framework",
        SourceType.PAPER,
        "A broader framework with high centrality metadata.",
        relevance=0.61,
        centrality=1.0,
    )

    selected = select_deep_candidates(
        [barely_viable, high_relevance],
        1,
        source_intent=RESEARCH_BRIEF,
    )

    assert selected == [high_relevance]


def test_source_selection_report_order_matches_actual_selection_order() -> None:
    stronger = _candidate(
        "Grounded Agent Memory Benchmark",
        SourceType.PAPER,
        "A strongly matching paper about agent memory benchmark evaluation.",
        relevance=0.86,
        centrality=0.60,
    )
    weaker = _candidate(
        "General Memory Survey",
        SourceType.PAPER,
        "A barely viable but more central memory survey.",
        relevance=0.61,
        centrality=0.90,
    )

    selected = select_deep_candidates([weaker, stronger], 1, source_intent=RESEARCH_BRIEF)
    report = build_source_selection_report(
        [weaker, stronger],
        selected,
        source_intent=RESEARCH_BRIEF,
    )

    ranked_titles = [row["title"] for row in report["ranked_sources"]]
    selected_titles = [candidate.title for candidate in selected]
    assert ranked_titles[: len(selected_titles)] == selected_titles


def test_research_brief_penalizes_language_specific_rag_benchmark() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation evaluation benchmark"],
        concept_groups={
            "agent_context": ["RAG", "retrieval augmented generation"],
            "memory_mechanism": ["retrieval pipeline", "grounded generation system"],
            "evaluation_signal": ["RAG benchmark", "RAG evaluation"],
        },
    )
    general = score_source_centrality(
        _candidate(
            "RAGChecker: A Fine-grained Framework for Diagnosing RAG",
            SourceType.PAPER,
            "A general framework with metrics for retrieval augmented generation evaluation.",
            relevance=0.8,
        ),
        topic,
    )
    russian_news = score_source_centrality(
        _candidate(
            "DRAGON: Dynamic RAG Benchmark On News",
            SourceType.PAPER,
            "A RAG benchmark focused on Russian news corpora and Russian language.",
            relevance=1.0,
        ),
        topic,
    )

    selected = select_deep_candidates(
        [russian_news, general],
        1,
        source_intent=RESEARCH_BRIEF,
    )

    assert selected == [general]
    assert russian_news.metadata["source_centrality"]["negative_signals"]


def test_domain_specific_rag_is_not_penalized_for_legal_topic() -> None:
    topic = TopicConfig(
        id="legal-rag",
        queries=["legal RAG systems"],
        paper_queries=["legal retrieval augmented generation benchmark"],
        concept_groups={
            "agent_context": ["legal RAG", "retrieval augmented generation"],
            "memory_mechanism": ["legal retrieval"],
            "evaluation_signal": ["benchmark"],
        },
    )

    legal = score_source_centrality(
        _candidate(
            "Fine-grained Claim-level RAG Benchmark for Law",
            SourceType.PAPER,
            "A legal RAG benchmark for law documents and legal retrieval tasks.",
            relevance=0.9,
        ),
        topic,
    )

    assert legal.metadata["source_centrality"]["score"] > 0.3
    assert legal.metadata["source_centrality"]["negative_signals"] == []


def test_domain_synonyms_do_not_penalize_requested_domain_topics() -> None:
    cases = [
        (
            "financial-rag",
            "financial RAG systems",
            "Finance RAG Benchmark",
            "A finance retrieval augmented generation benchmark for financial reports.",
        ),
        (
            "healthcare-rag",
            "healthcare RAG systems",
            "Medical RAG Benchmark",
            "A medical retrieval augmented generation benchmark for clinical records.",
        ),
        (
            "commerce-rag",
            "commerce RAG systems",
            "E-commerce RAG Benchmark",
            "A retail retrieval augmented generation benchmark for e-commerce catalogs.",
        ),
    ]
    for topic_id, query, title, summary in cases:
        topic = TopicConfig(
            id=topic_id,
            queries=[query],
            paper_queries=[f"{query} benchmark"],
            concept_groups={
                "agent_context": ["RAG", "retrieval augmented generation"],
                "memory_mechanism": ["retrieval"],
                "evaluation_signal": ["benchmark"],
            },
        )

        scored = score_source_centrality(
            _candidate(title, SourceType.PAPER, summary, relevance=0.9),
            topic,
        )

        assert scored.metadata["source_centrality"]["negative_signals"] == []


def test_negative_concept_aliases_do_not_exempt_domain_penalty() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation benchmark"],
        concept_groups={
            "agent_context": ["RAG", "retrieval augmented generation"],
            "evaluation_signal": ["benchmark"],
            "negative_application_noise": ["finance"],
        },
    )

    scored = score_source_centrality(
        _candidate(
            "Finance RAG Benchmark",
            SourceType.PAPER,
            "A finance retrieval augmented generation benchmark for financial reports.",
            relevance=0.9,
        ),
        topic,
    )

    assert scored.metadata["source_centrality"]["negative_signals"]


def test_source_centrality_metadata_is_attached() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory"],
        paper_queries=["agent memory benchmark"],
        concept_groups={
            "agent_context": ["agent memory"],
            "memory_mechanism": ["long-term memory"],
            "evaluation_signal": ["benchmark"],
        },
    )

    scored = score_source_centrality(
        _candidate(
            "Agent Memory Benchmark",
            SourceType.PAPER,
            "A benchmark paper about long-term memory for agents.",
            relevance=0.8,
        ),
        topic,
    )

    centrality = scored.metadata["source_centrality"]
    assert centrality["score"] > 0
    assert centrality["positive_signals"]
    assert "reason" in centrality


def test_source_centrality_normalizes_source_name_for_canonical_signal() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory"],
        paper_queries=[],
    )
    source = _candidate(
        "Agent Memory Paper",
        SourceType.PAPER,
        "A paper about agent memory.",
        relevance=0.8,
    )
    source = replace(source, source_name="ArXiv", url="https://example.com/paper")

    scored = score_source_centrality(source, topic)

    assert "canonical_paper_source=arxiv" in scored.metadata["source_centrality"][
        "positive_signals"
    ]


def _candidate(
    title: str,
    source_type: SourceType,
    summary: str,
    *,
    relevance: float,
    centrality: float | None = None,
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
    metadata = {
        **candidate.metadata,
        "relevance": {"status": "relevant", "score": relevance},
    }
    if centrality is not None:
        metadata["source_centrality"] = {
            "score": centrality,
            "positive_signals": ["fixture"],
            "negative_signals": [],
            "reason": "fixture centrality",
        }
    return replace(
        candidate,
        metadata=metadata,
    )
