"""Candidate deduplication and scoring."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from research_radar.models import SourceCandidate


def canonicalize_url(url: str) -> str:
    """Return a canonical URL for dedupe."""

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def dedupe_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    """Deduplicate candidates by canonical id or URL."""

    seen: set[str] = set()
    result: list[SourceCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        key = candidate.canonical_id or canonicalize_url(candidate.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def priority_score(url: str, priority_sources: list[str]) -> float:
    """Return a score boost for priority source domains."""

    host = urlparse(url).netloc.lower()
    for index, source in enumerate(priority_sources):
        source_host = source.lower()
        if host == source_host or host.endswith("." + source_host):
            return max(0.0, 1.0 - index * 0.05)
    return 0.0
