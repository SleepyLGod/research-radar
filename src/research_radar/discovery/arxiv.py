"""arXiv discovery connector."""

from __future__ import annotations

import re
from urllib.parse import quote_plus
from urllib.request import urlopen
from xml.etree import ElementTree

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType

STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class ArxivConnector:
    """Discover papers through the arXiv Atom API."""

    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return arXiv candidates for configured queries."""

        candidates: list[SourceCandidate] = []
        failed_queries: list[str] = []
        last_error: OSError | None = None
        for query in context.topic.queries:
            url = (
                f"{self.endpoint}?search_query={_search_query(query)}"
                f"&start=0&max_results={context.limit}&sortBy=submittedDate&sortOrder=descending"
            )
            try:
                with urlopen(url, timeout=20) as response:
                    payload = response.read()
            except OSError as exc:
                failed_queries.append(query)
                last_error = exc
                continue
            candidates.extend(self._parse(payload, context))
        if not candidates and last_error is not None:
            raise DiscoveryError(
                f"arXiv discovery failed for all queries: {_failed_query_summary(failed_queries)}"
            ) from last_error
        return candidates

    def _parse(self, payload: bytes, context: DiscoveryContext) -> list[SourceCandidate]:
        root = ElementTree.fromstring(payload)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        candidates = []
        for entry in root.findall("atom:entry", ns):
            title = _text(entry.find("atom:title", ns))
            entry_id = _text(entry.find("atom:id", ns))
            summary = _text(entry.find("atom:summary", ns))
            published = _text(entry.find("atom:published", ns))
            authors = [
                _text(author.find("atom:name", ns))
                for author in entry.findall("atom:author", ns)
                if _text(author.find("atom:name", ns))
            ]
            if not title or not entry_id:
                continue
            candidates.append(
                SourceCandidate(
                    title=" ".join(title.split()),
                    url=entry_id,
                    canonical_id=entry_id.rsplit("/", 1)[-1],
                    source_type=SourceType.PAPER,
                    source_name=self.name,
                    authors=authors,
                    published_at=published,
                    summary=" ".join(summary.split()) if summary else None,
                    score=0.7 + priority_score(entry_id, context.topic.priority_sources),
                )
            )
        return candidates


def _text(element: ElementTree.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _search_query(query: str) -> str:
    terms = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", query)
        if token.casefold() not in STOPWORDS
    ]
    if not terms:
        return f"all:{quote_plus(query)}"
    return "+AND+".join(f"all:{quote_plus(term)}" for term in terms)


def _failed_query_summary(queries: list[str]) -> str:
    shown = ", ".join(queries[:3])
    if len(queries) > 3:
        return f"{shown}, ..."
    return shown
