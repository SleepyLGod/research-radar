from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.wechat import compose_wechat_html, render_wechat_html
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, SourceCandidate, SourceType


def test_wechat_html_uses_verified_claims_only() -> None:
    verified = Claim(
        text="Verified insight",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://example.com/paper",
                source_title="Paper",
                quote="Direct evidence",
                location="page 1",
            )
        ],
    )
    unsupported = Claim(text="Unsupported insight", status=ClaimStatus.UNSUPPORTED)

    html = compose_wechat_html("agent-memory", [verified, unsupported])

    assert "Verified insight" in html
    assert "Direct evidence" in html
    assert "Unsupported insight" not in html


def test_markdown_and_wechat_render_same_article_draft() -> None:
    claim = Claim(
        text="Same neutral draft",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Grounded")],
    )
    draft = build_weekly_draft("agent-memory", [claim])

    markdown = render_markdown(draft)
    html = render_wechat_html(draft)

    assert "Same neutral draft" in markdown
    assert "Same neutral draft" in html
    assert draft.topic_id == "agent-memory"


def test_daily_article_draft_excludes_downgraded_claims() -> None:
    source = SourceCandidate(
        title="Agent memory source",
        url="https://example.com/source",
        source_type=SourceType.PAPER,
        source_name="test",
    )
    supported = Claim(
        text="Supported daily claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/source", quote="Evidence")],
    )
    downgraded = Claim(
        text="Downgraded daily claim",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/source", quote="Evidence")],
    )

    draft = build_daily_draft("agent-memory", [source], [supported, downgraded])

    assert supported in draft.claims
    assert downgraded not in draft.claims
