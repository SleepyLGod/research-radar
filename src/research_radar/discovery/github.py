"""GitHub repository discovery connector."""

from __future__ import annotations

import json
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from research_radar.discovery.base import DiscoveryContext
from research_radar.discovery.dedupe import priority_score
from research_radar.exceptions import DiscoveryError, SecretError
from research_radar.models import SourceCandidate, SourceType
from research_radar.security.secrets import SecretManager


class GitHubRepoConnector:
    """Discover repositories through GitHub search."""

    name = "github"
    endpoint = "https://api.github.com/search/repositories"

    def __init__(self, secrets: SecretManager | None = None) -> None:
        self._secrets = secrets

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return GitHub repository candidates."""

        candidates: list[SourceCandidate] = []
        failed_queries: list[str] = []
        last_error: OSError | None = None
        for query in context.topic.queries:
            url = (
                f"{self.endpoint}?q={quote_plus(query)}&sort=updated&order=desc"
                f"&per_page={context.limit}"
            )
            request = Request(url, headers=self._headers())
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
                f"GitHub discovery failed for all queries: {_failed_query_summary(failed_queries)}"
            ) from last_error
        return candidates

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ResearchRadar/0.0.0",
        }
        if self._secrets is None:
            return headers
        try:
            headers["Authorization"] = f"Bearer {self._secrets.get_github_token()}"
        except SecretError:
            pass
        return headers

    def _parse(
        self,
        payload: dict[str, object],
        context: DiscoveryContext,
    ) -> list[SourceCandidate]:
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        candidates: list[SourceCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            full_name = item.get("full_name")
            html_url = item.get("html_url")
            if not isinstance(full_name, str) or not isinstance(html_url, str):
                continue
            candidates.append(
                SourceCandidate(
                    title=full_name,
                    url=html_url,
                    canonical_id=f"github:{full_name.lower()}",
                    source_type=SourceType.REPOSITORY,
                    source_name=self.name,
                    summary=(
                        item.get("description")
                        if isinstance(item.get("description"), str)
                        else None
                    ),
                    score=0.55 + priority_score(html_url, context.topic.priority_sources),
                    metadata={
                        "stars": item.get("stargazers_count"),
                        "forks": item.get("forks_count"),
                        "updated_at": item.get("updated_at"),
                    },
                )
            )
        return candidates


def _failed_query_summary(queries: list[str]) -> str:
    shown = ", ".join(queries[:3])
    if len(queries) > 3:
        return f"{shown}, ..."
    return shown
