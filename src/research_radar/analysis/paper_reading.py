"""Researcher-grade paper reading structures and validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from research_radar.analysis.providers import LLMProvider, Message
from research_radar.evidence.policy import enforce_evidence_policy
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    ReviewFinding,
    dataclass_to_dict,
)


@dataclass(frozen=True)
class AreaContext:
    """Background context needed before judging a paper."""

    background: str
    active_questions: list[str] = field(default_factory=list)
    common_baselines: list[str] = field(default_factory=list)
    evidence: list[EvidenceAnchor] = field(default_factory=list)


@dataclass(frozen=True)
class ProblemSolution:
    """The paper's problem and actual solution mechanism."""

    problem: str
    why_it_matters: str
    hidden_assumptions: list[str]
    solution: str
    mechanism: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class RelatedWorkAssessment:
    """Assessment of novelty against related work."""

    prior_work: list[str]
    novelty: str
    repackaging_risk: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class LimitationAssessment:
    """Explicit and inferred limitations."""

    explicit_limitations: list[str]
    inferred_weaknesses: list[str]
    evidence: list[EvidenceAnchor]
    future_work: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CriticalAssessment:
    """Neutral, evidence-backed critique."""

    overclaiming_risk: str
    weak_evaluations: list[str]
    missing_ablations: list[str]
    bottom_line: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class PaperReading:
    """Structured researcher-grade reading of one paper."""

    title: str
    area_context: AreaContext
    problem_solution: ProblemSolution
    related_work: RelatedWorkAssessment
    limitations: LimitationAssessment
    critical_assessment: CriticalAssessment
    essence: str
    plain_language_example: str
    experiment_summary: str = ""
    experiment_evidence: list[EvidenceAnchor] = field(default_factory=list)
    unsupported_or_rejected_claims: list[str] = field(default_factory=list)


def paper_reading_prompt(
    artifact: Artifact,
    area_context: str | None = None,
    *,
    language: str = "en",
) -> str:
    """Build the structured paper-reading prompt."""

    context = area_context or "Infer only from supplied sources; mark missing context as unknown."
    language_rule = (
        "REPORT LANGUAGE: Simplified Chinese. Every analytical JSON string value must be "
        "Simplified Chinese, including background, problem, motivation, solution, mechanism, "
        "experiments, related work, limitations, critique, plain_language_example, and essence. "
        "Only evidence quote fields may remain in the original source language, because they "
        "must be exact substrings from TEXT."
        if language == "zh"
        else "REPORT LANGUAGE: English. Write all analytical prose in English. Keep evidence "
        "quote fields as exact substrings from TEXT."
    )
    return f"""Run the deep-reading stage for this ResearchRadar source.
Act as a skeptical but fair researcher.
{language_rule}

Area context:
{context}

Paper:
TITLE: {artifact.source.title}
URL: {artifact.source.url}
TEXT:
{artifact.text[:12000]}

Return structured JSON with these fields:
- deep_readings:
  - area_context: background, active_questions, common_baselines, evidence
  - problem_solution: problem, why_it_matters, hidden_assumptions, solution, mechanism, evidence
  - related_work: prior_work, novelty, repackaging_risk, evidence
  - experiments: summary, evidence
  - limitations: explicit_limitations, inferred_weaknesses, future_work, evidence
  - critical_assessment: overclaiming_risk, weak_evaluations, missing_ablations,
    bottom_line, evidence
  - plain_language_example: simple example grounded in the source
  - essence: one sentence describing what the source is really doing
- perspective_questions: follow-up questions from researcher, builder, evaluator, and skeptic views
- evidence_index: anchors used for factual, novelty, limitation, and critique claims
- unsupported_or_rejected_claims: claims you considered but rejected

Rules:
- Separate facts from interpretation and speculation.
- Make problem, motivation, solution, mechanism, experiments, related work, limitations, and
  critique detailed enough for researcher notes: usually 2-4 concrete sentences per field.
- Every factual or critical claim needs evidence in the same section.
- Every section evidence field must be a non-empty list of objects.
- Every evidence object must include quote and location.
- The quote field must be an exact substring copied from TEXT.
- Use short exact quotes; do not clean up hyphenation, symbols, line-break artifacts, or wording.
- Do not use paraphrased evidence anchors.
- Do not turn author framing into your own conclusion unless evidence supports it.
- Be neutral, sharp, and concrete. Do not flatter the paper.
- Do not draft the final article here; this stage feeds an outline-first synthesis step.
- Return JSON only. Do not wrap it in Markdown.

Evidence object shape:
{{"quote": "source-backed anchor", "location": "README section, page, or extracted text"}}
"""


