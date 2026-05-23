"""WeChat Official Account HTML composition."""

from __future__ import annotations

from html import escape

from research_radar.compose.draft import build_weekly_draft
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, Claim


def render_wechat_html(draft: ArticleDraft) -> str:
    """Render a platform-neutral draft as WeChat-compatible HTML."""

    language = str(draft.metadata.get("language", "en"))
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
        if _section_kind(section) == "evidence_trail":
            content = "".join(_evidence_block(claim, language=language) for claim in section.claims)
        elif _section_kind(section) == "new_updated_sources":
            content = _source_list(section.metadata.get("sources", []), language=language)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        else:
            content = "".join(_claim_card(claim, language=language) for claim in section.claims)
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


def _claim_card(claim: Claim, *, language: str) -> str:
    tag = "已核验" if language == "zh" else "Verified"
    fallback = (
        "这条判断由下方证据链支撑。"
        if language == "zh"
        else "This claim is backed by the evidence trail below."
    )
    return f"""<section class="rr-card">
<span class="rr-tag">{tag}</span>
<h3>{escape(_localized_claim_text(claim.text, language=language))}</h3>
<p>{escape(claim.rationale or fallback)}</p>
</section>"""


def _source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    blocks = []
    for group, items in group_source_entries(raw_sources):
        if not items:
            continue
        blocks.append(f"<h3>{escape(source_group_label(group, language=language))}</h3>")
        for item in items:
            title = escape(str(item.get("title", "Untitled source")))
            url = escape(str(item.get("url", "")))
            gist = escape(str(item.get("gist", "")))
            descriptor = escape(_source_descriptor(item))
            gist_label = "摘要" if language == "zh" else "Gist"
            blocks.append(
                f"""<section class="rr-card">
<h3><a href="{url}">{title}</a></h3>
<p>{descriptor}</p>
<p><strong>{gist_label}:</strong> {gist}</p>
</section>"""
            )
    return "".join(blocks)


def _section_kind(section: object) -> str:
    metadata = getattr(section, "metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get("kind"), str):
        return str(metadata["kind"])
    title = str(getattr(section, "title", "")).lower()
    if title.startswith("new / updated"):
        return "new_updated_sources"
    if title.startswith("evidence"):
        return "evidence_trail"
    return ""


def _source_descriptor(item: dict[object, object]) -> str:
    parts = []
    for key, label in [
        ("role", "role"),
        ("history_status", "status"),
        ("published_at", "published"),
        ("version", "version"),
    ]:
        value = item.get(key)
        if value:
            parts.append(f"{label}={value}")
    return ", ".join(str(part) for part in parts)


def _evidence_block(claim: Claim, *, language: str) -> str:
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
    claim_text = escape(_localized_claim_text(claim.text, language=language))
    return f"<section><h3>{claim_text}</h3>{''.join(anchors)}</section>"


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
