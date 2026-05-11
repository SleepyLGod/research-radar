from research_radar.discovery.source_role import classify_source_role
from research_radar.models import SourceCandidate, SourceType


def test_arxiv_paper_is_primary_paper() -> None:
    source = SourceCandidate(
        title="Memory in the LLM Era",
        url="https://arxiv.org/abs/2604.01707",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="A modular paper about agent memory systems.",
    )

    scored = classify_source_role(source)

    assert scored.metadata["source_role"]["role"] == "primary_paper"


def test_curated_collection_is_survey_or_list() -> None:
    source = SourceCandidate(
        title="Awesome Agent Memory",
        url="https://github.com/example/awesome-agent-memory",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="A curated collection of agent memory systems, benchmarks, and papers.",
    )

    scored = classify_source_role(source)

    assert scored.metadata["source_role"]["role"] == "survey_or_list"
    assert scored.metadata["source_role"]["deep_read_priority"] == 50


def test_benchmark_repository_outranks_resource_list() -> None:
    benchmark = classify_source_role(
        SourceCandidate(
            title="Agent Memory Benchmark",
            url="https://github.com/example/agent-memory-benchmark",
            source_type=SourceType.REPOSITORY,
            source_name="github",
            summary="Benchmark implementation for persistent recall in agents.",
        )
    )
    resource_list = classify_source_role(
        SourceCandidate(
            title="Awesome Agent Memory",
            url="https://github.com/example/awesome-agent-memory",
            source_type=SourceType.REPOSITORY,
            source_name="github",
            summary="Curated collection of agent memory resources.",
        )
    )

    assert benchmark.metadata["source_role"]["role"] == "implementation_repo"
    assert (
        benchmark.metadata["source_role"]["deep_read_priority"]
        > resource_list.metadata["source_role"]["deep_read_priority"]
    )


def test_regular_repository_is_implementation_fallback() -> None:
    source = SourceCandidate(
        title="go-agent-memory",
        url="https://github.com/example/go-agent-memory",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Agent memory storage service.",
    )

    scored = classify_source_role(source)

    assert scored.metadata["source_role"]["role"] == "implementation_repo"
    assert scored.metadata["source_role"]["reason"] == "repository source"