def model_paper_reading(
    artifact: Artifact,
    provider: LLMProvider,
    *,
    model: str,
    area_context: str | None = None,
    language: str = "en",
) -> PaperReading:
    """Run model-based deep reading and parse the structured result."""

    messages = [
        Message(
            role="system",
            content=(
                "You are a skeptical but fair research analyst. "
                f"{_system_language_rule(language)} "
                "Return strict JSON only."
            ),
        ),
        Message(
            role="user",
            content=paper_reading_prompt(artifact, area_context, language=language),
        ),
    ]
    response = provider.complete(messages, model=model)
    return parse_paper_reading(response.content, artifact)


def parse_paper_reading(raw_json: str, artifact: Artifact) -> PaperReading:
    """Parse model JSON into a validated paper-reading structure."""

    payload = _load_json_object(raw_json)
    reading_data = payload.get("deep_readings", payload)
    if isinstance(reading_data, list):
        if not reading_data:
            raise AnalysisError("Paper reading JSON contained no deep readings.")
        reading_data = reading_data[0]
    if not isinstance(reading_data, dict):
        raise AnalysisError("Paper reading JSON must contain an object deep_readings value.")

    fallback_evidence = _parse_evidence(
        payload.get("evidence_index", []),
        artifact,
        required=False,
    )
    reading = PaperReading(
        title=str(reading_data.get("title") or artifact.source.title),
        area_context=_parse_area_context(reading_data.get("area_context", {}), artifact),
        problem_solution=_parse_problem_solution(
            reading_data.get("problem_solution", {}),
            artifact,
            fallback_evidence,
        ),
        related_work=_parse_related_work(
            reading_data.get("related_work")
            or reading_data.get("related_work_analysis")
            or {},
            artifact,
            fallback_evidence,
        ),
        limitations=_parse_limitations(
            reading_data.get("limitations", {}),
            artifact,
            fallback_evidence,
        ),
        critical_assessment=_parse_critical_assessment(
            reading_data.get("critical_assessment", {}),
            artifact,
            fallback_evidence,
        ),
        essence=_required_string(reading_data, "essence"),
        plain_language_example=str(reading_data.get("plain_language_example") or ""),
        experiment_summary=_parse_experiment_summary(reading_data),
        experiment_evidence=_parse_experiment_evidence(
            reading_data,
            artifact,
            fallback_evidence,
        ),
        unsupported_or_rejected_claims=[
            str(item)
            for item in reading_data.get("unsupported_or_rejected_claims", [])
            if str(item).strip()
        ],
    )
    _require_anchor(reading.problem_solution.evidence, "problem_solution")
    _require_anchor(reading.related_work.evidence, "related_work")
    _require_anchor(reading.limitations.evidence, "limitations")
    _require_anchor(reading.critical_assessment.evidence, "critical_assessment")
    return reading


