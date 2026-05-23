"""Platform-neutral research article draft construction."""

from __future__ import annotations

import re

from research_radar.analysis.source_gist import sanitize_source_gist
from research_radar.evidence.policy import publishable_claims
from research_radar.models import ArticleDraft, ArticleSection, Claim, SourceCandidate, SourceType


def build_daily_draft(
    topic_id: str,
    sources: list[SourceCandidate],
    claims: list[Claim],
    *,
    language: str = "en",
) -> ArticleDraft:
    """Build a platform-neutral daily monitoring draft."""

    verified = publishable_claims(claims)
    source_entries = [_source_entry(source, language=language) for source in sources]

    observation_lines = [_localized_claim_text(claim.text, language=language) for claim in verified]
    lede = _lede(verified, language=language)
    labels = _daily_labels(language)
    return ArticleDraft(
        title=labels["title"].format(topic_id=topic_id),
        topic_id=topic_id,
        digest=lede[:120],
        lede=lede,
        claims=verified,
        sections=[
            ArticleSection(
                title=labels["sources"],
                body=(
                    labels["no_sources"]
                    if not source_entries
                    else ""
                ),
                metadata={"kind": "new_updated_sources", "sources": source_entries},
            ),
            ArticleSection(
                title=labels["observations"],
                body="\n".join(observation_lines) or labels["no_observations"],
                claims=verified,
                metadata={"kind": "verified_observations"},
            ),
            ArticleSection(
                title=labels["evidence"],
                body=_evidence_text(verified, language=language),
                claims=verified,
                metadata={"kind": "evidence_trail"},
            ),
        ],
        metadata={"source_count": len(sources), "draft_type": "daily", "language": language},
    )


def build_weekly_draft(topic_id: str, claims: list[Claim]) -> ArticleDraft:
    """Build a platform-neutral weekly deep-dive draft."""

    verified = publishable_claims(claims)
    lede = _lede(verified)
    return ArticleDraft(
        title=f"{topic_id}: Weekly Research Deep Dive",
        topic_id=topic_id,
        digest=lede[:120],
        lede=lede,
        claims=verified,
        sections=[
            ArticleSection(
                title="One-line conclusion",
                body=lede,
                claims=verified[:1],
            ),
            ArticleSection(
                title="What changed",
                body="\n".join(claim.text for claim in verified) or "No verified change yet.",
                claims=verified,
            ),
            ArticleSection(
                title="Evidence map",
                body=_evidence_text(verified),
                claims=verified,
            ),
        ],
        metadata={"draft_type": "weekly"},
    )


def _lede(claims: list[Claim], *, language: str = "en") -> str:
    if not claims:
        if language == "zh":
            return "没有 claim 通过证据核验，因此这篇草稿会保持为空。"
        return "No claim passed evidence verification, so this draft is intentionally empty."
    return _localized_claim_text(claims[0].text, language=language)


def _daily_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "title": "ResearchRadar 日报：{topic_id}",
            "sources": "新增 / 更新来源",
            "no_sources": "没有新增或更新来源通过报告门槛。",
            "observations": "已核验观察",
            "no_observations": "暂时没有已核验观察。",
            "evidence": "证据链",
        }
    return {
        "title": "ResearchRadar Daily: {topic_id}",
        "sources": "New / Updated Sources",
        "no_sources": "No new or updated sources passed the report gate.",
        "observations": "Verified observations",
        "no_observations": "No verified observations yet.",
        "evidence": "Evidence trail",
    }


def _evidence_text(claims: list[Claim], *, language: str = "en") -> str:
    blocks = []
    for claim in claims:
        anchors = []
        for anchor in claim.evidence:
            label = anchor.source_title or anchor.source_url
            location = f" ({anchor.location})" if anchor.location else ""
            anchors.append(f"- {label}{location}: {anchor.quote}")
        claim_text = _localized_claim_text(claim.text, language=language)
        blocks.append(f"{claim_text}\n" + "\n".join(anchors))
    return "\n\n".join(blocks) or "No evidence anchors available."


def _localized_claim_text(text: str, *, language: str) -> str:
    if language != "zh":
        return text
    prefix_map = {
        "Problem:": "问题：",
        "Solution:": "方法：",
        "Related work:": "相关工作：",
        "Experiment:": "实验：",
        "Limitations:": "局限：",
        "Critical assessment:": "批判判断：",
        "Essence:": "本质：",
    }
    for prefix, localized in prefix_map.items():
        if text.startswith(prefix):
            return localized + text[len(prefix) :].lstrip()
    return text


def _source_entry(source: SourceCandidate, *, language: str = "en") -> dict[str, str | None]:
    history = source.metadata.get("source_history", {})
    role = source.metadata.get("source_role", {})
    gist = source.metadata.get("source_gist", {})
    role_value = str(role.get("role", source.source_type.value))
    return {
        "title": source.title,
        "url": source.url,
        "role": role_value,
        "source_type": source.source_type.value,
        "source_group": _source_group(source, role_value),
        "history_status": str(history.get("status", "not_tracked")),
        "published_at": source.published_at,
        "version": _display_version(history.get("version")),
        "gist": sanitize_source_gist(str(gist.get("text") or "")) or _fallback_gist(
            source,
            language=language,
        ),
    }


def _display_version(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _fallback_gist(source: SourceCandidate, *, language: str = "en") -> str:
    title = re.sub(r"\s+", " ", source.title).strip()
    if language == "zh":
        return sanitize_source_gist(f"基于标题和来源元数据，这个来源主要围绕《{title}》。")
    return sanitize_source_gist(
        f"Based on title and source metadata, this source is about {title}."
    )


def _source_group(source: SourceCandidate, role: str) -> str:
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
