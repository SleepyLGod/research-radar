"""Platform-neutral research article draft construction."""

from __future__ import annotations

from research_radar.evidence.policy import publishable_claims
from research_radar.models import ArticleDraft, ArticleSection, Claim, SourceCandidate


def build_daily_draft(
    topic_id: str,
    sources: list[SourceCandidate],
    claims: list[Claim],
) -> ArticleDraft:
    """Build a platform-neutral daily monitoring draft."""

    verified = publishable_claims(claims)
    source_lines = []
    for source in sources:
        summary = f" - {source.summary[:220]}" if source.summary else ""
        source_lines.append(f"{source.title}: {source.url}{summary}")

    observation_lines = [claim.text for claim in verified]
    lede = _lede(verified)
    return ArticleDraft(
        title=f"ResearchRadar Daily: {topic_id}",
        topic_id=topic_id,
        digest=lede[:120],
        lede=lede,
        claims=verified,
        sections=[
            ArticleSection(title="High-signal sources", body="\n".join(source_lines)),
            ArticleSection(
                title="Verified observations",
                body="\n".join(observation_lines) or "No verified observations yet.",
                claims=verified,
            ),
            ArticleSection(
                title="Evidence trail",
                body=_evidence_text(verified),
                claims=verified,
            ),
        ],
        metadata={"source_count": len(sources), "draft_type": "daily"},
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


def _lede(claims: list[Claim]) -> str:
    if not claims:
        return "No claim passed evidence verification, so this draft is intentionally empty."
    return claims[0].text


def _evidence_text(claims: list[Claim]) -> str:
    blocks = []
    for claim in claims:
        anchors = []
        for anchor in claim.evidence:
            label = anchor.source_title or anchor.source_url
            location = f" ({anchor.location})" if anchor.location else ""
            anchors.append(f"- {label}{location}: {anchor.quote}")
        blocks.append(f"{claim.text}\n" + "\n".join(anchors))
    return "\n\n".join(blocks) or "No evidence anchors available."
