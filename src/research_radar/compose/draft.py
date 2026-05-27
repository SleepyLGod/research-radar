"""Platform-neutral research article draft construction."""

from __future__ import annotations

import re
from typing import Any

from research_radar.analysis.source_gist import sanitize_source_gist
from research_radar.compose.source_groups import source_group_for_candidate
from research_radar.evidence.policy import publishable_claims
from research_radar.models import ArticleDraft, ArticleSection, Claim, SourceCandidate


def build_daily_draft(
    topic_id: str,
    sources: list[SourceCandidate],
    claims: list[Claim],
    *,
    language: str = "en",
    readings: list[Any] | None = None,
    deep_read_sources: list[SourceCandidate] | None = None,
    seen_sources: list[dict[str, Any]] | None = None,
) -> ArticleDraft:
    """Build a platform-neutral daily monitoring draft."""

    verified = publishable_claims(claims)
    if readings is not None or deep_read_sources is not None or seen_sources is not None:
        return _build_long_form_daily_draft(
            topic_id,
            sources,
            verified,
            language=language,
            readings=readings or [],
            deep_read_sources=deep_read_sources or [],
            seen_sources=seen_sources or [],
        )

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


def _build_long_form_daily_draft(
    topic_id: str,
    sources: list[SourceCandidate],
    verified: list[Claim],
    *,
    language: str,
    readings: list[Any],
    deep_read_sources: list[SourceCandidate],
    seen_sources: list[dict[str, Any]],
) -> ArticleDraft:
    labels = _long_form_labels(language)
    deep_urls = {source.url for source in deep_read_sources}
    source_entries = [
        _source_entry(source, language=language, deep_read=source.url in deep_urls)
        for source in sources
    ]
    deep_read_entries = _deep_read_entries(
        readings,
        deep_read_sources,
        verified,
        language=language,
    )
    other_source_entries = [entry for entry in source_entries if not entry.get("deep_read")]
    seen_entries = _seen_source_entries(seen_sources)
    lede = _long_form_lede(verified, deep_read_entries, source_entries, seen_entries, language)
    sections = [
        ArticleSection(
            title=labels["summary"],
            body=_summary_body(verified, deep_read_entries, source_entries, seen_entries, language),
            claims=verified[:3],
            metadata={"kind": "today_summary"},
        ),
        ArticleSection(
            title=labels["deep_reads"],
            body=labels["no_deep_reads"] if not deep_read_entries else "",
            claims=verified,
            metadata={"kind": "deep_reads", "deep_reads": deep_read_entries},
        ),
        ArticleSection(
            title=labels["other_sources"],
            body=labels["no_other_sources"] if not other_source_entries else "",
            metadata={"kind": "new_updated_sources", "sources": other_source_entries},
        ),
        ArticleSection(
            title=labels["seen_before"],
            body=labels["no_seen_sources"] if not seen_entries else "",
            metadata={"kind": "seen_before", "sources": seen_entries},
        ),
        ArticleSection(
            title=labels["evidence_notes"],
            body=_evidence_text(verified, language=language),
            claims=verified,
            metadata={"kind": "evidence_notes"},
        ),
    ]
    return ArticleDraft(
        title=labels["title"].format(topic_id=topic_id),
        topic_id=topic_id,
        digest=lede[:120],
        lede=lede,
        claims=verified,
        sections=sections,
        metadata={
            "source_count": len(sources),
            "deep_read_count": len(deep_read_entries),
            "seen_source_count": len(seen_entries),
            "draft_type": "daily_long_form",
            "language": language,
        },
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


def _long_form_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "title": "ResearchRadar 日报：{topic_id}",
            "summary": "今日摘要",
            "deep_reads": "今日精读",
            "other_sources": "其他新增 / 更新来源",
            "seen_before": "已读过的相关来源",
            "evidence_notes": "证据说明",
            "no_deep_reads": "今天没有新论文进入精读。",
            "no_other_sources": "没有其他新增或更新来源通过报告门槛。",
            "no_seen_sources": "没有可展示的历史来源。",
            "no_new": "今天没有新论文或新版本进入精读；下面保留历史相关来源，方便回看。",
            "with_deep": "今天精读了 {count} 篇新论文，并保留其他新增来源供后续跟进。",
            "with_sources": "今天没有精读通过，但有 {count} 个新增或更新来源可供人工查看。",
            "no_verified": "没有 claim 通过证据核验；来源链接会保留在下方供人工查看。",
            "verified_count": "已核验证据点：{count} 条。",
        }
    return {
        "title": "ResearchRadar Daily: {topic_id}",
        "summary": "Today at a Glance",
        "deep_reads": "Today's Deep Reads",
        "other_sources": "Other New / Updated Sources",
        "seen_before": "Seen Before",
        "evidence_notes": "Evidence Notes",
        "no_deep_reads": "No new paper entered deep reading today.",
        "no_other_sources": "No other new or updated sources passed the report gate.",
        "no_seen_sources": "No historical sources are available for display.",
        "no_new": (
            "No new paper or new version entered deep reading today; historical related "
            "sources are kept below for quick review."
        ),
        "with_deep": "Today deep-read {count} new paper(s) and kept other sources for follow-up.",
        "with_sources": (
            "No deep reading passed today, but {count} new or updated source(s) are available "
            "for manual review."
        ),
        "no_verified": (
            "No claim passed evidence verification; source links remain below for manual review."
        ),
        "verified_count": "{count} evidence-backed observation(s) passed verification.",
    }


