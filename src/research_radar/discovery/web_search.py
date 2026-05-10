"""Generic web search adapter."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType


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
