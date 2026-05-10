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