def _long_form_lede(
    verified: list[Claim],
    deep_read_entries: list[dict[str, Any]],
    source_entries: list[dict[str, Any]],
    seen_entries: list[dict[str, Any]],
    language: str,
) -> str:
    labels = _long_form_labels(language)
    if deep_read_entries and verified:
        return (
            f"{labels['with_deep'].format(count=len(deep_read_entries))} "
            f"{_localized_claim_text(verified[0].text, language=language)}"
        )
    if deep_read_entries:
        return labels["with_deep"].format(count=len(deep_read_entries))
    if source_entries:
        if not verified:
            return labels["no_verified"]
        return labels["with_sources"].format(count=len(source_entries))
    if seen_entries:
        return labels["no_new"]
    return _lede(verified, language=language)


def _summary_body(
    verified: list[Claim],
    deep_read_entries: list[dict[str, Any]],
    source_entries: list[dict[str, Any]],
    seen_entries: list[dict[str, Any]],
    language: str,
) -> str:
    labels = _long_form_labels(language)
    lines = [
        _long_form_lede(verified, deep_read_entries, source_entries, seen_entries, language),
        labels["verified_count"].format(count=len(verified)),
    ]
    if not source_entries and seen_entries:
        lines.append(labels["no_new"])
    return "\n".join(lines)


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


def _deep_read_entries(
    readings: list[Any],
    deep_read_sources: list[SourceCandidate],
    verified: list[Claim],
    *,
    language: str,
) -> list[dict[str, Any]]:
    entries = []
    for index, reading in enumerate(readings):
        source = deep_read_sources[index] if index < len(deep_read_sources) else None
        reading_claims = _claims_for_reading(reading, source, verified)
        entries.append(
            {
                "title": str(getattr(reading, "title", "") or getattr(source, "title", "")),
                "source": _source_entry(source, language=language, deep_read=True)
                if source
                else None,
                "essence": str(getattr(reading, "essence", "")),
                "problem": _problem_entry(reading),
                "solution": _solution_entry(reading),
                "experiments": _experiments_entry(reading),
                "related_work": _related_work_entry(reading),
                "limitations": _limitations_entry(reading),
                "critical_assessment": _critical_entry(reading),
                "plain_language_example": str(
                    getattr(reading, "plain_language_example", "")
                ),
                "claims": [_claim_entry(claim, language=language) for claim in reading_claims],
            }
        )
    return entries


def _claims_for_reading(
    reading: Any,
    source: SourceCandidate | None,
    verified: list[Claim],
) -> list[Claim]:
    title = str(getattr(reading, "title", ""))
    source_url = source.url if source else ""
    source_title = source.title if source else title
    matches = []
    for claim in verified:
        for anchor in claim.evidence:
            if source_url and anchor.source_url == source_url:
                matches.append(claim)
                break
            if source_title and anchor.source_title == source_title:
                matches.append(claim)
                break
            if title and anchor.source_title == title:
                matches.append(claim)
                break
    return matches


def _problem_entry(reading: Any) -> dict[str, Any]:
    value = getattr(reading, "problem_solution", None)
    return {
        "core": str(getattr(value, "problem", "")),
        "why_it_matters": str(getattr(value, "why_it_matters", "")),
        "hidden_assumptions": list(getattr(value, "hidden_assumptions", []) or []),
    }


def _solution_entry(reading: Any) -> dict[str, str]:
    value = getattr(reading, "problem_solution", None)
    return {
        "core": str(getattr(value, "solution", "")),
        "mechanism": str(getattr(value, "mechanism", "")),
    }


def _experiments_entry(reading: Any) -> dict[str, str]:
    return {"summary": str(getattr(reading, "experiment_summary", ""))}


def _related_work_entry(reading: Any) -> dict[str, Any]:
    value = getattr(reading, "related_work", None)
    return {
        "novelty": str(getattr(value, "novelty", "")),
        "prior_work": list(getattr(value, "prior_work", []) or []),
        "repackaging_risk": str(getattr(value, "repackaging_risk", "")),
    }


def _limitations_entry(reading: Any) -> dict[str, Any]:
    value = getattr(reading, "limitations", None)
    return {
        "explicit_limitations": list(getattr(value, "explicit_limitations", []) or []),
        "inferred_weaknesses": list(getattr(value, "inferred_weaknesses", []) or []),
        "future_work": list(getattr(value, "future_work", []) or []),
    }


def _critical_entry(reading: Any) -> dict[str, Any]:
    value = getattr(reading, "critical_assessment", None)
    return {
        "bottom_line": str(getattr(value, "bottom_line", "")),
        "overclaiming_risk": str(getattr(value, "overclaiming_risk", "")),
        "weak_evaluations": list(getattr(value, "weak_evaluations", []) or []),
        "missing_ablations": list(getattr(value, "missing_ablations", []) or []),
    }


def _claim_entry(claim: Claim, *, language: str) -> dict[str, Any]:
    return {
        "text": _localized_claim_text(claim.text, language=language),
        "rationale": claim.rationale or "",
        "evidence": [
            {
                "source_url": anchor.source_url,
                "source_title": anchor.source_title,
                "quote": anchor.quote,
                "location": anchor.location,
            }
            for anchor in claim.evidence
        ],
    }


def _seen_source_entries(seen_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for source in seen_sources[:12]:
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title or not url:
            continue
        entries.append(
            {
                "title": title,
                "url": url,
                "history_status": "seen",
                "version": source.get("version"),
                "family_key": source.get("family_key"),
            }
        )
    return entries


def _source_entry(
    source: SourceCandidate,
    *,
    language: str = "en",
    deep_read: bool = False,
) -> dict[str, Any]:
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
        "deep_read": deep_read,
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
    return source_group_for_candidate(source, role)
