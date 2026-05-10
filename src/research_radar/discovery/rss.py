"""RSS and Atom feed discovery connector."""

from __future__ import annotations

from urllib.request import urlopen
from xml.etree import ElementTree

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType


class RssConnector:
    """Discover blog posts from configured feed URLs."""

    name = "rss"

    def __init__(self, feed_urls: list[str]) -> None:
        self._feed_urls = feed_urls

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return candidates from RSS or Atom feeds."""

        candidates: list[SourceCandidate] = []
        for feed_url in self._feed_urls:
            try:
                with urlopen(feed_url, timeout=20) as response:
                    payload = response.read()
            except OSError as exc:
                raise DiscoveryError(f"RSS discovery failed for feed: {feed_url}") from exc
            candidates.extend(self._parse(payload, feed_url, context))
        return sorted(candidates, key=lambda item: item.score, reverse=True)[: context.limit]

    def _parse(
        self,
        payload: bytes,
        feed_url: str,
        context: DiscoveryContext,
    ) -> list[SourceCandidate]:
        root = ElementTree.fromstring(payload)
        if root.tag.endswith("rss"):
            items = root.findall("./channel/item")
            return [self._rss_item(item, feed_url, context) for item in items if item is not None]
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        return [
            self._atom_entry(entry, feed_url, context, ns)
            for entry in entries
            if entry is not None
        ]

    def _rss_item(
        self,
        item: ElementTree.Element,
        feed_url: str,
        context: DiscoveryContext,
    ) -> SourceCandidate:
        title = _child_text(item, "title")
        url = _child_text(item, "link")
        return SourceCandidate(
            title=title,
            url=url,
            source_type=SourceType.BLOG,
            source_name=self.name,
            published_at=_child_text(item, "pubDate"),
            summary=_child_text(item, "description") or None,
            score=0.45 + priority_score(url, context.topic.priority_sources),
            metadata={"feed_url": feed_url},
        )

    def _atom_entry(
        self,
        entry: ElementTree.Element,
        feed_url: str,
        context: DiscoveryContext,
        ns: dict[str, str],
    ) -> SourceCandidate:
        title = _child_text(entry, "atom:title", ns)
        url = ""
        link = entry.find("atom:link", ns)
        if link is not None:
            url = link.attrib.get("href", "")
        return SourceCandidate(
            title=title,
            url=url,
            source_type=SourceType.BLOG,
            source_name=self.name,
            published_at=_child_text(entry, "atom:updated", ns),
            summary=_child_text(entry, "atom:summary", ns) or None,
            score=0.45 + priority_score(url, context.topic.priority_sources),
            metadata={"feed_url": feed_url},
        )


def _child_text(
    element: ElementTree.Element,
    path: str,
    ns: dict[str, str] | None = None,
) -> str:
    child = element.find(path, ns or {})
    if child is None or child.text is None:
        return ""
    return child.text.strip()
