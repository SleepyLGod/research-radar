"""Route sources to the right ingestion implementation."""

from __future__ import annotations

from pathlib import Path

from research_radar.ingestion.github_repo import ingest_github_repo
from research_radar.ingestion.html import ingest_html
from research_radar.ingestion.pdf import ingest_pdf
from research_radar.models import Artifact, SourceCandidate, SourceType


def ingest_source(source: SourceCandidate, artifact_dir: Path) -> Artifact:
    """Ingest a source according to its source type."""

    if source.source_type == SourceType.PAPER:
        return ingest_pdf(source, artifact_dir)
    if source.source_type == SourceType.REPOSITORY:
        return ingest_github_repo(source)
    return ingest_html(source)