def render_deep_reading_report(
    readings: list[PaperReading],
    claims: list[Claim] | None = None,
    *,
    language: str = "en",
) -> str:
    """Render structured paper readings as a human-readable Markdown audit report."""

    labels = _deep_reading_labels(language)
    lines = [f"# {labels['title']}", ""]
    if not readings:
        lines.append(labels["no_readings"])
        return "\n".join(lines).strip() + "\n"
    allowed = _publishable_prefixes(claims)
    for reading in readings:
        lines.extend([f"## {reading.title}", ""])
        if _can_render("Essence:", allowed):
            lines.extend([f"**{labels['essence']}:** {reading.essence}", ""])
        if _can_render("Problem:", allowed):
            lines.extend(
                [
                    f"### {labels['problem']}",
                    f"**{labels['core']}:** {reading.problem_solution.problem}",
                    f"- {labels['why_it_matters']}: {reading.problem_solution.why_it_matters}",
                    _list_line(
                        labels["hidden_assumptions"],
                        reading.problem_solution.hidden_assumptions,
                        language=language,
                    ),
                    "",
                ]
            )
        if _can_render("Solution:", allowed):
            lines.extend(
                [
                    f"### {labels['solution']}",
                    f"**{labels['core']}:** {reading.problem_solution.solution}",
                    f"- {labels['mechanism']}: {reading.problem_solution.mechanism}",
                    "",
                ]
            )
        if _can_render("Experiment:", allowed):
            lines.extend(
                [
                    f"### {labels['experiments']}",
                    (
                        f"**{labels['core']}:** "
                        f"{reading.experiment_summary or labels['no_experiment']}"
                    ),
                    "",
                ]
            )
        if reading.plain_language_example:
            lines.extend(
                [
                    f"### {labels['plain_example']}",
                    reading.plain_language_example,
                    "",
                ]
            )
        if _can_render("Related work:", allowed):
            lines.extend(
                [
                    f"### {labels['related_work']}",
                    f"**{labels['core']}:** {reading.related_work.novelty}",
                    _list_line(
                        labels["prior_work"],
                        reading.related_work.prior_work,
                        language=language,
                    ),
                    f"- {labels['repackaging_risk']}: {reading.related_work.repackaging_risk}",
                    "",
                ]
            )
        if _can_render("Limitations:", allowed):
            explicit = reading.limitations.explicit_limitations
            inferred = reading.limitations.inferred_weaknesses
            lines.extend(
                [
                    f"### {labels['limitations']}",
                    f"**{labels['core']}:** {_first_or_none(explicit, labels['no_limitations'])}",
                    _list_line(labels["explicit_limitations"], explicit, language=language),
                    _list_line(labels["inferred_weaknesses"], inferred, language=language),
                    _list_line(
                        labels["future_work"],
                        reading.limitations.future_work,
                        language=language,
                    ),
                    "",
                ]
            )
        if _can_render("Critical assessment:", allowed):
            lines.extend(
                [
                    f"### {labels['critical']}",
                    f"**{labels['core']}:** {reading.critical_assessment.bottom_line}",
                    (
                        f"- {labels['overclaiming_risk']}: "
                        f"{reading.critical_assessment.overclaiming_risk}"
                    ),
                    _list_line(
                        labels["weak_evaluations"],
                        reading.critical_assessment.weak_evaluations,
                        language=language,
                    ),
                    _list_line(
                        labels["missing_ablations"],
                        reading.critical_assessment.missing_ablations,
                        language=language,
                    ),
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def reading_to_dict(reading: PaperReading) -> dict[str, object]:
    """Convert a paper reading to a JSON-friendly dictionary."""

    return dataclass_to_dict(reading)


def _publishable_prefixes(claims: list[Claim] | None) -> set[str] | None:
    if claims is None:
        return None
    prefixes = set()
    for claim in claims:
        if not claim.is_publishable():
            continue
        prefix, separator, _ = claim.text.partition(":")
        if separator:
            prefixes.add(f"{prefix.casefold()}:")
    return prefixes


def _can_render(prefix: str, allowed: set[str] | None) -> bool:
    return allowed is None or prefix.casefold() in allowed


def _list_line(label: str, values: list[str], *, language: str = "en") -> str:
    if not values:
        empty = "未捕捉到" if language == "zh" else "none captured"
        return f"- {label}: {empty}"
    return f"- {label}: " + "; ".join(values)


def _deep_reading_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "title": "深度阅读报告",
            "no_readings": "没有生成深度阅读结果。",
            "essence": "本质判断",
            "problem": "问题与动机",
            "solution": "方法与机制",
            "experiments": "实验与评估",
            "plain_example": "通俗例子",
            "related_work": "相关工作",
            "limitations": "局限与未来工作",
            "critical": "中立批判",
            "core": "核心判断",
            "why_it_matters": "为什么重要",
            "hidden_assumptions": "隐藏假设",
            "mechanism": "机制",
            "no_experiment": "没有捕捉到实验摘要。",
            "prior_work": "已有工作",
            "repackaging_risk": "重新包装风险",
            "no_limitations": "没有捕捉到明确局限。",
            "explicit_limitations": "作者明确局限",
            "inferred_weaknesses": "推断弱点",
            "future_work": "未来工作",
            "overclaiming_risk": "过度声称风险",
            "weak_evaluations": "薄弱评估",
            "missing_ablations": "缺失消融",
        }
    return {
        "title": "Deep Reading Report",
        "no_readings": "No deep readings were produced.",
        "essence": "Essence",
        "problem": "Problems and Motivation",
        "solution": "Solution",
        "experiments": "Experiments",
        "plain_example": "Plain-language Example",
        "related_work": "Related Work",
        "limitations": "Limitations and Future Work",
        "critical": "Critical Assessment",
        "core": "Core",
        "why_it_matters": "Why it matters",
        "hidden_assumptions": "Hidden assumptions",
        "mechanism": "Mechanism",
        "no_experiment": "No experiment summary captured.",
        "prior_work": "Prior work",
        "repackaging_risk": "Repackaging risk",
        "no_limitations": "No explicit limitations captured.",
        "explicit_limitations": "Explicit limitations",
        "inferred_weaknesses": "Inferred weaknesses",
        "future_work": "Future work",
        "overclaiming_risk": "Overclaiming risk",
        "weak_evaluations": "Weak evaluations",
        "missing_ablations": "Missing ablations",
    }


def _system_language_rule(language: str) -> str:
    if language == "zh":
        return (
            "All analytical JSON string values must be Simplified Chinese; only evidence "
            "quote strings may preserve original source wording."
        )
    return "All analytical JSON string values must be English."


def _first_or_none(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def reading_to_claims(reading: PaperReading) -> list[Claim]:
    """Convert a structured paper reading into evidence-bound claims."""

    return [
        _claim(
            f"Problem: {reading.problem_solution.problem}",
            reading.problem_solution.evidence,
            "Paper problem statement.",
        ),
        _claim(
            f"Solution: {reading.problem_solution.solution}",
            reading.problem_solution.evidence,
            "Paper solution summary.",
        ),
        _claim(
            f"Related work: {reading.related_work.novelty}",
            reading.related_work.evidence,
            "Novelty assessment against related work.",
        ),
        *(
            [
                _claim(
                    f"Experiment: {reading.experiment_summary}",
                    reading.experiment_evidence,
                    "Experiment or evaluation summary.",
                )
            ]
            if reading.experiment_summary
            else []
        ),
        *(
            [
                _claim(
                    f"Limitations: {'; '.join(reading.limitations.explicit_limitations)}",
                    reading.limitations.evidence,
                    "Explicit limitations reported or supported by the paper.",
                )
            ]
            if reading.limitations.explicit_limitations
            else []
        ),
        _claim(
            f"Critical assessment: {reading.critical_assessment.bottom_line}",
            reading.critical_assessment.evidence,
            "Neutral critique backed by evaluation or method evidence.",
        ),
        _claim(
            f"Essence: {reading.essence}",
            _combined_evidence(reading),
            "One-sentence essence of the paper.",
        ),
        *[
            Claim(
                text=text,
                status=ClaimStatus.UNSUPPORTED,
                rationale="Rejected during paper reading.",
            )
            for text in reading.unsupported_or_rejected_claims
        ],
    ]


def validate_paper_reading(
    reading: PaperReading,
    artifact: Artifact | None = None,
) -> tuple[list[Claim], list[ReviewFinding]]:
    """Validate that paper-reading claims are evidence-backed before publication."""

    claims, findings = enforce_evidence_policy(reading_to_claims(reading))
    if artifact is None:
        return claims, findings
    checked_claims: list[Claim] = []
    for claim in claims:
        if not claim.is_publishable():
            checked_claims.append(claim)
            continue
        valid_evidence = [
            anchor for anchor in claim.evidence if _quote_found(anchor.quote, artifact.text)
        ]
        if len(valid_evidence) == len(claim.evidence):
            checked_claims.append(claim)
            continue
        missing_count = len(claim.evidence) - len(valid_evidence)
        if valid_evidence:
            checked_claims.append(
                replace(
                    claim,
                    evidence=valid_evidence,
                    metadata={
                        **claim.metadata,
                        "evidence_validation": {
                            "status": "partial",
                            "missing_anchor_count": missing_count,
                        },
                    },
                )
            )
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message="Some evidence anchors were not found in the ingested text.",
                    claim_text=claim.text,
                    metadata={
                        "kind": "evidence_anchor_unmatched",
                        "missing_anchor_count": missing_count,
                    },
                )
            )
            continue
        checked_claims.append(
            replace(
                claim,
                status=ClaimStatus.UNSUPPORTED,
                evidence=[],
                metadata={
                    **claim.metadata,
                    "evidence_validation": {
                        "status": "failed",
                        "missing_anchor_count": missing_count,
                    },
                },
            )
        )
        findings.append(
            ReviewFinding(
                severity="error",
                message="No evidence anchors for this claim were found in the ingested text.",
                claim_text=claim.text,
                metadata={
                    "kind": "evidence_anchor_unmatched",
                    "missing_anchor_count": missing_count,
                },
            )
        )
    return checked_claims, findings


