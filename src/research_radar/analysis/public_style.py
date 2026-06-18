"""Public writing style contract and lightweight audit helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_radar.models import ReviewFinding

PROTECTED_SPAN_RULES = (
    "- Preserve numbers, percentages, formulas, model names, benchmark names, dataset names, "
    "metric names, method names, package names, paper titles, source URLs, claim prefixes, "
    "and exact evidence quotes. Do not round, paraphrase, translate, or soften them."
)

READER_PUBLIC_WRITING_STYLE_CONTRACT = f"""
Public writing style for reader_explanation:
- Write like a specific researcher explaining the paper to a technical reader, not like a
  template summary or marketing copy.
- Be concrete: name the mechanism, request path, data flow, components, metrics, baselines,
  and limitations when the supplied packet supports them.
- Avoid generic significance language, promotional tone, vague authority, mechanical
  rule-of-three phrasing, empty conclusions, and "not only ... but also ..." drama.
- For Chinese downstream reports, make the explanation easy to translate into natural prose:
  direct subject, clear action, short transitions, no slogan-like closing.
{PROTECTED_SPAN_RULES}
- Accuracy is more important than fluency. If a point is not anchored, omit it.
""".strip()

LOCALIZATION_PUBLIC_WRITING_STYLE_CONTRACT = f"""
Chinese public writing style:
- Translate into natural Simplified Chinese that sounds like a technical writer explaining the
  paper, not like a template, sales copy, or motivational essay.
- Keep the original meaning and attribution. Do not add claims, URLs, critique, rankings,
  examples, or conclusions.
- Prefer concrete subject and action. Avoid empty phrases such as "综上所述", "值得注意的是",
  "本质上", "赋能", "闭环", and "不仅仅是...更是...".
- Keep professional register. Do not over-casualize technical explanations, and do not turn
  research limitations into comforting or promotional language.
{PROTECTED_SPAN_RULES}
""".strip()


@dataclass(frozen=True)
class PublicStyleIssue:
    """One public writing style issue found in rendered text."""

    pattern: str
    family: str
    excerpt: str


STYLE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "empty_summary",
        "template conclusion",
        re.compile(r"综上所述|总的来说|归根结底|本质上|值得注意的是"),
    ),
    (
        "false_depth",
        "performative contrast",
        re.compile(r"不仅仅是.{0,24}更是|不是.{0,24}而是"),
    ),
    (
        "business_jargon",
        "business or engineer jargon",
        re.compile(r"赋能|抓手|闭环|沉淀方法论|稳稳兜住|收口|落盘"),
    ),
    (
        "machine_metadata",
        "machine metadata in public text",
        re.compile(r"\b(?:role|status|score)=", flags=re.IGNORECASE),
    ),
    (
        "english_ai_phrase",
        "generic AI writing phrase",
        re.compile(
            r"\b(?:in conclusion|it is important to note|serves as a testament|"
            r"vibrant|pivotal|underscores|showcases)\b",
            flags=re.IGNORECASE,
        ),
    ),
)


def audit_public_writing_text(
    text: str,
    *,
    target: str,
    language: str,
) -> list[ReviewFinding]:
    """Return non-blocking review findings for public writing style issues."""

    issues = _style_issues(text)
    if not issues:
        return []
    findings = []
    for issue in issues:
        findings.append(
            ReviewFinding(
                severity="warning",
                message=(
                    f"Public {target} text contains {issue.family}: "
                    f"{issue.pattern}"
                ),
                metadata={
                    "kind": "public_writing_style",
                    "target": target,
                    "language": language,
                    "pattern": issue.pattern,
                    "family": issue.family,
                    "excerpt": issue.excerpt,
                },
            )
        )
    return findings


def _style_issues(text: str) -> list[PublicStyleIssue]:
    issues: list[PublicStyleIssue] = []
    for pattern_name, family, pattern in STYLE_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(
                PublicStyleIssue(
                    pattern=pattern_name,
                    family=family,
                    excerpt=_excerpt(text, match.start(), match.end()),
                )
            )
    return issues


def _excerpt(text: str, start: int, end: int) -> str:
    left = max(0, start - 60)
    right = min(len(text), end + 60)
    excerpt = re.sub(r"\s+", " ", text[left:right]).strip()
    if left > 0:
        excerpt = "..." + excerpt
    if right < len(text):
        excerpt += "..."
    return excerpt
