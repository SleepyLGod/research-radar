"""GitHub repository ingestion."""

from __future__ import annotations

import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from research_radar.exceptions import IngestionError
from research_radar.models import Artifact, SourceCandidate


def ingest_github_repo(source: SourceCandidate) -> Artifact:
    """Fetch public repository metadata and README text."""

    owner_repo = _owner_repo(source.url)
    if owner_repo is None:
        raise IngestionError(f"Not a GitHub repository URL: {source.url}")
    owner, repo = owner_repo
    metadata = _fetch_json(f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}")
    readme = _fetch_readme(owner, repo)
    text = "\n\n".join(
        [
            f"# {metadata.get('full_name', source.title)}",
            str(metadata.get("description") or ""),
            readme,
        ]
    ).strip()
    if not text:
        raise IngestionError(f"No repository text extracted: {source.url}")
    return Artifact(source=source, text=text, content_type="application/vnd.github.repository+json")


def _owner_repo(url: str) -> tuple[str, str] | None:
    marker = "github.com/"
    if marker not in url:
        return None
    path = url.split(marker, 1)[1].strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _fetch_json(url: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ResearchRadar/0.0.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise IngestionError(f"Failed to fetch GitHub metadata: {url}") from exc
    if not isinstance(payload, dict):
        raise IngestionError(f"GitHub response must be an object: {url}")
    return payload


def _fetch_readme(owner: str, repo: str) -> str:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    request = Request(url, headers={"User-Agent": "ResearchRadar/0.0.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
