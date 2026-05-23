import json

from research_radar.config import TopicConfig
from research_radar.discovery import arxiv as arxiv_module
from research_radar.discovery import openalex as openalex_module
from research_radar.discovery import semantic_scholar as semantic_scholar_module
from research_radar.discovery import web_search as web_search_module
from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import dedupe_candidates, priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType


def test_dedupe_prefers_highest_score() -> None:
    low = SourceCandidate(
        title="Low",
        url="https://example.com/a/",
        source_type=SourceType.WEB,
        source_name="test",
        score=0.1,
    )
    high = SourceCandidate(
        title="High",
        url="https://example.com/a",
        source_type=SourceType.WEB,
        source_name="test",
        score=0.9,
    )

    assert dedupe_candidates([low, high]) == [high]


def test_priority_score_matches_subdomain() -> None:
    assert priority_score("https://export.arxiv.org/abs/1", ["arxiv.org"]) > 0


def test_arxiv_connector_continues_after_one_query_failure(monkeypatch) -> None:
    def fake_urlopen(url: str, timeout: int):
        if "first" in url:
            raise OSError("temporary failure")
        return FakeResponse(
            b"""
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <title>Agent Memory Paper</title>
                <id>https://arxiv.org/abs/2604.01707</id>
                <summary>An agent memory benchmark paper.</summary>
                <published>2026-04-01T00:00:00Z</published>
                <author><name>Ada Researcher</name></author>
              </entry>
            </feed>
            """
        )

    monkeypatch.setattr(arxiv_module, "urlopen", fake_urlopen)
    connector = arxiv_module.ArxivConnector()

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(id="agent-memory", queries=["first", "second"]),
            limit=1,
        )
    )

    assert candidates[0].title == "Agent Memory Paper"


