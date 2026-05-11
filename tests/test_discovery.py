import json

from research_radar.config import TopicConfig
from research_radar.discovery import arxiv as arxiv_module
from research_radar.discovery import openalex as openalex_module
from research_radar.discovery import semantic_scholar as semantic_scholar_module
from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import dedupe_candidates, priority_score
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


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._payload
