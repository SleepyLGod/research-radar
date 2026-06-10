"""Human-facing source display helpers."""

from __future__ import annotations

from collections.abc import Mapping


def source_descriptor(item: Mapping[object, object], *, language: str = "en") -> str:
    """Return a reader-facing source metadata label."""

    parts: list[str] = []
    source_kind = _role_label(
        item.get("role") or item.get("source_type"),
        language=language,
    )
    history_status = _history_status_label(item.get("history_status"), language=language)
    published_at = _plain_value(item.get("published_at"))
    version = _plain_value(item.get("version"))
    if source_kind:
        parts.append(source_kind)
    if history_status:
        parts.append(history_status)
    if published_at:
        parts.append(published_at)
    if version:
        parts.append(version)
    return " · ".join(parts)


def _role_label(value: object, *, language: str) -> str:
    raw = _plain_value(value)
    if not raw:
        return ""
    labels = _ZH_ROLE_LABELS if language == "zh" else _EN_ROLE_LABELS
    return labels.get(raw, _fallback_label(raw))


def _history_status_label(value: object, *, language: str) -> str:
    raw = _plain_value(value)
    if not raw or raw == "not_tracked":
        return ""
    labels = _ZH_HISTORY_LABELS if language == "zh" else _EN_HISTORY_LABELS
    return labels.get(raw, _fallback_label(raw))


def _plain_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _fallback_label(value: str) -> str:
    return value.replace("_", " ").strip()


_EN_ROLE_LABELS = {
    "primary_paper": "Research paper",
    "benchmark_paper": "Benchmark paper",
    "implementation_repo": "Implementation repo",
    "blog_or_web": "Web/blog context",
    "survey_or_list": "Survey/list",
    "paper": "Research paper",
    "repository": "Implementation repo",
    "web": "Web/blog context",
    "rss": "Web/blog context",
    "blog": "Web/blog context",
}

_ZH_ROLE_LABELS = {
    "primary_paper": "研究论文",
    "benchmark_paper": "基准/评测论文",
    "implementation_repo": "实现/代码仓库",
    "blog_or_web": "网页/博客背景",
    "survey_or_list": "综述/列表",
    "paper": "研究论文",
    "repository": "实现/代码仓库",
    "web": "网页/博客背景",
    "rss": "网页/博客背景",
    "blog": "网页/博客背景",
}

_EN_HISTORY_LABELS = {
    "new": "new source",
    "seen": "seen before",
    "version_update": "version update",
}

_ZH_HISTORY_LABELS = {
    "new": "新来源",
    "seen": "历史来源",
    "version_update": "版本更新",
}
