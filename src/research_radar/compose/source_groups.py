"""Shared source grouping helpers for rendered daily reports."""

from research_radar.models import SourceCandidate, SourceType

SOURCE_GROUPS = (
    "research_papers",
    "benchmarks",
    "implementation_repos",
    "web_blog_context",
    "other",
)


def group_source_entries(
    raw_sources: list[object],
) -> list[tuple[str, list[dict[object, object]]]]:
    """Group rendered source entries without dropping unknown source groups."""

    grouped: dict[str, list[dict[object, object]]] = {group: [] for group in SOURCE_GROUPS}
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        group = str(item.get("source_group") or "other")
        if group not in grouped:
            group = "other"
        grouped[group].append(item)
    return [(group, grouped[group]) for group in SOURCE_GROUPS]


def source_group_label(group: str, *, language: str) -> str:
    """Return the localized display label for a source group."""

    if language == "zh":
        return {
            "research_papers": "研究论文",
            "benchmarks": "基准 / 评测",
            "implementation_repos": "实现 / 代码仓库",
            "web_blog_context": "网页 / 博客背景",
            "other": "其他来源",
        }.get(group, "其他来源")
    return {
        "research_papers": "Research Papers",
        "benchmarks": "Benchmarks",
        "implementation_repos": "Implementation / Repos",
        "web_blog_context": "Web / Blog Context",
        "other": "Other Sources",
    }.get(group, "Other Sources")


def source_group_for_candidate(source: SourceCandidate, role: str) -> str:
    """Return the rendered source group for a candidate."""

    if role == "primary_paper":
        return "research_papers"
    if role == "benchmark_paper":
        return "benchmarks"
    if source.source_type == SourceType.REPOSITORY or role == "implementation_repo":
        return "implementation_repos"
    if source.source_type == SourceType.PAPER:
        return "research_papers"
    if source.source_type in {SourceType.BLOG, SourceType.WEB, SourceType.RSS}:
        return "web_blog_context"
    if role in {"blog_or_web", "survey_or_list"}:
        return "web_blog_context"
    return "other"
