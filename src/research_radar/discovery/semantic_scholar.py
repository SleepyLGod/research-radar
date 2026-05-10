"""Semantic Scholar discovery connector."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError, SecretError
from research_radar.models import SourceCandidate, SourceType
from research_radar.security.secrets import SecretManager


class SemanticScholarConnector:
    """Discover papers through Semantic Scholar Graph API."""

    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, secrets: SecretManager | None = None) -> None:
        self._secrets = secrets

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return Semantic Scholar paper candidates."""

        candidates: list[SourceCandidate] = []
        for query in context.topic.queries:
            params = urlencode(
                {
                    "query": query,
                    "limit": str(context.limit),
                    "fields": "title,url,abstract,authors,year,publicationDate,externalIds",
                }
            )
            request = Request(f"{self.endpoint}?{params}", headers=self._headers())
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except OSError as exc:
                raise DiscoveryError(
                    f"Semantic Scholar discovery failed for query: {query}"
                ) from exc
            candidates.extend(self._parse(payload, context))
        return candidates

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "ResearchRadar/0.0.0"}
        if self._secrets is None:
            return headers
        try:
            headers["x-api-key"] = self._secrets.get_semantic_scholar_api_key()
        except SecretError:
            pass
        return headers

    def _parse(
        self,
        payload: dict[str, object],
        context: DiscoveryContext,
    ) -> list[SourceCandidate]:
        rows = payload.get("data", [])
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
            authors = []
            for author in row.get("authors", []):
                if isinstance(author, dict) and isinstance(author.get("name"), str):
                    authors.append(author["name"])
            candidates.append(
                SourceCandidate(
                    title=title,
                    url=url,
                    canonical_id=_semantic_id(row),
                    source_type=SourceType.PAPER,
                    source_name=self.name,
                    authors=authors,
                    published_at=str(row.get("publicationDate") or row.get("year") or ""),
                    summary=row.get("abstract") if isinstance(row.get("abstract"), str) else None,
                    score=0.75 + priority_score(url, context.topic.priority_sources),
                    metadata={"external_ids": row.get("externalIds", {})},
                )
            )
        return candidates


def _semantic_id(row: dict[str, object]) -> str | None:
    external_ids = row.get("externalIds")
    if isinstance(external_ids, dict):
        for key in ["DOI", "ArXiv", "CorpusId"]:
            value = external_ids.get(key)
            if isinstance(value, str):
                return f"{key}:{value}"
            if isinstance(value, int):
                return f"{key}:{value}"
    return None
