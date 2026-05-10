"""Researcher-grade paper reading structures and validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from research_radar.evidence.policy import enforce_evidence_policy
from research_radar.models import Artifact, Claim, ClaimStatus, EvidenceAnchor, ReviewFinding


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
    unsupported_or_rejected_claims: list[str] = field(default_factory=list)


def paper_reading_prompt(artifact: Artifact, area_context: str | None = None) -> str:
    """Build the structured paper-reading prompt."""

    context = area_context or "Infer only from supplied sources; mark missing context as unknown."
    return f"""Run the deep-reading stage for this ResearchRadar source.
Act as a skeptical but fair researcher.

Area context:
{context}

Paper:
TITLE: {artifact.source.title}
URL: {artifact.source.url}
TEXT:
{artifact.text[:12000]}

Return structured JSON with these fields:
- deep_readings:
  - area_context: background, active_questions, common_baselines, evidence anchors
  - problem_solution: problem, why_it_matters, hidden_assumptions, solution, mechanism, evidence
  - related_work: prior_work, novelty, repackaging_risk, evidence
  - limitations: explicit_limitations, inferred_weaknesses, evidence
  - critical_assessment: overclaiming_risk, weak_evaluations, missing_ablations,
    bottom_line, evidence
  - plain_language_example: simple example grounded in the source
  - essence: one sentence describing what the source is really doing
- perspective_questions: follow-up questions from researcher, builder, evaluator, and skeptic views
- evidence_index: anchors used for factual, novelty, limitation, and critique claims
- unsupported_or_rejected_claims: claims you considered but rejected

Rules:
- Separate facts from interpretation and speculation.
- Every factual or critical claim needs a page, section, URL, or quote anchor.
- Do not turn author framing into your own conclusion unless evidence supports it.
- Be neutral, sharp, and concrete. Do not flatter the paper.
- Do not draft the final article here; this stage feeds an outline-first synthesis step.
"""


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
        _claim(
            f"Limitations: {'; '.join(reading.limitations.explicit_limitations)}",
            reading.limitations.evidence,
            "Explicit limitations reported or supported by the paper.",
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


def validate_paper_reading(reading: PaperReading) -> tuple[list[Claim], list[ReviewFinding]]:
    """Validate that paper-reading claims are evidence-backed before publication."""

    return enforce_evidence_policy(reading_to_claims(reading))


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
