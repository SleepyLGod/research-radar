"""Discovery connector interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from research_radar.config import TopicConfig
from research_radar.models import SourceCandidate


@dataclass(frozen=True)
class DiscoveryContext:
    """Runtime context passed to discovery connectors."""

    topic: TopicConfig
    limit: int = 10
    metadata: dict[str, str] = field(default_factory=dict)


class DiscoveryConnector(Protocol):
    """Protocol for source discovery connectors."""

    name: str

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return source candidates for a topic."""
