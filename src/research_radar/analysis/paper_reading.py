"""Researcher-grade paper reading structures and validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from research_radar.analysis.paper_sections import (
    PaperReadingPacket,
    build_reading_packet,
    render_reading_packet,
)
from research_radar.analysis.prompts import RESEARCH_RADAR_RUNTIME_CONTRACT
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
from research_radar.security.redaction import redact_text


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
class ClaimUnit:
    """One atomic, evidence-backed claim emitted by a paper reading."""

    section: str
    claim_kind: str
    text: str
    evidence: list[EvidenceAnchor]
    publishable_default: bool = True


@dataclass(frozen=True)
class ReaderExplanation:
    """Reader-facing explanation that must stay within verified paper evidence."""

    opening_context: str = ""
    core_thesis: str = ""
    problem_walkthrough: str = ""
    solution_walkthrough: str = ""
    experiment_interpretation: str = ""
    related_work_context: str = ""
    limitations_discussion: str = ""
    plain_language_story: str = ""
    reader_takeaway: str = ""


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
    claim_units: list[ClaimUnit] = field(default_factory=list)
    reader_explanation: ReaderExplanation = field(default_factory=ReaderExplanation)


@dataclass(frozen=True)
class ReaderAttempt:
    """One model attempt to produce structured paper-reading JSON."""

    attempt_index: int
    provider: str
    model: str
    status: str
    error_message: str | None = None
    response_excerpt: str = ""


@dataclass(frozen=True)
class PaperReadingResult:
    """Parsed paper reading plus structured attempt audit."""

    reading: PaperReading
    attempts: list[ReaderAttempt]


def paper_reading_prompt(
    artifact: Artifact,
    area_context: str | None = None,
    *,
    language: str = "en",
    packet: PaperReadingPacket | None = None,
) -> str:
    """Build the structured paper-reading prompt."""

    context = area_context or "Infer only from supplied sources; mark missing context as unknown."
    reading_packet = packet or build_reading_packet(artifact)
    language_rule = (
        "REPORT LANGUAGE: Simplified Chinese. Every analytical JSON string value must be "
        "Simplified Chinese, including background, problem, motivation, solution, mechanism, "
        "experiments, related work, limitations, critique, plain_language_example, and essence. "
        "Only evidence quote fields may remain in the original source language, because they "
        "must be exact substrings from the full paper reading packet."
        if language == "zh"
        else "REPORT LANGUAGE: English. Write all analytical prose in English. Keep evidence "
        "quote fields as exact substrings from the full paper reading packet."
    )
    return f"""{RESEARCH_RADAR_RUNTIME_CONTRACT}

Run the deep-reading stage for this ResearchRadar source.
Act as a skeptical but fair researcher.
{language_rule}

Area context:
{context}

Paper:
TITLE: {artifact.source.title}
URL: {artifact.source.url}
{render_reading_packet(reading_packet)}

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
  - claim_units: required list of atomic claims for verification and publication
  - reader_explanation: opening_context, core_thesis, problem_walkthrough,
    solution_walkthrough, experiment_interpretation, related_work_context,
    limitations_discussion, plain_language_story, reader_takeaway
- perspective_questions: follow-up questions from researcher, builder, evaluator, and skeptic views
- evidence_index: anchors used for factual, novelty, limitation, and critique claims
- unsupported_or_rejected_claims: claims you considered but rejected

Rules:
- Separate facts from interpretation and speculation.
- reader_explanation is the reader-facing explanation layer. Write it as natural
  research prose, not bullet fragments: each field should usually be 1-3 concise
  paragraphs that walk a technical reader from motivation to mechanism to evidence.
- reader_explanation must not introduce any new facts, URLs, rankings, critique, or
  speculation beyond the anchored section fields and claim_units. If a point cannot
  be grounded in the supplied packet, omit it or mark it unknown in unsupported_or_rejected_claims.
- Use reader_explanation to make the paper understandable: explain why the problem
  matters, how the mechanism works step by step, how to read the experiments, how
  related work frames the contribution, what the limitations mean in practice, and
  give one plain-language story that follows only verified technical claims.
- opening_context should work as a short background primer for ordinary technical
  readers: explain the broader area problem first, then why this specific paper is
  worth reading.
