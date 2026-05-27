"""Load platform-neutral article drafts from run artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from research_radar.exceptions import PublishError
from research_radar.models import (
    ArticleDraft,
    ArticleSection,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
)
from research_radar.storage.files import read_json


def load_article_draft(path: Path) -> ArticleDraft:
    """Load an ArticleDraft JSON artifact."""

    if not path.exists():
        raise PublishError(f"Article draft not found: {path}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise PublishError("Article draft artifact must be a JSON object.")
    try:
        return ArticleDraft(
            title=_required_string(data, "title"),
            topic_id=_required_string(data, "topic_id"),
            digest=_required_string(data, "digest"),
            lede=_required_string(data, "lede"),
            sections=[_section(item) for item in _list(data.get("sections"))],
            claims=[_claim(item) for item in _list(data.get("claims"))],
            created_at=_created_at(data.get("created_at")),
            metadata=_dict(data.get("metadata")),
        )
    except KeyError as exc:
        raise PublishError(f"Article draft is missing required field: {exc.args[0]}") from exc


def _section(data: object) -> ArticleSection:
    if not isinstance(data, dict):
        raise PublishError("Article draft section must be a JSON object.")
    return ArticleSection(
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        claims=[_claim(item) for item in _list(data.get("claims"))],
        metadata=_dict(data.get("metadata")),
    )


def _claim(data: object) -> Claim:
    if not isinstance(data, dict):
        raise PublishError("Article draft claim must be a JSON object.")
    return Claim(
        text=str(data.get("text", "")),
        status=_claim_status(data.get("status")),
        evidence=[_evidence(item) for item in _list(data.get("evidence"))],
        rationale=_optional_string(data.get("rationale")),
        metadata=_dict(data.get("metadata")),
    )


def _evidence(data: object) -> EvidenceAnchor:
    if not isinstance(data, dict):
        raise PublishError("Article draft evidence anchor must be a JSON object.")
    return EvidenceAnchor(
        source_url=str(data.get("source_url", "")),
        quote=str(data.get("quote", "")),
        location=_optional_string(data.get("location")),
        source_title=_optional_string(data.get("source_title")),
        confidence=_confidence(data.get("confidence", 1.0)),
    )


def _claim_status(value: object) -> ClaimStatus:
    try:
        return ClaimStatus(str(value or ClaimStatus.NEEDS_REVIEW.value))
    except ValueError as exc:
        raise PublishError(f"Unsupported claim status in article draft: {value}") from exc


def _created_at(value: object) -> datetime:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise PublishError(f"Invalid article draft created_at value: {value}") from exc
    return datetime.now().astimezone()


def _confidence(value: object) -> float:
    if value is None or value == "":
        return 1.0
    return float(value)


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data[field]
    if value is None or str(value).strip() == "":
        raise PublishError(f"Article draft is missing required field: {field}")
    return str(value)


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
