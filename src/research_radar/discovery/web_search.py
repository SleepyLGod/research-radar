"""Generic web search adapter."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError
from research_radar.models import SourceCandidate, SourceType
from research_radar.security.redaction import redact_text

TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"


class GenericWebSearchConnector:
    """Search adapter for JSON search APIs with a simple `q` parameter."""

    name = "web_search"

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        *,
        timeout_seconds: int = 20,
    ) -> None:
        self._endpoint = endpoint
        self._headers = headers or {}
        self._timeout_seconds = timeout_seconds

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return web candidates from a generic JSON search endpoint."""

        candidates: list[SourceCandidate] = []
        for query in context.topic.queries:
            separator = "&" if "?" in self._endpoint else "?"
            url = f"{self._endpoint}{separator}{urlencode({'q': query, 'limit': context.limit})}"
            request = Request(url, headers=self._headers)
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
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


@dataclass
class TavilyWebSearchConnector:
    """Search adapter for Tavily's `/search` API."""

    api_key: str
    endpoint: str = TAVILY_SEARCH_ENDPOINT
    max_results: int = 5
    search_depth: str = "basic"
    timeout_seconds: int = 30
    diagnostics: dict[str, object] = field(default_factory=dict, init=False)

    name = "web_search"

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return Tavily web candidates for each topic query."""

        candidates: list[SourceCandidate] = []
        failed_queries: list[str] = []
        query_diagnostics: list[dict[str, object]] = []
        last_error: Exception | None = None
        for query in context.topic.queries:
            started = time.monotonic()
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
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                elapsed = time.monotonic() - started
                failed_queries.append(query)
                last_error = exc
                query_diagnostics.append(
                    _query_diagnostic(
                        query=query,
                        status="failed",
                        elapsed_seconds=elapsed,
                        timeout_seconds=self.timeout_seconds,
                        error=exc,
                    )
                )
                continue
            if not isinstance(result, dict):
                elapsed = time.monotonic() - started
                failed_queries.append(query)
                last_error = DiscoveryError(
                    f"Tavily web search returned non-object payload: {query}"
                )
                query_diagnostics.append(
                    _query_diagnostic(
                        query=query,
                        status="invalid_response",
                        elapsed_seconds=elapsed,
                        timeout_seconds=self.timeout_seconds,
                        error=last_error,
                    )
                )
                continue
            elapsed = time.monotonic() - started
            parsed = self._parse(result, context, query=query, elapsed_seconds=elapsed)
            candidates.extend(parsed)
            query_diagnostics.append(
                _query_diagnostic(
                    query=query,
                    status="succeeded",
                    elapsed_seconds=elapsed,
                    timeout_seconds=self.timeout_seconds,
                    candidate_count=len(parsed),
                    provider_response_time=result.get("response_time"),
                )
            )
        self.diagnostics = _connector_diagnostics(
            query_diagnostics,
            candidates,
            provider="tavily",
            timeout_seconds=self.timeout_seconds,
        )
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
        elapsed_seconds: float,
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
                        "query_elapsed_seconds": round(elapsed_seconds, 3),
                        "timeout_seconds": self.timeout_seconds,
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
            **(
                {"pdf_url": str(canonical["pdf_url"])}
                if canonical.get("pdf_url") is not None
                else {}
            ),
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

    if _host_matches(host, "openreview.net") and path in {"forum", "pdf"}:
        paper_id = parse_qs(parsed.query).get("id", [""])[0]
        if paper_id:
            forum_url = f"https://openreview.net/forum?id={paper_id}"
            return {
                "source_type": SourceType.PAPER,
                "url": forum_url,
                "canonical_id": f"OpenReview:{paper_id}",
                "pdf_url": f"https://openreview.net/pdf?id={paper_id}",
                "rule": f"openreview_{path}",
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


def _query_diagnostic(
    *,
    query: str,
    status: str,
    elapsed_seconds: float,
    timeout_seconds: int,
    candidate_count: int = 0,
    provider_response_time: object = None,
    error: Exception | None = None,
) -> dict[str, object]:
    diagnostic: dict[str, object] = {
        "query": query,
        "status": status,
        "candidate_count": candidate_count,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "timeout_seconds": timeout_seconds,
        "slow": elapsed_seconds >= timeout_seconds * 0.8,
    }
    if provider_response_time is not None:
        diagnostic["provider_response_time"] = provider_response_time
    if error is not None:
        diagnostic["error_type"] = type(error).__name__
        diagnostic["error"] = redact_text(str(error))[:300]
    return diagnostic


def _connector_diagnostics(
    query_diagnostics: list[dict[str, object]],
    candidates: list[SourceCandidate],
    *,
    provider: str,
    timeout_seconds: int,
) -> dict[str, object]:
    return {
        "provider": provider,
        "query_count": len(query_diagnostics),
        "successful_query_count": sum(
            1 for item in query_diagnostics if item.get("status") == "succeeded"
        ),
        "failed_query_count": sum(
            1 for item in query_diagnostics if item.get("status") != "succeeded"
        ),
        "slow_query_count": sum(1 for item in query_diagnostics if item.get("slow")),
        "candidate_count": len(candidates),
        "canonical_paper_count": sum(
            1 for candidate in candidates if candidate.source_type == SourceType.PAPER
        ),
        "canonical_repository_count": sum(
            1 for candidate in candidates if candidate.source_type == SourceType.REPOSITORY
        ),
        "generic_web_count": sum(
            1 for candidate in candidates if candidate.source_type == SourceType.WEB
        ),
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": round(
            sum(
                float(item.get("elapsed_seconds", 0.0))
                for item in query_diagnostics
                if isinstance(item.get("elapsed_seconds"), (int, float))
            ),
            3,
        ),
        "queries": query_diagnostics,
    }
