"""Presentation-only source curation for public daily reports."""

from __future__ import annotations

from research_radar.compose.source_groups import source_group_for_candidate
from research_radar.discovery.source_selection import (
    RESEARCH_BRIEF,
    RESEARCH_BRIEF_LOW_CENTRALITY_FLOOR,
    source_selection_key,
)
from research_radar.models import SourceCandidate, SourceType

PUBLIC_SOURCE_CAPS = {
    "research_papers": 8,
    "benchmarks": 8,
    "implementation_repos": 3,
    "web_blog_context": 5,
    "other": 3,
}


def select_public_report_sources(
    sources: list[SourceCandidate],
    selected_sources: list[SourceCandidate],
    *,
    source_intent: str,
) -> list[SourceCandidate]:
    """Return curated sources for public reports without changing audit artifacts."""

    if source_intent != RESEARCH_BRIEF:
        return sources

    selected_urls = {source.url for source in selected_sources}
    selected: list[SourceCandidate] = []
    group_counts: dict[str, int] = {}
    for source in sorted(
        sources,
        key=lambda item: (
            item.url in selected_urls,
            source_selection_key(item, source_intent=source_intent),
        ),
        reverse=True,
    ):
        group = source_group_for_candidate(source, _role(source))
        is_selected = source.url in selected_urls
        if not is_selected and _is_duplicate_paper_family(source):
            continue
        if not is_selected and _is_low_centrality_domain_source(source):
            continue
        if not is_selected and group_counts.get(group, 0) >= PUBLIC_SOURCE_CAPS[group]:
            continue
        selected.append(source)
        group_counts[group] = group_counts.get(group, 0) + 1
    return selected


def _is_low_centrality_domain_source(source: SourceCandidate) -> bool:
    if source.source_type != SourceType.PAPER:
        return False
    centrality = source.metadata.get("source_centrality", {})
    if not centrality.get("negative_signals"):
        return False
    return float(centrality.get("score", 0.0)) < RESEARCH_BRIEF_LOW_CENTRALITY_FLOOR


def _is_duplicate_paper_family(source: SourceCandidate) -> bool:
    return source.metadata.get("deep_selection_dedupe", {}).get("status") == "duplicate"


def _role(source: SourceCandidate) -> str:
    role = source.metadata.get("source_role", {}).get("role")
    return str(role) if role is not None else source.source_type.value
