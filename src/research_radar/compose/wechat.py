"""WeChat Official Account HTML composition."""

from __future__ import annotations

from html import escape

from research_radar.compose.draft import build_weekly_draft
from research_radar.compose.source_groups import group_source_entries, source_group_label
from research_radar.models import ArticleDraft, Claim


def render_wechat_html(draft: ArticleDraft) -> str:
    """Render a platform-neutral draft as WeChat-compatible HTML."""

    language = str(draft.metadata.get("language", "en"))
    long_form = draft.metadata.get("draft_type") == "daily_long_form"
    body = [
        _section(
            "section",
            f"""
            <h1>{escape(draft.title)}</h1>
            <p class="lede">{escape(draft.lede)}</p>
            """,
        )
    ]
    if long_form:
        body.append(_table_of_contents(draft, language=language))
    for index, section in enumerate(draft.sections, start=1):
        kind = _section_kind(section)
        if kind == "evidence_trail":
            content = "".join(_evidence_block(claim, language=language) for claim in section.claims)
        elif kind == "evidence_notes":
            content = _evidence_notes(section.claims, language=language)
        elif kind == "deep_reads":
            content = _deep_reads(section.metadata.get("deep_reads", []), language=language)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        elif kind in {"new_updated_sources", "other_sources"}:
            content = _source_list(section.metadata.get("sources", []), language=language)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        elif kind == "seen_before":
            content = _seen_source_list(section.metadata.get("sources", []), language=language)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        elif kind == "today_summary":
            content = _paragraphs(section.body)
        else:
            content = "".join(_claim_card(claim, language=language) for claim in section.claims)
            if not content:
                content = f"<p>{escape(section.body)}</p>"
        body.append(
            _section(
                "section",
                f"<h2>{escape(section.title)}</h2>{content}",
                section_id=f"rr-section-{index}" if long_form else None,
            )
        )
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
.rr-toc{{border:1px solid #d1d5db;padding:14px 16px;margin:18px 0;background:#f9fafb;}}
.rr-toc ol{{margin:8px 0 0 20px;padding:0;}}
.rr-deep{{border-top:2px solid #111827;padding-top:18px;margin-top:18px;}}
.rr-kicker{{font-size:13px;color:#64748b;margin:0 0 4px;}}
.rr-diagram{{display:block;border:1px solid #dbeafe;background:#eff6ff;padding:12px;margin:12px 0;}}
.rr-step{{display:inline-block;vertical-align:top;width:22%;min-width:120px;margin:4px;
padding:8px;background:#ffffff;border:1px solid #bfdbfe;}}
.rr-step strong{{display:block;color:#1e40af;margin-bottom:4px;}}
.rr-evidence-note{{font-size:14px;color:#475569;}}
.lede{{font-size:18px;font-weight:600;color:#111827;}}
h1{{font-size:26px;line-height:1.25;margin:0 0 14px;}}
h2{{font-size:20px;margin:24px 0 10px;}}
h3{{font-size:17px;margin:0 0 8px;}}
h4{{font-size:16px;margin:16px 0 6px;}}
a{{color:#0f766e;text-decoration:none;}}
</style>
{body}
</section>"""


def _section(tag: str, content: str, *, section_id: str | None = None) -> str:
    id_attr = f' id="{escape(section_id)}"' if section_id else ""
    return f"<{tag}{id_attr}>{content}</{tag}>"


def _table_of_contents(draft: ArticleDraft, *, language: str) -> str:
    title = "目录" if language == "zh" else "Contents"
    items = []
    for index, section in enumerate(draft.sections, start=1):
        items.append(f'<li><a href="#rr-section-{index}">{escape(section.title)}</a></li>')
    return _section(
        "section",
        f'<div class="rr-toc"><strong>{title}</strong><ol>{"".join(items)}</ol></div>',
    )


def _paragraphs(text: str) -> str:
    return "".join(
        f"<p>{escape(line.strip())}</p>" for line in text.splitlines() if line.strip()
    )


def _deep_reads(raw_deep_reads: object, *, language: str) -> str:
    if not isinstance(raw_deep_reads, list):
        return ""
    blocks = []
    labels = _deep_read_labels(language)
    for raw_entry in raw_deep_reads:
        if not isinstance(raw_entry, dict):
            continue
        title = escape(str(raw_entry.get("title") or labels["untitled"]))
        source = raw_entry.get("source") if isinstance(raw_entry.get("source"), dict) else {}
        source_link = _source_title_link(source, fallback=title)
        sections = [
            _deep_text_block(labels["essence"], raw_entry.get("essence")),
            _problem_block(raw_entry.get("problem"), labels),
            _solution_block(raw_entry.get("solution"), labels),
            _experiments_block(raw_entry.get("experiments"), labels),
            _related_work_block(raw_entry.get("related_work"), labels),
            _limitations_block(raw_entry.get("limitations"), labels),
            _critical_block(raw_entry.get("critical_assessment"), labels),
            _deep_text_block(labels["plain_example"], raw_entry.get("plain_language_example")),
            _key_evidence_block(raw_entry.get("claims"), labels),
        ]
        blocks.append(
            f"""<article class="rr-deep">
<p class="rr-kicker">{labels["deep_read_label"]}</p>
<h3>{source_link}</h3>
{_paper_descriptor(source)}
{_explanatory_diagram(raw_entry, labels)}
{''.join(section for section in sections if section)}
</article>"""
        )
    return "".join(blocks)


def _source_title_link(source: object, *, fallback: str) -> str:
    if not isinstance(source, dict):
        return fallback
    title = escape(str(source.get("title") or fallback))
    url = escape(str(source.get("url") or ""))
    if not url:
        return title
    return f'<a href="{url}">{title}</a>'


def _paper_descriptor(source: object) -> str:
    if not isinstance(source, dict):
        return ""
    descriptor = escape(_source_descriptor(source))
    gist = escape(str(source.get("gist") or ""))
    lines = []
    if descriptor:
        lines.append(f'<p class="rr-kicker">{descriptor}</p>')
    if gist:
        lines.append(f"<p>{gist}</p>")
    return "".join(lines)


def _explanatory_diagram(entry: dict[object, object], labels: dict[str, str]) -> str:
    steps = [
        (labels["problem_short"], _nested_value(entry.get("problem"), "core")),
        (labels["method_short"], _nested_value(entry.get("solution"), "core")),
        (labels["eval_short"], _nested_value(entry.get("experiments"), "summary")),
        (labels["caveat_short"], _first_nested_list(entry.get("limitations"))),
    ]
    rendered = []
    for title, value in steps:
        if value:
            rendered.append(
                '<span class="rr-step">'
                f"<strong>{escape(title)}</strong>{escape(_shorten(value))}</span>"
            )
    if len(rendered) < 2:
        return ""
    return f'<div class="rr-diagram">{"".join(rendered)}</div>'


def _deep_text_block(title: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"<h4>{escape(title)}</h4><p>{escape(text)}</p>"


def _problem_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    parts = [
        _deep_text_block(labels["problem"], value.get("core")),
        _deep_text_block(labels["why_it_matters"], value.get("why_it_matters")),
        _list_block(labels["hidden_assumptions"], value.get("hidden_assumptions")),
    ]
    return "".join(parts)


def _solution_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _deep_text_block(labels["solution"], value.get("core")),
            _deep_text_block(labels["mechanism"], value.get("mechanism")),
        ]
    )


def _experiments_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return _deep_text_block(labels["experiments"], value.get("summary"))


def _related_work_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _deep_text_block(labels["related_work"], value.get("novelty")),
            _list_block(labels["prior_work"], value.get("prior_work")),
            _deep_text_block(labels["repackaging_risk"], value.get("repackaging_risk")),
        ]
    )


def _limitations_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _list_block(labels["explicit_limitations"], value.get("explicit_limitations")),
            _list_block(labels["inferred_weaknesses"], value.get("inferred_weaknesses")),
            _list_block(labels["future_work"], value.get("future_work")),
        ]
    )


def _critical_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(
        [
            _deep_text_block(labels["critical"], value.get("bottom_line")),
            _deep_text_block(labels["overclaiming_risk"], value.get("overclaiming_risk")),
            _list_block(labels["weak_evaluations"], value.get("weak_evaluations")),
            _list_block(labels["missing_ablations"], value.get("missing_ablations")),
        ]
    )


def _key_evidence_block(value: object, labels: dict[str, str]) -> str:
    if not isinstance(value, list) or not value:
        return ""
    claims = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        text = escape(str(item.get("text") or ""))
        evidence = item.get("evidence")
        quote = ""
        if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
            location = str(evidence[0].get("location") or "")
            raw_quote = str(evidence[0].get("quote") or "")
            quote = (
                f'<blockquote class="rr-quote"><em>{escape(location)}</em>'
                f"<p>{escape(raw_quote)}</p></blockquote>"
            )
        claims.append(f"<li>{text}{quote}</li>")
    if not claims:
        return ""
    return f'<h4>{escape(labels["key_evidence"])}</h4><ol>{"".join(claims)}</ol>'


def _list_block(title: str, value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    items = "".join(f"<li>{escape(str(item))}</li>" for item in value if str(item).strip())
    if not items:
        return ""
    return f"<h4>{escape(title)}</h4><ul>{items}</ul>"


def _seen_source_list(raw_sources: object, *, language: str) -> str:
    if not isinstance(raw_sources, list):
        return ""
    label = "已读过" if language == "zh" else "Seen"
    items = []
    for source in raw_sources[:12]:
        if not isinstance(source, dict):
            continue
        title = escape(str(source.get("title") or "Untitled source"))
        url = escape(str(source.get("url") or ""))
        version = escape(str(source.get("version") or ""))
        suffix = f" ({version})" if version else ""
        items.append(f'<li><a href="{url}">{title}</a>{suffix}</li>')
    if not items:
        return ""
    return f"<p>{label}</p><ul>{''.join(items)}</ul>"


def _evidence_notes(claims: list[Claim], *, language: str) -> str:
    if not claims:
        fallback = (
            "今天没有可发布的已核验证据点。"
            if language == "zh"
            else "No verified evidence-backed observations today."
        )
        return f"<p>{fallback}</p>"
    note = (
        "以下证据只展示已通过核验的关键原文锚点；完整审计请看本地 review_report.md。"
        if language == "zh"
        else (
            "Only verified source anchors are shown here; the full audit remains in "
            "review_report.md."
        )
    )
    return f'<p class="rr-evidence-note">{note}</p>' + "".join(
        _evidence_block(claim, language=language) for claim in claims[:12]
    )


def _deep_read_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "untitled": "未命名论文",
            "deep_read_label": "精读论文",
            "essence": "本质判断",
            "problem": "问题与动机",
            "why_it_matters": "为什么重要",
            "hidden_assumptions": "隐藏假设",
            "solution": "方法与机制",
            "mechanism": "机制展开",
            "experiments": "实验与评估",
            "related_work": "相关工作",
            "prior_work": "代表性已有工作",
            "repackaging_risk": "重新包装风险",
            "explicit_limitations": "作者明确局限",
            "inferred_weaknesses": "证据支持的推断弱点",
            "future_work": "未来工作",
            "critical": "中立批判",
            "overclaiming_risk": "过度声称风险",
            "weak_evaluations": "薄弱评估",
            "missing_ablations": "缺失消融",
            "plain_example": "通俗例子",
            "key_evidence": "关键证据",
            "problem_short": "问题",
            "method_short": "方法",
            "eval_short": "评估",
            "caveat_short": "局限",
        }
    return {
        "untitled": "Untitled paper",
        "deep_read_label": "Deep-read paper",
        "essence": "Essence",
        "problem": "Problem and Motivation",
        "why_it_matters": "Why it matters",
        "hidden_assumptions": "Hidden assumptions",
        "solution": "Solution Mechanism",
        "mechanism": "Mechanism details",
        "experiments": "Experiments",
        "related_work": "Related Work",
        "prior_work": "Representative prior work",
        "repackaging_risk": "Repackaging risk",
        "explicit_limitations": "Explicit limitations",
        "inferred_weaknesses": "Evidence-backed inferred weaknesses",
        "future_work": "Future work",
        "critical": "Critical Assessment",
        "overclaiming_risk": "Overclaiming risk",
        "weak_evaluations": "Weak evaluations",
        "missing_ablations": "Missing ablations",
        "plain_example": "Plain-language Example",
        "key_evidence": "Key Evidence",
        "problem_short": "Problem",
        "method_short": "Method",
        "eval_short": "Evaluation",
        "caveat_short": "Caveat",
    }


def _nested_value(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get(key) or "")


def _first_nested_list(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ["explicit_limitations", "inferred_weaknesses", "future_work"]:
        values = value.get(key)
        if isinstance(values, list) and values:
            return str(values[0])
    return ""


def _shorten(value: str, limit: int = 130) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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
