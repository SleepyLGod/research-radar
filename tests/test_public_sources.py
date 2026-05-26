from dataclasses import replace

from research_radar.discovery.source_selection import IMPLEMENTATION_SCAN, RESEARCH_BRIEF
from research_radar.models import SourceCandidate, SourceType
from research_radar.pipeline.public_sources import select_public_report_sources


def test_public_sources_keep_central_rag_paper_and_omit_domain_noise() -> None:
    central = _candidate(
        "RAGChecker",
        SourceType.PAPER,
        role="benchmark_paper",
        centrality=0.72,
    )
    legal = _candidate(
        "Fine-grained Claim-level RAG Benchmark for Law",
        SourceType.PAPER,
        role="benchmark_paper",
        centrality=0.42,
        negative_signals=["domain_specific=law, legal"],
    )
    russian_news = _candidate(
        "DRAGON: Dynamic RAG Benchmark On News",
        SourceType.PAPER,
        role="benchmark_paper",
        centrality=0.42,
        negative_signals=["domain_specific=news, russian"],
    )
    food = _candidate(
        "Healthy Eating RAG",
        SourceType.PAPER,
        role="survey_or_list",
        centrality=0.32,
        negative_signals=["domain_specific=eating, food, nutrition"],
    )

    selected = select_public_report_sources(
        [legal, food, russian_news, central],
        [central],
        source_intent=RESEARCH_BRIEF,
    )

    assert selected == [central]


def test_public_sources_keep_central_rag_paper_without_deep_selection() -> None:
    central = _candidate(
        "RAGChecker",
        SourceType.PAPER,
        role="benchmark_paper",
        centrality=0.72,
    )
    legal = _candidate(
        "Fine-grained Claim-level RAG Benchmark for Law",
        SourceType.PAPER,
        role="benchmark_paper",
        centrality=0.42,
        negative_signals=["domain_specific=law, legal"],
    )

    selected = select_public_report_sources(
        [legal, central],
        [],
        source_intent=RESEARCH_BRIEF,
    )

    assert selected == [central]


def test_public_sources_pin_selected_deep_source_even_if_low_centrality() -> None:
    selected_source = _candidate(
        "Selected Domain Paper",
        SourceType.PAPER,
        role="benchmark_paper",
        centrality=0.30,
        negative_signals=["domain_specific=law"],
    )

    selected = select_public_report_sources(
        [selected_source],
        [selected_source],
        source_intent=RESEARCH_BRIEF,
    )

    assert selected == [selected_source]


def test_public_sources_cap_repos_and_web_context() -> None:
    repos = [
        _candidate(f"Repo {index}", SourceType.REPOSITORY, role="implementation_repo")
        for index in range(5)
    ]
    web_sources = [
        _candidate(f"Blog {index}", SourceType.WEB, role="blog_or_web")
        for index in range(8)
    ]

    selected = select_public_report_sources(
        [*repos, *web_sources],
        [],
        source_intent=RESEARCH_BRIEF,
    )

    selected_repos = [source for source in selected if source.source_type == SourceType.REPOSITORY]
    selected_web = [source for source in selected if source.source_type == SourceType.WEB]
    assert len(selected_repos) == 3
    assert len(selected_web) == 5


def test_public_sources_preserve_non_research_brief_behavior() -> None:
    sources = [
        _candidate("Legal RAG", SourceType.PAPER, role="benchmark_paper", centrality=0.2),
        _candidate("Repo", SourceType.REPOSITORY, role="implementation_repo"),
    ]

    selected = select_public_report_sources(
        sources,
        [],
        source_intent=IMPLEMENTATION_SCAN,
    )

    assert selected == sources


def _candidate(
    title: str,
    source_type: SourceType,
    *,
    role: str,
    centrality: float = 0.0,
    negative_signals: list[str] | None = None,
) -> SourceCandidate:
    candidate = SourceCandidate(
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        source_type=source_type,
        source_name="arxiv" if source_type == SourceType.PAPER else "web",
        summary=title,
        score=1.0,
        metadata={
            "relevance": {"status": "relevant", "score": 1.0},
            "source_role": {"role": role},
        },
    )
    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "source_centrality": {
                "score": centrality,
                "positive_signals": [],
                "negative_signals": negative_signals or [],
                "reason": "fixture centrality",
            },
        },
    )
