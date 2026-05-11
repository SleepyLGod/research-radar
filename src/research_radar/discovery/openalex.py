"""OpenAlex discovery connector."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType


class OpenAlexConnector:
    """Discover papers through the OpenAlex Works API."""

    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return OpenAlex work candidates for configured queries."""

        candidates: list[SourceCandidate] = []
        failed_queries: list[str] = []
        last_error: OSError | None = None
        for query in context.topic.queries:
            params = urlencode(
                {
                    "search": query,
                    "per-page": str(context.limit),
                    "sort": "publication_date:desc",
                }
            )
            request = Request(f"{self.endpoint}?{params}", headers=_headers())
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except OSError as exc:
                failed_queries.append(query)
                last_error = exc
                continue
            candidates.extend(self._parse(payload, context))
        if not candidates and last_error is not None:
            raise DiscoveryError(
                "OpenAlex discovery failed for all queries: "
                f"{_failed_query_summary(failed_queries)}"
            ) from last_error
        return candidates

    def _parse(
        self,
        payload: dict[str, object],
        context: DiscoveryContext,
    ) -> list[SourceCandidate]:
        rows = payload.get("results", [])
        if not isinstance(rows, list):
            return []
        candidates: list[SourceCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = row.get("display_name") or row.get("title")
            url = _source_url(row)
            if not isinstance(title, str) or not url:
                continue
            candidates.append(
                SourceCandidate(
                    title=title,
                    url=url,
                    canonical_id=_canonical_id(row),
                    source_type=SourceType.PAPER,
                    source_name=self.name,
                    authors=_authors(row),
                    published_at=_published_at(row),
                    summary=_abstract(row),
                    score=0.76 + priority_score(url, context.topic.priority_sources),
                    metadata={
                        "openalex_id": row.get("id"),
                        "doi": row.get("doi"),
                        "type": row.get("type"),
                        "cited_by_count": row.get("cited_by_count"),
                    },
                )
            )
        return candidates


def _headers() -> dict[str, str]:
    return {"User-Agent": "ResearchRadar/0.0.0"}


def _source_url(row: dict[str, object]) -> str | None:
    primary_location = row.get("primary_location")
    if isinstance(primary_location, dict):
        landing_page_url = primary_location.get("landing_page_url")
        if isinstance(landing_page_url, str) and landing_page_url:
            return landing_page_url
    doi = row.get("doi")
    if isinstance(doi, str) and doi:
        return doi
    openalex_id = row.get("id")
    if isinstance(openalex_id, str) and openalex_id:
        return openalex_id
    return None


def _canonical_id(row: dict[str, object]) -> str | None:
    doi = row.get("doi")
    if isinstance(doi, str) and doi:
        return f"DOI:{doi.removeprefix('https://doi.org/')}"
    openalex_id = row.get("id")
    if isinstance(openalex_id, str) and openalex_id:
        return f"OpenAlex:{openalex_id.rsplit('/', 1)[-1]}"
    return None


def _authors(row: dict[str, object]) -> list[str]:
    authors = []
    authorships = row.get("authorships", [])
    if not isinstance(authorships, list):
        return authors
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            authors.append(author["display_name"])
    return authors


def _published_at(row: dict[str, object]) -> str | None:
    publication_date = row.get("publication_date")
    if isinstance(publication_date, str) and publication_date:
        return publication_date
    publication_year = row.get("publication_year")
    if isinstance(publication_year, int):
        return str(publication_year)
    return None


def _abstract(row: dict[str, object]) -> str | None:
    inverted = row.get("abstract_inverted_index")
    if not isinstance(inverted, dict) or not inverted:
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        if not isinstance(word, str) or not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions[index] = word
    if not positions:
        return None
    return " ".join(positions[index] for index in sorted(positions))


def _failed_query_summary(queries: list[str]) -> str:
    shown = ", ".join(queries[:3])
    if len(queries) > 3:
        return f"{shown}, ..."
    return shown