def heuristic_paper_reading(artifact: Artifact) -> PaperReading:
    """Build a conservative reading from labeled fixture-like text."""

    text = artifact.text
    anchor = EvidenceAnchor(
        source_url=artifact.source.url,
        source_title=artifact.source.title,
        quote=text[:500],
        location="extracted text",
        confidence=0.8,
    )
    return PaperReading(
        title=artifact.source.title,
        area_context=AreaContext(
            background=_section(text, "Background") or "Area background is not established.",
            active_questions=[_section(text, "Question")] if _section(text, "Question") else [],
            common_baselines=[_section(text, "Baseline")] if _section(text, "Baseline") else [],
            evidence=[anchor],
        ),
        problem_solution=ProblemSolution(
            problem=_section(text, "Problem") or "Problem is not clearly stated.",
            why_it_matters=_section(text, "Motivation") or "Motivation is not clearly stated.",
            hidden_assumptions=[_section(text, "Assumption")]
            if _section(text, "Assumption")
            else [],
            solution=_section(text, "Solution") or "Solution is not clearly stated.",
            mechanism=_section(text, "Mechanism") or "Mechanism is not clearly stated.",
            evidence=[anchor],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=[_section(text, "Related Work")] if _section(text, "Related Work") else [],
            novelty=_section(text, "Novelty") or "Novelty is not established.",
            repackaging_risk=_section(text, "Repackaging Risk") or "Repackaging risk is unknown.",
            evidence=[anchor],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=[_section(text, "Limitation")]
            if _section(text, "Limitation")
            else [],
            inferred_weaknesses=[_section(text, "Weakness")] if _section(text, "Weakness") else [],
            evidence=[anchor],
            future_work=[_section(text, "Future Work")] if _section(text, "Future Work") else [],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk=_section(text, "Overclaiming") or "Overclaiming risk is unknown.",
            weak_evaluations=[_section(text, "Weak Evaluation")]
            if _section(text, "Weak Evaluation")
            else [],
            missing_ablations=[_section(text, "Missing Ablation")]
            if _section(text, "Missing Ablation")
            else [],
            bottom_line=(
                _section(text, "Critical Bottom Line")
                or "Critical bottom line is unknown."
            ),
            evidence=[anchor],
        ),
        experiment_summary=_section(text, "Experiment"),
        experiment_evidence=[anchor] if _section(text, "Experiment") else [],
        essence=_section(text, "Essence") or "The paper's essence is not established.",
        plain_language_example=_section(text, "Example") or "No grounded example is available.",
        unsupported_or_rejected_claims=[
            _section(text, "Unsupported Claim")
        ]
        if _section(text, "Unsupported Claim")
        else [],
    )


