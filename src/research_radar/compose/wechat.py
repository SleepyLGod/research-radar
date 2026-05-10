"""WeChat Official Account HTML composition."""

from __future__ import annotations

from html import escape

from research_radar.compose.draft import build_weekly_draft
from research_radar.models import ArticleDraft, Claim


def render_wechat_html(draft: ArticleDraft) -> str:
    """Render a platform-neutral draft as WeChat-compatible HTML."""

    body = [
        _section(
            "section",
            f"""
            <h1>{escape(draft.title)}</h1>
            <p class="lede">{escape(draft.lede)}</p>
            """,
        )
    ]
    for section in draft.sections:
        if section.title.lower().startswith("evidence"):
            content = "".join(_evidence_block(claim) for claim in section.claims)
        else:
            content = "".join(_claim_card(claim) for claim in section.claims)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        body.append(_section("section", f"<h2>{escape(section.title)}</h2>{content}"))
    return _html_shell("".join(body))


def compose_wechat_html(topic_id: str, claims: list[Claim]) -> str:
    """Compose a WeChat-compatible article body."""

    return render_wechat_html(build_weekly_draft(topic_id, claims))


def _html_shell(body: str) -> str:
    shell_start = (
        "<section style=\"font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',"
        "Arial,sans-serif;color:#1f2933;line-height:1.75;font-size:16px;\">"
    )
    return f"""{shell_start}
<style>
.rr-card{{border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;
margin:14px 0;background:#ffffff;}}
.rr-tag{{display:inline-block;color:#0f766e;background:#ccfbf1;padding:2px 8px;
border-radius:999px;font-size:12px;}}
.rr-quote{{border-left:4px solid #0f766e;padding:8px 12px;margin:10px 0;
background:#f8fafc;color:#334155;}}
.lede{{font-size:18px;font-weight:600;color:#111827;}}
h1{{font-size:26px;line-height:1.25;margin:0 0 14px;}}
h2{{font-size:20px;margin:24px 0 10px;}}
h3{{font-size:17px;margin:0 0 8px;}}
a{{color:#0f766e;text-decoration:none;}}
</style>
{body}
</section>"""


def _section(tag: str, content: str) -> str:
    return f"<{tag}>{content}</{tag}>"


def _claim_card(claim: Claim) -> str:
    return f"""<section class="rr-card">
<span class="rr-tag">Verified</span>
<h3>{escape(claim.text)}</h3>
<p>{escape(claim.rationale or "This claim is backed by the evidence trail below.")}</p>
</section>"""


def _evidence_block(claim: Claim) -> str:
    anchors = []
    for anchor in claim.evidence:
        title = escape(anchor.source_title or anchor.source_url)
        quote = escape(anchor.quote)
        location = escape(anchor.location or "")
        anchors.append(
            f"""<section class="rr-quote">
<strong>{title}</strong>{f" <em>{location}</em>" if location else ""}
<p>{quote}</p>
<p><a href="{escape(anchor.source_url)}">Original source</a></p>
</section>"""
        )
    return f"<section><h3>{escape(claim.text)}</h3>{''.join(anchors)}</section>"
