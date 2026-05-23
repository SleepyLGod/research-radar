from research_radar.config import TopicConfig
from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.orchestrator import DiscoveryOrchestrator
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType


class RecordingConnector:
    def __init__(
        self,
        name: str,
        source_type: SourceType,
        url: str,
        calls: list[str],
    ) -> None:
        self.name = name
        self._source_type = source_type
        self._url = url
        self._calls = calls
        self.queries: list[str] = []

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        self._calls.append(self.name)
        self.queries = context.topic.queries
        return [
            SourceCandidate(
                title=f"{self.name} agent memory result",
                url=self._url,
                source_type=self._source_type,
                source_name=self.name,
                summary="An agent memory benchmark paper.",
                score=1.0,
            )
        ]


class FailingConnector:
    name = "semantic_scholar"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        raise DiscoveryError("upstream unavailable")


def test_discovery_orchestrator_runs_primary_sources_before_web_and_repos() -> None:
    calls: list[str] = []
    github = RecordingConnector(
        "github",
        SourceType.REPOSITORY,
        "https://github.com/example/agent-memory",
        calls,
    )
    web = RecordingConnector(
        "web_search",
        SourceType.WEB,
        "https://example.com/agent-memory",
        calls,
    )
    arxiv = RecordingConnector(
        "arxiv",
        SourceType.PAPER,
        "https://arxiv.org/abs/2604.01707",
        calls,
    )
    openalex = RecordingConnector(
        "openalex",
        SourceType.PAPER,
        "https://openalex.org/W123",
        calls,
    )
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory"],
        priority_sources=["github.com"],
    )

    result = DiscoveryOrchestrator([github, web, openalex, arxiv]).discover(
        topic,
        limit=2,
        trusted_domains=["arxiv.org"],
    )

    assert calls == ["openalex", "arxiv", "web_search", "github"]
    assert result.stage_counts["primary_sources"] == 2
    assert result.stage_counts["web_search"] == 1
    assert result.stage_counts["repositories"] == 1
    assert result.provider_counts == {
        "openalex": 1,
        "arxiv": 1,
        "web_search": 1,
        "github": 1,
    }


def test_discovery_orchestrator_adds_provenance_metadata() -> None:
    calls: list[str] = []
    arxiv = RecordingConnector(
        "arxiv",
        SourceType.PAPER,
        "https://arxiv.org/abs/2604.01707",
        calls,
    )
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory"],
        priority_sources=["arxiv.org"],
    )

    result = DiscoveryOrchestrator([arxiv]).discover(
        topic,
        limit=1,
        trusted_domains=["openreview.net"],
    )

    metadata = result.candidates[0].metadata
    assert metadata["discovery_stage"] == "primary_sources"
    assert metadata["discovery_provider"] == "arxiv"
    assert metadata["matched_query"] == "agent memory"
    assert metadata["trusted_domain_match"] == "arxiv.org"
    assert "Discovered by arxiv" in metadata["selection_rationale"]


def test_discovery_orchestrator_preserves_paper_query_expansion() -> None:
    calls: list[str] = []
    arxiv = RecordingConnector(
        "arxiv",
        SourceType.PAPER,
        "https://arxiv.org/abs/2604.01707",
        calls,
    )
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory"],
        paper_queries=["Memory in the LLM Era"],
    )

    result = DiscoveryOrchestrator([arxiv]).discover(topic, limit=1)

    assert arxiv.queries == [
        "Memory in the LLM Era",
        "agent memory",
        "agent memory paper",
        "agent memory benchmark",
        "agent memory survey",
        "agent memory arxiv",
    ]
    assert result.query_expansions["arxiv"]["discovery_stage"] == "primary_sources"


def test_discovery_orchestrator_keeps_running_after_connector_failure() -> None:
    calls: list[str] = []
    arxiv = RecordingConnector(
        "arxiv",
        SourceType.PAPER,
        "https://arxiv.org/abs/2604.01707",
        calls,
    )
    topic = TopicConfig(id="agent-memory", queries=["agent memory"])

    result = DiscoveryOrchestrator([FailingConnector(), arxiv]).discover(topic, limit=1)

    assert [candidate.source_name for candidate in result.candidates] == ["arxiv"]
    assert result.findings[0].severity == "warning"
    assert result.findings[0].metadata["kind"] == "discovery_failed"
    assert result.findings[0].metadata["discovery_stage"] == "primary_sources"


def test_discovery_orchestrator_treats_web_search_failure_as_warning() -> None:
    class FailingWebConnector:
        name = "web_search"

        def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
            raise DiscoveryError("search unavailable")

    calls: list[str] = []
    arxiv = RecordingConnector(
        "arxiv",
        SourceType.PAPER,
        "https://arxiv.org/abs/2604.01707",
        calls,
    )
    topic = TopicConfig(id="agent-memory", queries=["agent memory"])

    result = DiscoveryOrchestrator([FailingWebConnector(), arxiv]).discover(topic, limit=1)

    assert [candidate.source_name for candidate in result.candidates] == ["arxiv"]
    assert result.findings[0].severity == "warning"
    assert result.findings[0].metadata["kind"] == "discovery_failed"
    assert result.findings[0].metadata["discovery_stage"] == "web_search"


def test_discovery_orchestrator_dedupes_web_paper_against_primary_source() -> None:
    class ArxivPaperConnector:
        name = "arxiv"

        def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
            return [
                SourceCandidate(
                    title="MemBench",
                    url="https://arxiv.org/abs/2506.21605v1",
                    canonical_id="2506.21605v1",
                    source_type=SourceType.PAPER,
                    source_name=self.name,
                    summary="An agent memory benchmark paper.",
                    score=1.7,
                )
            ]

    class WebPaperConnector:
        name = "web_search"

        def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
            return [
                SourceCandidate(
                    title="MemBench arXiv HTML",
                    url="https://arxiv.org/abs/2506.21605v1",
                    canonical_id="2506.21605v1",
                    source_type=SourceType.PAPER,
                    source_name=self.name,
                    summary="The same paper discovered through web search.",
                    score=1.6,
                    metadata={"search_provider": "tavily"},
                )
            ]

    result = DiscoveryOrchestrator([WebPaperConnector(), ArxivPaperConnector()]).discover(
        TopicConfig(id="agent-memory", queries=["agent memory"]),
        limit=1,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source_name == "arxiv"
    assert result.candidates[0].source_type == SourceType.PAPER
    assert result.duplicate_count == 1
