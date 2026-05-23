"""Generic web search adapter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse
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
                _web_result_candidate(
                    title=title,
                    url=url,
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
        failed_queries: list[str] = []
        last_error: Exception | None = None
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
                failed_queries.append(query)
                last_error = exc
                continue
            if not isinstance(result, dict):
                failed_queries.append(query)
                last_error = DiscoveryError(
                    f"Tavily web search returned non-object payload: {query}"
                )
                continue
            candidates.extend(self._parse(result, context, query=query))
        if not candidates and last_error is not None:
            raise DiscoveryError(
                "Tavily web search failed for all queries: "
                f"{_failed_query_summary(failed_queries)}"
            ) from last_error
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
                _web_result_candidate(
                    title=title,
                    url=url,
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


def _web_result_candidate(
    *,
    title: str,
    url: str,
    source_name: str,
    summary: str | None,
    score: float,
    metadata: dict[str, object],
) -> SourceCandidate:
    canonical = _canonical_web_source(url)
    source_type = canonical["source_type"]
    if not isinstance(source_type, SourceType):
        raise DiscoveryError("Web source canonicalization returned invalid source type.")
    return SourceCandidate(
        title=title,
        url=str(canonical["url"]),
        canonical_id=(
            str(canonical["canonical_id"]) if canonical["canonical_id"] is not None else None
        ),
        source_type=source_type,
        source_name=source_name,
        summary=summary,
        score=score,
        metadata={
            **metadata,
            "web_canonicalization": {
                "source_type": source_type.value,
                "rule": str(canonical["rule"]),
                "original_url": url,
            },
        },
    )


def _canonical_web_source(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    path = parsed.path.strip("/")

    arxiv_id = _arxiv_id_from_path(path)
    if _host_matches(host, "arxiv.org") and arxiv_id is not None:
        return {
            "source_type": SourceType.PAPER,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "canonical_id": arxiv_id,
            "rule": "arxiv",
        }

    if _host_matches(host, "aclanthology.org") and path:
        acl_id = path.removesuffix(".pdf").strip("/")
        return {
            "source_type": SourceType.PAPER,
            "url": url,
            "canonical_id": f"ACL:{acl_id}",
            "rule": "acl_anthology",
        }

    if _host_matches(host, "openreview.net") and path == "forum":
        paper_id = parse_qs(parsed.query).get("id", [""])[0]
        if paper_id:
            return {
                "source_type": SourceType.PAPER,
                "url": url,
                "canonical_id": f"OpenReview:{paper_id}",
                "rule": "openreview_forum",
            }

    github_repo = _github_repo(host, path)
    if github_repo is not None:
        owner, repo = github_repo
        return {
            "source_type": SourceType.REPOSITORY,
            "url": f"https://github.com/{owner}/{repo}",
            "canonical_id": f"github:{owner.casefold()}/{repo.casefold()}",
            "rule": "github_repo",
        }

    return {
        "source_type": SourceType.WEB,
        "url": url,
        "canonical_id": None,
        "rule": "none",
    }


def _arxiv_id_from_path(path: str) -> str | None:
    match = re.fullmatch(r"(?:abs|html|pdf)/([^/#?]+)", path, flags=re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).removesuffix(".pdf")
    if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", candidate, flags=re.IGNORECASE):
        return candidate
    return None


def _github_repo(host: str, path: str) -> tuple[str, str] | None:
    if not _host_matches(host, "github.com"):
        return None
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0] in {"topics", "marketplace", "features", "search"}:
        return None
    if parts[1].endswith(".git"):
        parts[1] = parts[1].removesuffix(".git")
    return parts[0], parts[1]


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _failed_query_summary(queries: list[str]) -> str:
    shown = ", ".join(queries[:3])
    if len(queries) > 3:
        return f"{shown}, ..."
    return shown