def _claim(text: str, evidence: list[EvidenceAnchor], rationale: str) -> Claim:
    status = ClaimStatus.SUPPORTED if evidence else ClaimStatus.UNSUPPORTED
    return Claim(text=text, status=status, evidence=evidence, rationale=rationale)


def _combined_evidence(reading: PaperReading) -> list[EvidenceAnchor]:
    return [
        *reading.problem_solution.evidence,
        *reading.related_work.evidence,
        *reading.limitations.evidence,
        *reading.critical_assessment.evidence,
    ]


def _section(text: str, label: str) -> str:
    prefix = f"{label}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix.lower()):
            return stripped[len(prefix) :].strip()
    return ""


def _load_json_object(raw_json: str) -> dict[str, object]:
    text = raw_json.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError("Paper reading response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise AnalysisError("Paper reading JSON must be an object.")
    return payload


def _parse_area_context(value: object, artifact: Artifact) -> AreaContext:
    data = _mapping(value, "area_context")
    return AreaContext(
        background=_required_string(data, "background"),
        active_questions=_string_list(data.get("active_questions", [])),
        common_baselines=_string_list(data.get("common_baselines", [])),
        evidence=_parse_evidence(data.get("evidence", []), artifact, required=False),
    )


def _parse_problem_solution(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> ProblemSolution:
    data = _mapping(value, "problem_solution")
    return ProblemSolution(
        problem=_required_string(data, "problem"),
        why_it_matters=_required_string(data, "why_it_matters"),
        hidden_assumptions=_string_list(data.get("hidden_assumptions", [])),
        solution=_required_string(data, "solution"),
        mechanism=_required_string(data, "mechanism"),
        evidence=_section_evidence(data, artifact, fallback_evidence),
    )


def _parse_related_work(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> RelatedWorkAssessment:
    data = _mapping(value, "related_work")
    return RelatedWorkAssessment(
        prior_work=_string_list(data.get("prior_work", [])),
        novelty=_required_string(data, "novelty"),
        repackaging_risk=_required_string(data, "repackaging_risk"),
        evidence=_section_evidence(data, artifact, fallback_evidence),
    )


def _parse_limitations(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> LimitationAssessment:
    data = _mapping(value, "limitations")
    return LimitationAssessment(
        explicit_limitations=_string_list(data.get("explicit_limitations", [])),
        inferred_weaknesses=_string_list(data.get("inferred_weaknesses", [])),
        evidence=_section_evidence(data, artifact, fallback_evidence),
        future_work=_string_list(data.get("future_work", [])),
    )


def _parse_critical_assessment(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> CriticalAssessment:
    data = _mapping(value, "critical_assessment")
    return CriticalAssessment(
        overclaiming_risk=_required_string(data, "overclaiming_risk"),
        weak_evaluations=_string_list(data.get("weak_evaluations", [])),
        missing_ablations=_string_list(data.get("missing_ablations", [])),
        bottom_line=_required_string(data, "bottom_line"),
        evidence=_section_evidence(data, artifact, fallback_evidence),
    )


def _parse_experiment_summary(data: dict[str, object]) -> str:
    experiments = data.get("experiments") or data.get("experiment")
    if isinstance(experiments, dict):
        return str(
            experiments.get("summary")
            or experiments.get("evaluation")
            or experiments.get("headline_results")
            or ""
        ).strip()
    return str(data.get("experiment_summary") or "").strip()


def _parse_experiment_evidence(
    data: dict[str, object],
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> list[EvidenceAnchor]:
    experiments = data.get("experiments") or data.get("experiment")
    if isinstance(experiments, dict):
        return _section_evidence(experiments, artifact, fallback_evidence)
    return _parse_evidence(data.get("experiment_evidence", []), artifact, required=False)


def _section_evidence(
    data: dict[str, object],
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> list[EvidenceAnchor]:
    anchors = _parse_evidence(
        data.get("evidence")
        or data.get("evidence_anchors")
        or data.get("citations")
        or [],
        artifact,
        required=False,
    )
    return anchors or fallback_evidence


def _parse_evidence(
    value: object,
    artifact: Artifact,
    *,
    required: bool,
) -> list[EvidenceAnchor]:
    if not isinstance(value, list):
        if required:
            raise AnalysisError("Evidence must be a list.")
        return []
    anchors: list[EvidenceAnchor] = []
    for item in value:
        if isinstance(item, str):
            quote = item.strip()
            if quote:
                anchors.append(
                    EvidenceAnchor(
                        source_url=artifact.source.url,
                        source_title=artifact.source.title,
                        quote=quote,
                        location="model anchor",
                        confidence=0.7,
                    )
                )
            continue
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or item.get("snippet") or item.get("anchor") or "").strip()
        if not quote:
            continue
        anchors.append(
            EvidenceAnchor(
                source_url=artifact.source.url,
                source_title=artifact.source.title,
                quote=quote,
                location=str(item.get("location") or item.get("section") or "model anchor"),
                confidence=float(item.get("confidence", 0.7)),
            )
        )
    if required and not anchors:
        raise AnalysisError("Expected at least one evidence anchor.")
    return anchors


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AnalysisError(f"Paper reading field must be an object: {name}")
    return value


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AnalysisError(f"Paper reading field is required: {key}")
    return value.strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _require_anchor(evidence: list[EvidenceAnchor], section: str) -> None:
    if not evidence:
        raise AnalysisError(f"Paper reading section has no evidence anchors: {section}")


def _quote_found(quote: str, text: str) -> bool:
    normalized_quote = _normalize_evidence_text(quote)
    if not normalized_quote:
        return False
    normalized_text = _normalize_evidence_text(text)
    if normalized_quote in normalized_text:
        return True
    compact_quote = _compact_evidence_text(normalized_quote)
    if len(compact_quote) < 12:
        return False
    return compact_quote in _compact_evidence_text(normalized_text)


def _normalize_evidence_text(text: str) -> str:
    without_controls = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", text)
    without_soft_hyphen = without_controls.replace("\xad", "")
    dehyphenated = re.sub(r"(?<=[a-zA-Z])-\s+(?=[a-zA-Z])", "", without_soft_hyphen)
    return re.sub(r"\s+", " ", dehyphenated).strip().lower()


def _compact_evidence_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())
