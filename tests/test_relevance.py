from research_radar.config import TopicConfig
from research_radar.discovery.relevance import gate_relevant_sources, score_source
from research_radar.models import SourceCandidate, SourceType


def test_relevance_gate_filters_irrelevant_arxiv_source() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory", "LLM memory benchmark"])
    source = SourceCandidate(
        title="The Kubo-Thermalization Correspondence",
        url="https://arxiv.org/abs/2605.06666",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="Quantum thermalization links long-time equilibration with response theory.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "irrelevant"


def test_relevance_gate_keeps_agent_memory_source() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory", "LLM memory benchmark"])
    source = SourceCandidate(
        title="Mimir",
        url="https://github.com/example/mimir",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Build memory systems for AI agents with persistent recall.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "relevant"


def test_relevance_gate_marks_borderline_source_needs_review() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory", "LLM memory benchmark"])
    source = SourceCandidate(
        title="Why Global LLM Leaderboards Are Misleading",
        url="https://arxiv.org/abs/2605.06656",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="Ranking LLMs via pairwise human feedback can make leaderboards misleading.",
    )

    all_sources, selected, findings = gate_relevant_sources([source], topic)

    assert all_sources[0].metadata["relevance"]["status"] == "needs_review"
    assert selected == []
    assert findings[0].metadata["source_status"] == "needs_review"


def test_relevance_exact_phrase_outranks_weak_single_token_match() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation evaluation benchmark"],
    )
    phrase_source = SourceCandidate(
        title="Evaluating Retrieval-Augmented Generation Systems",
        url="https://arxiv.org/abs/2605.01000",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="A benchmark for retrieval augmented generation evaluation.",
    )
    weak_source = SourceCandidate(
        title="Normalizing Trajectory Models",
        url="https://arxiv.org/abs/2605.01001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="A method for generation in trajectory modeling.",
    )

    phrase = score_source(phrase_source, topic)
    weak = score_source(weak_source, topic)

    assert phrase.metadata["relevance"]["status"] == "relevant"
    assert weak.metadata["relevance"]["status"] != "relevant"
    assert phrase.metadata["relevance"]["score"] > weak.metadata["relevance"]["score"]


def test_relevance_generic_benchmark_wording_is_not_enough_for_viable_paper() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory systems"])
    source = SourceCandidate(
        title="A General Benchmark for Efficient Inference",
        url="https://arxiv.org/abs/2605.01002",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="This benchmark evaluates inference systems without memory agents.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] != "relevant"


def test_relevance_future_dated_paper_requires_review() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation evaluation benchmark"],
    )
    source = SourceCandidate(
        title="Retrieval Augmented Generation Benchmark",
        url="https://example.com/future-paper",
        source_type=SourceType.PAPER,
        source_name="openalex",
        published_at="2999-01-01",
        summary="A benchmark for retrieval augmented generation evaluation.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "needs_review"
    assert scored.metadata["relevance"]["future_publication"] == "2999-01-01"
