"""Typed data models shared across ResearchRadar subsystems."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__version__ = "0.1.0"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    """Convert a dataclass value to a JSON-friendly dictionary."""

    result = asdict(value)
    return _json_ready(result)


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


class SourceType(StrEnum):
    """Supported source categories."""

    PAPER = "paper"
    BLOG = "blog"
    REPOSITORY = "repository"
    WEB = "web"
    RSS = "rss"


class ClaimStatus(StrEnum):
    """Verification status for a claim."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NEEDS_REVIEW = "needs_review"
    SPECULATIVE = "speculative"


class ArticleChannel(StrEnum):
    """Supported article rendering channels."""

    MARKDOWN = "markdown"
    WECHAT = "wechat"
    ZHIHU = "zhihu"


@dataclass(frozen=True)
class SourceCandidate:
    """A normalized candidate source found during discovery."""

    title: str
    url: str
    source_type: SourceType
    source_name: str
    discovered_at: datetime = field(default_factory=utc_now)
    canonical_id: str | None = None
    authors: list[str] = field(default_factory=list)
    published_at: str | None = None
    summary: str | None = None
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Artifact:
    """An ingested artifact with extracted text and provenance."""

    source: SourceCandidate
    text: str
    artifact_path: str | None = None
    content_type: str | None = None
    extracted_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceAnchor:
    """A source-backed evidence anchor for a claim."""

    source_url: str
    quote: str
    location: str | None = None
    source_title: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class Claim:
    """A claim that may be included in generated output."""

    text: str
    status: ClaimStatus = ClaimStatus.NEEDS_REVIEW
    evidence: list[EvidenceAnchor] = field(default_factory=list)
    rationale: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_publishable(self) -> bool:
        """Return whether the claim can be used as factual article content."""

        return self.status == ClaimStatus.SUPPORTED and bool(self.evidence)


@dataclass(frozen=True)
class ArticleSection:
    """A platform-neutral article section."""

    title: str
    body: str
    claims: list[Claim] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArticleDraft:
    """A platform-neutral research article draft."""

    title: str
    topic_id: str
    digest: str
    lede: str
    sections: list[ArticleSection]
    claims: list[Claim] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def publishable_claims(self) -> list[Claim]:
        """Return claims that can be used as factual published content."""

        return [claim for claim in self.claims if claim.is_publishable()]


@dataclass(frozen=True)
class ReviewFinding:
    """A model or rule-based review finding."""

    severity: str
    message: str
    claim_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationAction:
    """A follow-up verification task suggested by a reviewer."""

    action_type: str
    reason: str
    claim_index: int | None = None
    claim_text: str | None = None
    query: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunManifest:
    """Durable manifest for a single pipeline run."""

    run_id: str
    topic_id: str
    mode: str
    created_at: datetime = field(default_factory=utc_now)
    source_count: int = 0
    claim_count: int = 0
    publishable_claim_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
