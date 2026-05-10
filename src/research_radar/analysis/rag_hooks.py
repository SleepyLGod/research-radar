"""Optional hooks for citation-backed scientific RAG backends."""

from __future__ import annotations

from typing import Protocol

from research_radar.models import Artifact, EvidenceAnchor


class CitationBackedRag(Protocol):
    """Protocol for optional PaperQA-like retrieval backends."""

    def answer_with_citations(
        self,
        question: str,
        artifacts: list[Artifact],
    ) -> list[EvidenceAnchor]:
        """Return evidence anchors supporting an answer to a research question."""