def test_arxiv_connector_requires_query_terms(monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_urlopen(url: str, timeout: int):
        seen_urls.append(url)
        return FakeResponse(
            b"""
            <feed xmlns="http://www.w3.org/2005/Atom">
            </feed>
            """
        )

    monkeypatch.setattr(arxiv_module, "urlopen", fake_urlopen)
    connector = arxiv_module.ArxivConnector()

    connector.discover(
        DiscoveryContext(
            topic=TopicConfig(
                id="rag-systems",
                queries=["retrieval augmented generation benchmark"],
            ),
            limit=1,
        )
    )

    assert "search_query=all:retrieval+AND+all:augmented+AND+all:generation" in seen_urls[0]
    assert "+AND+all:benchmark" in seen_urls[0]


def test_semantic_scholar_connector_continues_after_one_query_failure(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        if "first" in request.full_url:
            raise OSError("temporary failure")
        return FakeResponse(
            json.dumps(
                {
                    "data": [
                        {
                            "title": "Agent Memory Paper",
                            "url": "https://semanticscholar.org/paper/example",
                            "abstract": "An agent memory benchmark paper.",
                            "authors": [{"name": "Ada Researcher"}],
                            "year": 2026,
                            "openAccessPdf": {
                                "url": "https://arxiv.org/pdf/2604.01707.pdf"
                            },
                        }
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(semantic_scholar_module, "urlopen", fake_urlopen)
    connector = semantic_scholar_module.SemanticScholarConnector()

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(id="agent-memory", queries=["first", "second"]),
            limit=1,
        )
    )

    assert candidates[0].title == "Agent Memory Paper"
    assert candidates[0].metadata["pdf_url"] == "https://arxiv.org/pdf/2604.01707.pdf"


def test_openalex_connector_parses_work_candidate(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        return FakeResponse(
            json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W123",
                            "doi": "https://doi.org/10.1234/example",
                            "display_name": "Agent Memory Paper",
                            "publication_date": "2026-04-01",
                            "type": "article",
                            "cited_by_count": 12,
                            "primary_location": {
                                "landing_page_url": "https://doi.org/10.1234/example"
                            },
                            "authorships": [
                                {"author": {"display_name": "Ada Researcher"}},
                            ],
                            "abstract_inverted_index": {
                                "Agent": [0],
                                "memory": [1],
                                "benchmark": [2],
                            },
                        }
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(openalex_module, "urlopen", fake_urlopen)
    connector = openalex_module.OpenAlexConnector()

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(
                id="agent-memory",
                queries=["agent memory"],
                priority_sources=["doi.org"],
            ),
            limit=1,
        )
    )

    candidate = candidates[0]
    assert candidate.title == "Agent Memory Paper"
    assert candidate.url == "https://doi.org/10.1234/example"
    assert candidate.canonical_id == "DOI:10.1234/example"
    assert candidate.authors == ["Ada Researcher"]
    assert candidate.published_at == "2026-04-01"
    assert candidate.summary == "Agent memory benchmark"
    assert candidate.metadata["openalex_id"] == "https://openalex.org/W123"
    assert candidate.metadata["cited_by_count"] == 12


def test_openalex_connector_continues_after_one_query_failure(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        if "first" in request.full_url:
            raise OSError("temporary failure")
        return FakeResponse(
            json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W123",
                            "display_name": "Agent Memory Paper",
                            "publication_year": 2026,
                        }
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(openalex_module, "urlopen", fake_urlopen)
    connector = openalex_module.OpenAlexConnector()

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(id="agent-memory", queries=["first", "second"]),
            limit=1,
        )
    )

    assert candidates[0].title == "Agent Memory Paper"


def test_tavily_web_search_posts_query_and_parses_web_candidates(monkeypatch) -> None:
    seen_requests = []
    seen_timeouts = []

    def fake_urlopen(request, timeout: int):
        seen_requests.append(request)
        seen_timeouts.append(timeout)
        return FakeResponse(
            json.dumps(
                {
                    "results": [
                        {
                            "title": "Agent Memory Project Page",
                            "url": "https://example.com/agent-memory",
                            "content": "An official page about agent memory systems.",
                            "score": 0.9,
                        }
                    ],
                    "response_time": 1.23,
                    "request_id": "req-1",
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
    connector = web_search_module.TavilyWebSearchConnector(
        api_key="tvly-test",
        endpoint="https://api.tavily.test/search",
        max_results=3,
        search_depth="basic",
        timeout_seconds=11,
    )

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(
                id="agent-memory",
                queries=["agent memory systems"],
                priority_sources=["example.com"],
            ),
            limit=2,
        )
    )

    body = json.loads(seen_requests[0].data.decode("utf-8"))
    assert seen_timeouts == [11]
    assert seen_requests[0].headers["Authorization"] == "Bearer tvly-test"
    assert body["query"] == "agent memory systems"
    assert body["max_results"] == 2
    assert body["include_answer"] is False
    assert body["include_raw_content"] is False
    assert candidates[0].source_type == SourceType.WEB
    assert candidates[0].source_name == "web_search"
    assert candidates[0].summary == "An official page about agent memory systems."
    assert candidates[0].metadata["search_provider"] == "tavily"
    assert candidates[0].metadata["search_query"] == "agent memory systems"
    assert candidates[0].metadata["request_id"] == "req-1"
    assert candidates[0].metadata["timeout_seconds"] == 11
    assert connector.diagnostics["provider"] == "tavily"
    assert connector.diagnostics["query_count"] == 1
    assert connector.diagnostics["candidate_count"] == 1
    assert connector.diagnostics["failed_query_count"] == 0


def test_tavily_web_search_canonicalizes_research_source_urls(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        return FakeResponse(
            json.dumps(
                {
                    "results": [
                        {
                            "title": "MemBench arXiv HTML",
                            "url": "https://arxiv.org/html/2506.21605v1",
                            "content": "A paper page.",
                            "score": 0.9,
                        },
                        {
                            "title": "ACL paper PDF",
                            "url": "https://aclanthology.org/2025.findings-acl.989.pdf",
                            "content": "An ACL paper.",
                            "score": 0.8,
                        },
                        {
                            "title": "OpenReview paper",
                            "url": "https://openreview.net/forum?id=LLtUtzSOL5",
                            "content": "An OpenReview paper.",
                            "score": 0.7,
                        },
                        {
                            "title": "Awesome Agent Memory",
                            "url": "https://github.com/TeleAI-UAGI/Awesome-Agent-Memory",
                            "content": "A GitHub repository.",
                            "score": 0.6,
                        },
                        {
                            "title": "Agent memory blog",
                            "url": "https://example.com/agent-memory",
                            "content": "A blog post.",
                            "score": 0.5,
                        },
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
    connector = web_search_module.TavilyWebSearchConnector(api_key="tvly-test")

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(id="agent-memory", queries=["agent memory systems"]),
            limit=5,
        )
    )

    assert candidates[0].source_type == SourceType.PAPER
    assert candidates[0].url == "https://arxiv.org/abs/2506.21605v1"
    assert candidates[0].canonical_id == "2506.21605v1"
    assert candidates[0].metadata["search_provider"] == "tavily"
    assert candidates[0].metadata["web_canonicalization"]["rule"] == "arxiv"
    assert candidates[0].metadata["web_canonicalization"]["original_url"] == (
        "https://arxiv.org/html/2506.21605v1"
    )
    assert candidates[1].source_type == SourceType.PAPER
    assert candidates[1].canonical_id == "ACL:2025.findings-acl.989"
    assert candidates[2].source_type == SourceType.PAPER
    assert candidates[2].canonical_id == "OpenReview:LLtUtzSOL5"
    assert candidates[3].source_type == SourceType.REPOSITORY
    assert candidates[3].url == "https://github.com/TeleAI-UAGI/Awesome-Agent-Memory"
    assert candidates[3].canonical_id == "github:teleai-uagi/awesome-agent-memory"
    assert candidates[4].source_type == SourceType.WEB
    assert candidates[4].metadata["web_canonicalization"]["rule"] == "none"


def test_tavily_web_search_failure_becomes_discovery_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise OSError("network down")

    monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
    connector = web_search_module.TavilyWebSearchConnector(api_key="tvly-test")

    try:
        connector.discover(
            DiscoveryContext(
                topic=TopicConfig(id="agent-memory", queries=["agent memory systems"]),
                limit=2,
            )
        )
    except DiscoveryError as exc:
        assert "Tavily web search failed" in str(exc)
    else:
        raise AssertionError("Expected discovery failure")


def test_tavily_web_search_continues_after_one_query_failure(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        body = json.loads(request.data.decode("utf-8"))
        if body["query"] == "first":
            raise OSError("temporary failure")
        return FakeResponse(
            json.dumps(
                {
                    "results": [
                        {
                            "title": "Agent Memory Paper",
                            "url": "https://arxiv.org/html/2506.21605v1",
                            "content": "A paper about agent memory.",
                            "score": 0.9,
                        }
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
    connector = web_search_module.TavilyWebSearchConnector(api_key="tvly-test")

    candidates = connector.discover(
        DiscoveryContext(
            topic=TopicConfig(id="agent-memory", queries=["first", "second"]),
            limit=1,
        )
    )

    assert len(candidates) == 1
    assert candidates[0].title == "Agent Memory Paper"
    assert candidates[0].source_type == SourceType.PAPER
    assert connector.diagnostics["query_count"] == 2
    assert connector.diagnostics["failed_query_count"] == 1
    assert connector.diagnostics["successful_query_count"] == 1
    assert connector.diagnostics["canonical_paper_count"] == 1
    assert connector.diagnostics["queries"][0]["status"] == "failed"
    assert connector.diagnostics["queries"][0]["error_type"] == "OSError"
    assert connector.diagnostics["queries"][1]["status"] == "succeeded"


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._payload
