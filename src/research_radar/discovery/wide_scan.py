"""Wide-scan and source-selection audit artifacts."""

from __future__ import annotations

from collections import Counter

from research_radar.discovery.source_selection import (
    source_selection_key,
    source_selection_score,
)
from research_radar.models import SourceCandidate


def build_wide_scan(candidates: list[SourceCandidate]) -> dict[str, object]:
    """Summarize broad discovery results without creating factual claims."""

    return {
        "source_count": len(candidates),
        "stage_counts": _counter(candidates, "discovery_stage"),
        "provider_counts": _counter(candidates, "discovery_provider"),
        "role_counts": _role_counts(candidates),
        "relevance_counts": _relevance_counts(candidates),
        "top_sources": [_source_row(candidate) for candidate in _top_sources(candidates)],
        "unsupported_or_rejected_claims": [
            "Wide-scan source frequency is not evidence of claim truth.",
            "Repository popularity is not paper novelty.",
            "A matching title alone is not enough for publishable analysis.",
        ],
    }


def build_source_selection_report(
    candidates: list[SourceCandidate],
    selected: list[SourceCandidate],
    *,
    source_intent: str,
    deep_reading_status_by_url: dict[str, str] | None = None,
) -> dict[str, object]:
    """Render source selection rationale as a machine-readable artifact."""

    selected_urls = {candidate.url for candidate in selected}
    status_map = deep_reading_status_by_url or {}
    rows = []
    for candidate in sorted(
        candidates,
        key=lambda item: source_selection_key(item, source_intent=source_intent),
        reverse=True,
    ):
        deep_status = status_map.get(candidate.url, "not_attempted")
        row = _source_row(candidate)
        row["selected_for_deep_reading"] = candidate.url in selected_urls
        row["attempted_for_deep_reading"] = deep_status != "not_attempted"
        row["deep_reading_status"] = deep_status
        row["selection_score"] = round(
            source_selection_score(candidate, source_intent=source_intent),
            3,
        )
        row["selection_reason"] = _selection_reason(candidate, row["selected_for_deep_reading"])
        rows.append(row)
    return {
        "source_intent": source_intent,
        "selected_count": len(selected),
        "selected_sources": [_source_row(candidate) for candidate in selected],
        "ranked_sources": rows,
    }


def _top_sources(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            float(candidate.metadata.get("relevance", {}).get("score", 0.0)),
            float(candidate.metadata.get("source_quality", {}).get("score", 0.0)),
            float(candidate.score),
        ),
        reverse=True,
    )[:12]


def _source_row(candidate: SourceCandidate) -> dict[str, object]:
    relevance = candidate.metadata.get("relevance", {})
    role = candidate.metadata.get("source_role", {})
    quality = candidate.metadata.get("source_quality", {})
    centrality = candidate.metadata.get("source_centrality", {})
    return {
        "title": candidate.title,
        "url": candidate.url,
        "source_type": candidate.source_type.value,
        "source_name": candidate.source_name,
        "discovery_stage": candidate.metadata.get("discovery_stage"),
        "discovery_provider": candidate.metadata.get("discovery_provider"),
        "matched_query": candidate.metadata.get("matched_query"),
        "role": role.get("role"),
        "role_reason": role.get("reason"),
        "relevance_status": relevance.get("status"),
        "relevance_score": relevance.get("score"),
        "relevance_reason": relevance.get("reason"),
        "quality_score": quality.get("score"),
        "quality_reason": quality.get("reason"),
        "centrality_score": centrality.get("score"),
        "centrality_reason": centrality.get("reason"),
        "centrality_positive_signals": centrality.get("positive_signals", []),
        "centrality_negative_signals": centrality.get("negative_signals", []),
    }


def _selection_reason(candidate: SourceCandidate, selected: bool) -> str:
    role = candidate.metadata.get("source_role", {}).get("role")
    relevance = candidate.metadata.get("relevance", {})
    quality = candidate.metadata.get("source_quality", {})
    centrality = candidate.metadata.get("source_centrality", {})
    prefix = "selected" if selected else "not selected"
    return (
        f"{prefix}: role={role}, relevance={relevance.get('score')}, "
        f"quality={quality.get('score')}, centrality={centrality.get('score')}"
    )


def _counter(candidates: list[SourceCandidate], key: str) -> dict[str, int]:
    counter = Counter(str(candidate.metadata.get(key, "unknown")) for candidate in candidates)
    return dict(sorted(counter.items()))


def _role_counts(candidates: list[SourceCandidate]) -> dict[str, int]:
    counter = Counter(
        str(candidate.metadata.get("source_role", {}).get("role", "unknown"))
        for candidate in candidates
    )
    return dict(sorted(counter.items()))


def _relevance_counts(candidates: list[SourceCandidate]) -> dict[str, int]:
    counter = Counter(
        str(candidate.metadata.get("relevance", {}).get("status", "unknown"))
        for candidate in candidates
    )
    return dict(sorted(counter.items()))