- solution_walkthrough must be the most detailed explanation field. Cover the main
  components, data flow, why each step exists, how components interact, and how the
  mechanism connects to reported experiments. Only include components supported by
  anchored evidence.
- Keep each claim_unit to exactly one verifiable assertion; split broad claims.
- claim_units must not combine method, result, novelty, and critique in one sentence.
- Setup facts must be separate claim_units: benchmark identity, metric definition,
  default backbone, embedding model, top-k retrieval, decoding, context length,
  hardware/time limit, performance result, cost result, and limitation each need
  their own atomic claim.
- Do not write combined setup claims such as "default backbone + embedding model +
  top-k + greedy decoding"; split them into separate claim_units with separate
  evidence quotes.
- Do not combine method design with reported performance, result with cost, ranking
  with causal explanation, or factual setup with critique.
- claim_units must cover the publishable factual, method, experiment, limitation, critique,
  and essence statements you want downstream article generation to use.
- claim_units may include facts, interpretation, novelty, limitation, critique, or essence,
  but every publishable_default=true unit must have exact evidence anchors.
- If a section-level conclusion is broad, put only the precise supported subclaims in
  claim_units and move the broad wording to unsupported_or_rejected_claims.
- Related work must extract concrete representative methods, baselines, datasets, or
  benchmarks explicitly named in the paper. If none are available, write "unknown"; do
  not fill the gap with generic novelty prose. Put named methods into
  related_work.prior_work, not only into area_context.common_baselines.
- Experiments must separate setup, metrics or benchmarks, main findings, cost or
  robustness findings, and known caveats. If the paper does not support one part,
  say "unknown" instead of guessing.
- Experiment and result claims must prefer evidence from experiments_results chunks.
- Limitations must separate paper-explicit limitations, evidence-backed inferred
  weaknesses, and critique that needs external verification.
- Limitations and critique must prefer evidence from limitations_conclusion chunks or
  explicit evaluation evidence. If the packet has a coverage warning, mention the gap
  in unsupported_or_rejected_claims instead of inventing the missing section.
- Author-reported superlatives such as best, state-of-the-art, or outperforms must be
  phrased as author-reported claims unless independently verified by supplied evidence.
- Broad essence statements must not bundle multiple contributions. Split them into
  separate atomic claim_units and keep only a narrow essence claim publishable by default.
- Make problem, motivation, solution, mechanism, experiments, related work, limitations, and
  critique detailed enough for researcher notes: usually 2-4 concrete sentences per field.
- Every factual or critical claim needs evidence in the same section.
- Every section evidence field must be a non-empty list of objects.
- Every evidence object must include quote and location.
- The quote field must be an exact substring copied from the full paper reading packet.
- Use short exact quotes; do not clean up hyphenation, symbols, line-break artifacts, or wording.
- Do not use paraphrased evidence anchors.
- Do not turn author framing into your own conclusion unless evidence supports it.
- Be neutral, sharp, and concrete. Do not flatter the paper.
- Do not draft the final article here; this stage feeds an outline-first synthesis step.
- Return JSON only. Do not wrap it in Markdown.

Evidence object shape:
{{"quote": "source-backed anchor", "location": "README section, page, or extracted text"}}
Claim unit shape:
{{"section": "problem|solution|experiment|related_work|limitations|critical_assessment|essence",
  "claim_kind": "fact|interpretation|novelty|limitation|critique|essence",
  "text": "one atomic assertion",
  "evidence": [{{"quote": "exact substring", "location": "section or page"}}],
  "publishable_default": true}}
