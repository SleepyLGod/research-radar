"""Shared source grouping helpers for rendered daily reports."""

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
