"""Deterministic source role classification for deep-reading selection."""

from __future__ import annotations

import re
from dataclasses import replace

from research_radar.models import SourceCandidate, SourceType

PRIMARY_PAPER_PRIORITY = 500
BENCHMARK_PAPER_PRIORITY = 450
BENCHMARK_REPO_PRIORITY = 430
IMPLEMENTATION_REPO_PRIORITY = 150
REPOSITORY_FALLBACK_PRIORITY = 120
BLOG_OR_WEB_PRIORITY = 200
SURVEY_OR_LIST_PRIORITY = 50
NOISE_PRIORITY = 0

LIST_TERMS = {
    "awesome",
    "curated",
    "collection",
    "collections",
    "list",
    "lists",
    "resources",
    "survey",
    "surveys",
}

BENCHMARK_TERMS = {
    "benchmark",
    "benchmarks",
    "dataset",
    "datasets",
    "evaluation",
    "eval",
}

IMPLEMENTATION_TERMS = {
    "framework",
    "library",
    "implementation",
    "toolkit",
    "package",
    "code",
}


def classify_source_role(candidate: SourceCandidate) -> SourceCandidate:
    """Attach source-role metadata used for deep-reading priority."""

    text = _normalized_text(candidate)
    tokens = set(_tokens(text))

    if tokens & LIST_TERMS:
        role = "survey_or_list"
        priority = SURVEY_OR_LIST_PRIORITY
        reason = "resource-list wording"
    elif candidate.source_type == SourceType.PAPER and tokens & BENCHMARK_TERMS:
        role = "benchmark_paper"
        priority = BENCHMARK_PAPER_PRIORITY
        reason = "paper with benchmark or evaluation wording"
    elif candidate.source_type == SourceType.PAPER:
        role = "primary_paper"
        priority = PRIMARY_PAPER_PRIORITY
        reason = "paper source"
    elif candidate.source_type == SourceType.REPOSITORY and tokens & BENCHMARK_TERMS:
        role = "implementation_repo"
        priority = BENCHMARK_REPO_PRIORITY
        reason = "repository with benchmark or evaluation wording"
    elif candidate.source_type == SourceType.REPOSITORY and tokens & IMPLEMENTATION_TERMS:
        role = "implementation_repo"
        priority = IMPLEMENTATION_REPO_PRIORITY
        reason = "repository with implementation wording"
    elif candidate.source_type == SourceType.REPOSITORY:
        role = "implementation_repo"
        priority = REPOSITORY_FALLBACK_PRIORITY
        reason = "repository source"
    elif candidate.source_type in {SourceType.BLOG, SourceType.WEB, SourceType.RSS}:
        role = "blog_or_web"
        priority = BLOG_OR_WEB_PRIORITY
        reason = "web or blog source"
    else:
        role = "noise"
        priority = NOISE_PRIORITY
        reason = "no primary-source signal"

    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "source_role": {
                "role": role,
                "reason": reason,
                "deep_read_priority": priority,
            },
        },
    )


def _normalized_text(candidate: SourceCandidate) -> str:
    return " ".join(
        [
            candidate.title.lower(),
            (candidate.summary or "").lower(),
            candidate.source_name.lower(),
            candidate.source_type.value.lower(),
        ]
    )


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)
