"""Markdown rendering for a single-paper research brief."""

from __future__ import annotations

from research_radar.analysis.paper_reading import PaperReading
from research_radar.evidence.policy import publishable_claims
from research_radar.models import Claim


def render_paper_brief(
    reading: PaperReading,
    claims: list[Claim],
    *,
    language: str = "en",
) -> str:
    """Render a conservative, evidence-backed paper brief."""

    verified = publishable_claims(claims)
    labels = _paper_labels(language)
    lines = [
        f"# {labels['title']}: {reading.title}",
        "",
        f"## {labels['essence']}",
        _claim_body(verified, "Essence:") or "No verified essence claim.",
        "",
        f"## {labels['background']}",
        reading.area_context.background,
        "",
        f"## {labels['problem']}",
        _problem_body(reading, verified, labels),
        "",
        f"## {labels['solution']}",
        _solution_body(reading, verified, labels),
        "",
        f"## {labels['experiment']}",
        _claim_body(verified, "Experiment:") or "No verified experiment claim.",
        "",
        f"## {labels['plain_example']}",
        reading.plain_language_example or labels["no_example"],
        "",
        f"## {labels['related_work']}",
        _related_work_body(reading, verified, labels),
        "",
        f"## {labels['limitations']}",
        _limitations_body(reading, verified, labels),
        "",
        f"## {labels['critique']}",
        _critical_body(reading, verified, labels),
        "",
        f"## {labels['evidence']}",
        _evidence_trail(verified, language=language),
    ]
    return "\n".join(lines).strip() + "\n"


def _claim_body(claims: list[Claim], prefix: str) -> str:
    for claim in claims:
        if claim.text.startswith(prefix):
            return claim.text[len(prefix) :].strip()
    return ""


def _problem_body(
    reading: PaperReading,
    claims: list[Claim],
    labels: dict[str, str],
) -> str:
    claim = _claim_body(claims, "Problem:")
    if not claim:
        return labels["no_problem"]
    lines = [claim, f"- {labels['why_it_matters']}: {reading.problem_solution.why_it_matters}"]
    if reading.problem_solution.hidden_assumptions:
        lines.append(
            f"- {labels['hidden_assumptions']}: "
            + "; ".join(reading.problem_solution.hidden_assumptions)
        )
    return "\n".join(lines)


def _solution_body(
    reading: PaperReading,
    claims: list[Claim],
    labels: dict[str, str],
) -> str:
    claim = _claim_body(claims, "Solution:")
    if not claim:
        return labels["no_solution"]
    return "\n".join([claim, f"- {labels['mechanism']}: {reading.problem_solution.mechanism}"])


def _related_work_body(
    reading: PaperReading,
    claims: list[Claim],
    labels: dict[str, str],
) -> str:
    claim = _claim_body(claims, "Related work:")
    if not claim:
        return labels["no_related_work"]
    lines = [claim]
    if reading.related_work.prior_work:
        lines.append(f"- {labels['prior_work']}: " + "; ".join(reading.related_work.prior_work))
    lines.append(f"- {labels['repackaging_risk']}: {reading.related_work.repackaging_risk}")
    return "\n".join(lines)


def _limitations_body(
    reading: PaperReading,
    claims: list[Claim],
    labels: dict[str, str],
) -> str:
    claim = _claim_body(claims, "Limitations:")
    if not claim:
        return labels["no_limitations"]
    lines = [claim]
    if reading.limitations.inferred_weaknesses:
        lines.append(
            f"- {labels['inferred_weaknesses']}: "
            + "; ".join(reading.limitations.inferred_weaknesses)
        )
    if reading.limitations.future_work:
        lines.append(f"- {labels['future_work']}: " + "; ".join(reading.limitations.future_work))
    return "\n".join(lines)


def _critical_body(
    reading: PaperReading,
    claims: list[Claim],
    labels: dict[str, str],
) -> str:
    claim = _claim_body(claims, "Critical assessment:")
    if not claim:
        return labels["no_critique"]
    lines = [
        claim,
        (
            f"- {labels['overclaiming_risk']}: "
            f"{reading.critical_assessment.overclaiming_risk}"
        ),
    ]
    if reading.critical_assessment.weak_evaluations:
        lines.append(
            f"- {labels['weak_evaluations']}: "
            + "; ".join(reading.critical_assessment.weak_evaluations)
        )
    if reading.critical_assessment.missing_ablations:
        lines.append(
            f"- {labels['missing_ablations']}: "
            + "; ".join(reading.critical_assessment.missing_ablations)
        )
    return "\n".join(lines)


def _paper_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "title": "ResearchRadar 论文简报",
            "essence": "本质判断",
            "background": "领域背景",
            "problem": "问题与动机",
            "solution": "方法与机制",
            "experiment": "实验与评估",
            "plain_example": "通俗例子",
            "related_work": "相关工作",
            "limitations": "局限与未来工作",
            "critique": "中立批判",
            "evidence": "证据链",
            "why_it_matters": "为什么重要",
            "hidden_assumptions": "隐藏假设",
            "mechanism": "机制",
            "prior_work": "已有工作",
            "repackaging_risk": "重新包装风险",
            "inferred_weaknesses": "推断弱点",
            "future_work": "未来工作",
            "overclaiming_risk": "过度声称风险",
            "weak_evaluations": "薄弱评估",
            "missing_ablations": "缺失消融",
            "no_example": "没有可发布的通俗例子。",
            "no_problem": "没有已核验的问题陈述。",
            "no_solution": "没有已核验的方法陈述。",
            "no_related_work": "没有已核验的相关工作判断。",
            "no_limitations": "没有已核验的局限判断。",
            "no_critique": "没有已核验的批判判断。",
        }
    return {
        "title": "ResearchRadar Paper Brief",
        "essence": "Essence",
        "background": "Background",
        "problem": "Problems and Motivation",
        "solution": "Solution",
        "experiment": "Experiments",
        "plain_example": "Plain-language Example",
        "related_work": "Related Work",
        "limitations": "Limitations and Future Work",
        "critique": "Critique",
        "evidence": "Evidence Trail",
        "why_it_matters": "Why it matters",
        "hidden_assumptions": "Hidden assumptions",
        "mechanism": "Mechanism",
        "prior_work": "Prior work",
        "repackaging_risk": "Repackaging risk",
        "inferred_weaknesses": "Inferred weaknesses",
        "future_work": "Future work",
        "overclaiming_risk": "Overclaiming risk",
        "weak_evaluations": "Weak evaluations",
        "missing_ablations": "Missing ablations",
        "no_example": "No grounded example is available.",
        "no_problem": "No verified problem claim.",
        "no_solution": "No verified solution claim.",
        "no_related_work": "No verified related-work claim.",
        "no_limitations": "No verified limitation claim.",
        "no_critique": "No verified critique claim.",
    }


def _evidence_trail(claims: list[Claim], *, language: str) -> str:
    if not claims:
        return "No publishable claims passed evidence validation."
    blocks = []
    for claim in claims:
        anchors = []
        for anchor in claim.evidence:
            location = f" ({anchor.location})" if anchor.location else ""
            source = anchor.source_title or anchor.source_url
            anchors.append(f"- {source}{location}: {anchor.quote}")
        claim_text = _localized_claim_text(claim.text, language=language)
        blocks.append(claim_text + "\n" + "\n".join(anchors))
    return "\n\n".join(blocks)


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