"""


def model_paper_reading(
    artifact: Artifact,
    provider: LLMProvider,
    *,
    model: str,
    area_context: str | None = None,
    language: str = "en",
    packet: PaperReadingPacket | None = None,
) -> PaperReading:
    """Run model-based deep reading and parse the structured result."""

    return model_paper_reading_with_attempts(
        artifact,
        provider,
        model=model,
        area_context=area_context,
        language=language,
        packet=packet,
    ).reading


def model_paper_reading_with_attempts(
    artifact: Artifact,
    provider: LLMProvider,
    *,
    model: str,
    area_context: str | None = None,
    language: str = "en",
    packet: PaperReadingPacket | None = None,
) -> PaperReadingResult:
    """Run model-based deep reading with one schema retry and attempt audit."""

    reading_packet = packet or build_reading_packet(artifact)
    user_prompt = paper_reading_prompt(
        artifact,
        area_context,
        language=language,
        packet=reading_packet,
    )
    messages = [
        Message(
            role="system",
            content=(
                "You are a skeptical but fair research analyst. "
                f"{_system_language_rule(language)} "
                "Return strict JSON only."
            ),
        ),
        Message(role="user", content=user_prompt),
    ]
    attempts: list[ReaderAttempt] = []
    last_error = ""
    current_messages = messages
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    for attempt_index in (1, 2):
        response = provider.complete(current_messages, model=model)
        excerpt = _response_excerpt(response.content)
        try:
            reading = parse_paper_reading(response.content, artifact)
        except AnalysisError as exc:
            last_error = str(exc)
            attempts.append(
                ReaderAttempt(
                    attempt_index=attempt_index,
                    provider=provider_name,
                    model=model,
                    status="failed",
                    error_message=last_error,
                    response_excerpt=excerpt,
                )
            )
            if attempt_index == 2:
                break
            current_messages = [
                messages[0],
                Message(
                    role="user",
                    content=_retry_paper_reading_prompt(
                        original_prompt=user_prompt,
                        error_message=last_error,
                        response_excerpt=excerpt,
                    ),
                ),
            ]
            continue
        attempts.append(
            ReaderAttempt(
                attempt_index=attempt_index,
                provider=provider_name,
                model=model,
                status="succeeded",
                response_excerpt=excerpt,
            )
        )
        return PaperReadingResult(reading=reading, attempts=attempts)

    raise AnalysisError(f"Paper reading failed after 2 attempts: {last_error}")


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
        essence=_optional_string(reading_data, "essence", fallback="unknown"),
        plain_language_example=_plain_language_example(reading_data.get("plain_language_example")),
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
        claim_units=_parse_claim_units(
            reading_data.get("claim_units") or payload.get("claim_units", []),
            artifact,
        ),
        reader_explanation=_parse_reader_explanation(
            reading_data.get("reader_explanation", {}),
        ),
    )
    _require_anchor(reading.problem_solution.evidence, "problem_solution")
    _require_anchor(reading.related_work.evidence, "related_work")
    _require_anchor(reading.limitations.evidence, "limitations")
    _require_anchor(reading.critical_assessment.evidence, "critical_assessment")
    return reading


def _retry_paper_reading_prompt(
    *,
    original_prompt: str,
    error_message: str,
    response_excerpt: str,
) -> str:
    """Build a prompt for retrying malformed paper-reading JSON."""

    return f"""Repair the previous paper-reading JSON response.

The previous response could not be parsed or failed required schema validation.
Error: {error_message}

Previous response excerpt:
{response_excerpt}

Return a complete replacement JSON object, not a patch, diff, explanation, or Markdown.
Do not omit required fields. Do not invent new claims to fill missing schema fields.
Keep all ResearchRadar evidence rules unchanged:
- every evidence quote must be an exact substring from the full paper reading packet;
- do not clean up hyphenation, symbols, line-break artifacts, or wording;
- keep claim_units atomic;
- do not relax quote matching, claim lint, or anchor completeness.

