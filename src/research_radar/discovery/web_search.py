"""Generic web search adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType

TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"


class GenericWebSearchConnector:
    """Search adapter for JSON search APIs with a simple `q` parameter."""

    name = "web_search"

    def __init__(self, endpoint: str, headers: dict[str, str] | None = None) -> None:
        self._endpoint = endpoint
        self._headers = headers or {}

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return web candidates from a generic JSON search endpoint."""

        candidates: list[SourceCandidate] = []
        for query in context.topic.queries:
            separator = "&" if "?" in self._endpoint else "?"
            url = f"{self._endpoint}{separator}{urlencode({'q': query, 'limit': context.limit})}"
            request = Request(url, headers=self._headers)
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except OSError as exc:
                raise DiscoveryError(f"Web search failed for query: {query}") from exc
            candidates.extend(self._parse(payload, context))
        return candidates

    def _parse(
        self,
        payload: dict[str, object],
        context: DiscoveryContext,
    ) -> list[SourceCandidate]:
        rows = payload.get("results", payload.get("items", []))
        if not isinstance(rows, list):
            return []
        candidates: list[SourceCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = row.get("title") or row.get("name")
            url = row.get("url") or row.get("link")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            candidates.append(
                SourceCandidate(
                    title=title,
                    url=url,
                    source_type=SourceType.WEB,
                    source_name=self.name,
                    summary=row.get("snippet") if isinstance(row.get("snippet"), str) else None,
                    score=0.35 + priority_score(url, context.topic.priority_sources),
                    metadata={"raw_rank": len(candidates) + 1},
                )
            )
        return candidates


@dataclass(frozen=True)
class TavilyWebSearchConnector:
    """Search adapter for Tavily's `/search` API."""

    api_key: str
    endpoint: str = TAVILY_SEARCH_ENDPOINT
    max_results: int = 5
    search_depth: str = "basic"

    name = "web_search"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return Tavily web candidates for each topic query."""

        candidates: list[SourceCandidate] = []
        for query in context.topic.queries:
            payload = {
                "query": query,
                "max_results": min(context.limit, self.max_results),
                "search_depth": self.search_depth,
                "topic": "general",
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
            }
            request = Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=30) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise DiscoveryError(f"Tavily web search failed for query: {query}") from exc
            if not isinstance(result, dict):
                raise DiscoveryError(f"Tavily web search returned non-object payload: {query}")
            candidates.extend(self._parse(result, context, query=query))
        return candidates

    def _parse(
        self,
        payload: dict[str, object],
        context: DiscoveryContext,
        *,
        query: str,
    ) -> list[SourceCandidate]:
        rows = payload.get("results", [])
        if not isinstance(rows, list):
            return []
        candidates: list[SourceCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = row.get("title")
            url = row.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            content = row.get("content")
            tavily_score = row.get("score")
            score_boost = tavily_score if isinstance(tavily_score, (int, float)) else 0.0
            candidates.append(
                SourceCandidate(
                    title=title,
                    url=url,
                    source_type=SourceType.WEB,
                    source_name=self.name,
                    summary=content if isinstance(content, str) else None,
                    score=0.4
                    + min(float(score_boost), 1.0) * 0.2
                    + priority_score(url, context.topic.priority_sources),
                    metadata={
                        "raw_rank": len(candidates) + 1,
                        "search_provider": "tavily",
                        "search_query": query,
                        "search_depth": self.search_depth,
                        "tavily_score": tavily_score,
                        "request_id": payload.get("request_id"),
                        "response_time": payload.get("response_time"),
                    },
                )
            )
        return candidates