Original task and source packet:
{original_prompt}
"""


def _response_excerpt(value: str, *, limit: int = 800) -> str:
    """Return a short, redacted response excerpt for audit logs."""

    excerpt = redact_text(value.strip())
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[:limit].rstrip() + "..."


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
        lines.extend(_reader_explanation_lines(reading.reader_explanation, labels))
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


def _reader_explanation_lines(
    explanation: ReaderExplanation,
    labels: dict[str, str],
) -> list[str]:
    sections = [
        ("opening_context", labels["opening_context"]),
        ("core_thesis", labels["core_thesis"]),
        ("problem_walkthrough", labels["problem"]),
        ("solution_walkthrough", labels["solution"]),
        ("experiment_interpretation", labels["experiments"]),
        ("related_work_context", labels["related_work"]),
        ("limitations_discussion", labels["limitations"]),
        ("plain_language_story", labels["plain_example"]),
        ("reader_takeaway", labels["reader_takeaway"]),
    ]
    lines: list[str] = []
    for key, label in sections:
        text = str(getattr(explanation, key, "")).strip()
        if text:
            lines.extend([f"### {label}", text, ""])
    return lines


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
            "opening_context": "背景知识速读",
            "core_thesis": "核心判断",
            "reader_takeaway": "读者 takeaway",
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
        "opening_context": "Opening Context",
        "core_thesis": "Core Thesis",
        "reader_takeaway": "Reader Takeaway",
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

    if reading.claim_units:
        return [
            *_claim_units_to_claims(reading.claim_units),
            *[
                Claim(
                    text=text,
                    status=ClaimStatus.UNSUPPORTED,
                    rationale="Rejected during paper reading.",
                    metadata={"paper_reading": {"source": "unsupported_or_rejected_claims"}},
                )
                for text in reading.unsupported_or_rejected_claims
            ],
        ]
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
        *(
            [
                _claim(
                    f"Essence: {reading.essence}",
                    _combined_evidence(reading),
                    "One-sentence essence of the paper.",
                )
            ]
            if reading.essence != "unknown"
            else []
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


def _claim_units_to_claims(units: list[ClaimUnit]) -> list[Claim]:
    claims = []
    for unit in units:
        status, status_reason = _claim_unit_initial_status(unit)
        claims.append(
            Claim(
                text=_claim_unit_text(unit),
                status=status,
                evidence=unit.evidence,
                rationale="Atomic paper-reading claim.",
                metadata={
                    "paper_reading": {
                        "source": "claim_units",
                        "section": unit.section,
                        "claim_kind": unit.claim_kind,
                        "publishable_default": unit.publishable_default,
                        "status_reason": status_reason,
                    },
                },
            )
        )
    return claims


def _claim_unit_initial_status(unit: ClaimUnit) -> tuple[ClaimStatus, str]:
    if not unit.evidence:
        return ClaimStatus.UNSUPPORTED, "missing evidence"
    if not unit.publishable_default:
        return ClaimStatus.NEEDS_REVIEW, "not publishable by default"
    lint_reason = _claim_lint_reason(unit)
    if lint_reason is not None:
        return ClaimStatus.NEEDS_REVIEW, lint_reason
    if _requires_author_report_attribution(unit.text):
        return ClaimStatus.NEEDS_REVIEW, "author-reported superlative needs attribution"
    if _bundles_multiple_essence_claims(unit):
        return ClaimStatus.NEEDS_REVIEW, "essence bundles multiple claims"
    if _requires_external_verification(unit):
        return ClaimStatus.NEEDS_REVIEW, "claim requires external verification"
    return ClaimStatus.SUPPORTED, "supported by supplied evidence"


def _claim_lint_reason(unit: ClaimUnit) -> str | None:
    text = _strip_claim_prefix(unit.text).casefold()
    setup_facets = [
        _has_any(text, ("backbone", "llm backbone")),
        _has_any(text, ("embedding model", "sentence-transformer", "all-minilm")),
        _has_any(text, ("top-k", "top k", "k=10", "retrieval uses k")),
        _has_any(text, ("greedy decoding", "decoding")),
        _has_any(text, ("context length", "context window")),
        _has_any(text, ("gpu", "a100", "two days", "time limit")),
    ]
    if sum(1 for matched in setup_facets if matched) > 1:
        return "claim too broad; split setup facets"
    has_method = _has_any(
        text,
        (
            "integrates",
            "combines",
            "proposes",
            "introduces",
            "tree-based",
            "hierarchical storage",
            "framework",
        ),
    )
    has_result = _has_result_marker(text)
    if has_method and has_result:
        return "claim too broad; split method and result"
    has_cost = _has_any(
        text,
        (
            "token cost",
            "tokens per",
            "cost",
            "overhead",
            "latency",
            "computational overhead",
        ),
    )
    if has_result and has_cost:
        return "claim too broad; split result and cost"
    has_ranking = _has_any(text, ("top-performing", "competitive", "outperform", "best"))
    has_causal = _has_any(text, ("due to", "attributed", "may explain", "because", "likely"))
    if has_ranking and has_causal:
        return "claim too broad; split ranking and causal explanation"
    has_fact_setup = _has_any(text, ("benchmark", "metric", "dataset", "backbone"))
    has_critique = _has_any(text, ("may not", "does not reflect", "not reflect", "limiting"))
    if has_fact_setup and has_critique:
        return "claim too broad; split fact and critique"
    return None


def _strip_claim_prefix(text: str) -> str:
    return re.sub(r"^\s*[A-Za-z _-]+:\s*", "", text).strip()


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_result_marker(text: str) -> bool:
    return _has_any(
        text,
        (
            "performance",
            "result",
            "score",
            "outperform",
            "outperforms",
            "best",
            "improvement",
            "achieves",
            "f1",
            "bleu",
        ),
    )


def _requires_author_report_attribution(text: str) -> bool:
    normalized = text.casefold()
    superlatives = (
        "best",
        "state-of-the-art",
        "sota",
        "outperform",
        "outperforms",
        "outperformed",
    )
    if not any(term in normalized for term in superlatives):
        return False
    attribution_markers = (
        "author reports",
        "authors report",
        "author-reported",
        "paper reports",
        "paper claims",
        "the paper reports",
        "the paper claims",
        "reported by the authors",
        "claimed by the authors",
    )
    return not any(marker in normalized for marker in attribution_markers)


def _bundles_multiple_essence_claims(unit: ClaimUnit) -> bool:
    if unit.section.strip().casefold() != "essence":
        return False
    normalized = unit.text.casefold()
    contribution_verbs = ("proposes", "introduces", "compares", "evaluates", "reports")
    verb_count = sum(1 for verb in contribution_verbs if verb in normalized)
    return verb_count >= 2


def _requires_external_verification(unit: ClaimUnit) -> bool:
    if unit.claim_kind.strip().casefold() not in {"critique", "limitation"}:
        return False
    normalized = unit.text.casefold()
    external_markers = (
        "independent replication",
        "externally validated",
        "external validation",
        "not replicated",
    )
    return any(marker in normalized for marker in external_markers)


def _claim_unit_text(unit: ClaimUnit) -> str:
    text = unit.text.strip()
    prefix = _claim_unit_prefix(unit.section)
    if text.casefold().startswith(prefix.casefold()):
        return text
    return f"{prefix} {text}"


def _claim_unit_prefix(section: str) -> str:
    normalized = section.strip().casefold().replace("-", "_").replace(" ", "_")
    prefixes = {
        "problem": "Problem:",
        "problem_solution": "Problem:",
        "motivation": "Problem:",
        "solution": "Solution:",
        "mechanism": "Solution:",
        "experiment": "Experiment:",
        "experiments": "Experiment:",
        "evaluation": "Experiment:",
        "related_work": "Related work:",
        "related_work_analysis": "Related work:",
        "novelty": "Related work:",
        "limitations": "Limitations:",
        "limitation": "Limitations:",
        "future_work": "Limitations:",
        "critical": "Critical assessment:",
        "critique": "Critical assessment:",
        "critical_assessment": "Critical assessment:",
        "essence": "Essence:",
    }
    return prefixes.get(normalized, f"{section.strip() or 'Claim'}:")


def validate_paper_reading(
    reading: PaperReading,
    artifact: Artifact | None = None,
) -> tuple[list[Claim], list[ReviewFinding]]:
    """Validate that paper-reading claims are evidence-backed before publication."""

    claims, findings = enforce_evidence_policy(reading_to_claims(reading))
    findings.extend(_claim_lint_findings(claims))
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


def _claim_lint_findings(claims: list[Claim]) -> list[ReviewFinding]:
    findings = []
    for claim in claims:
        reason = str(claim.metadata.get("paper_reading", {}).get("status_reason") or "")
        if not reason.startswith("claim too broad"):
            continue
        findings.append(
            ReviewFinding(
                severity="warning",
                message=f"Claim lint requires splitting: {reason}",
                claim_text=claim.text,
                metadata={"kind": "claim_lint", "reason": reason},
            )
        )
    return findings


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
    text = _extract_json_object_text(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError("Paper reading response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise AnalysisError("Paper reading JSON must be an object.")
    return payload


def _extract_json_object_text(text: str) -> str:
    if text.startswith("{"):
        return text
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


def _parse_area_context(value: object, artifact: Artifact) -> AreaContext:
    data = _mapping(value, "area_context")
    return AreaContext(
        background=_optional_string(
            data,
            "background",
            aliases=("area_background", "background_context", "context"),
            fallback="unknown",
        ),
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
        summary = (
            experiments.get("summary")
            or experiments.get("evaluation")
            or experiments.get("headline_results")
        )
        if isinstance(summary, dict):
            return _joined_experiment_parts(summary)
        direct_summary = str(summary or "").strip()
        if direct_summary:
            return direct_summary
        return _joined_experiment_parts(experiments)
    return str(data.get("experiment_summary") or "").strip()


def _joined_experiment_parts(experiments: dict[str, object]) -> str:
    parts = []
    labels = {
        "setup": "Setup",
        "metrics_benchmarks": "Metrics/benchmarks",
        "metrics_or_benchmarks": "Metrics/benchmarks",
        "main_findings": "Main findings",
        "cost_robustness_findings": "Cost/robustness findings",
        "cost_or_robustness_findings": "Cost/robustness findings",
        "known_caveats": "Known caveats",
    }
    for key, label in labels.items():
        text = _string_or_joined_list(experiments.get(key))
        if text:
            parts.append(f"{label}: {text}")
    return " ".join(parts)


def _string_or_joined_list(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(_readable_text(item) for item in value if _readable_text(item))
    return str(value or "").strip()


def _plain_language_example(value: object) -> str:
    if isinstance(value, dict):
        text = value.get("text") or value.get("example") or value.get("summary")
        return str(text or "").strip()
    return str(value or "").strip()


def _parse_experiment_evidence(
    data: dict[str, object],
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> list[EvidenceAnchor]:
    experiments = data.get("experiments") or data.get("experiment")
    if isinstance(experiments, dict):
        return _section_evidence(experiments, artifact, fallback_evidence)
    return _parse_evidence(data.get("experiment_evidence", []), artifact, required=False)


def _parse_reader_explanation(value: object) -> ReaderExplanation:
    data = value if isinstance(value, dict) else {}
    return ReaderExplanation(
        opening_context=_optional_explanation(data, "opening_context"),
        core_thesis=_optional_explanation(data, "core_thesis"),
        problem_walkthrough=_optional_explanation(data, "problem_walkthrough"),
        solution_walkthrough=_optional_explanation(data, "solution_walkthrough"),
        experiment_interpretation=_optional_explanation(data, "experiment_interpretation"),
        related_work_context=_optional_explanation(data, "related_work_context"),
        limitations_discussion=_optional_explanation(data, "limitations_discussion"),
        plain_language_story=_optional_explanation(data, "plain_language_story"),
        reader_takeaway=_optional_explanation(data, "reader_takeaway"),
    )


def _optional_explanation(data: dict[object, object], key: str) -> str:
    value = data.get(key)
    if isinstance(value, list):
        return "\n\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _parse_claim_units(value: object, artifact: Artifact) -> list[ClaimUnit]:
    if not isinstance(value, list):
        return []
    units: list[ClaimUnit] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        claim_kind = str(item.get("claim_kind") or item.get("kind") or "").strip()
        text = str(item.get("text") or item.get("claim") or "").strip()
        if not section or not claim_kind or not text:
            continue
        evidence = _parse_evidence(item.get("evidence", []), artifact, required=False)
        publishable_default = item.get("publishable_default", True)
        units.append(
            ClaimUnit(
                section=section,
                claim_kind=claim_kind,
                text=text,
                evidence=evidence,
                publishable_default=_bool_value(publishable_default),
            )
        )
    return units


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


def _optional_string(
    data: dict[str, object],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    fallback: str = "",
) -> str:
    for candidate in (key, *aliases):
        value = data.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _readable_text(item))]


def _readable_text(value: object) -> str:
    if isinstance(value, dict):
        if "name" in value and "reported_profile" in value:
            return f"{value['name']}: {value['reported_profile']}".strip()
        for key in ("text", "name", "summary", "claim"):
            if key in value and str(value[key]).strip():
                return str(value[key]).strip()
        return ""
    return str(value).strip()


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() not in {"false", "0", "no"}
    return bool(value)


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
