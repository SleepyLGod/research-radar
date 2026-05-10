from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    RelatedWorkAssessment,
    heuristic_paper_reading,
    paper_reading_prompt,
    validate_paper_reading,
)
from research_radar.analysis.prompts import (
    research_planner_prompt,
    synthesis_outline_prompt,
    triage_prompt,
    verifier_prompt,
)
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)


def test_heuristic_paper_reading_extracts_researcher_rubric() -> None:
    artifact = Artifact(
        source=SourceCandidate(
            title="Memory Systems Paper",
            url="https://example.com/paper",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text="""Background: Agent memory systems combine retrieval, storage, and reflection.
Question: How should memory systems prove retrieved evidence supports answers?
Baseline: Answer-only benchmark scoring.
Problem: Existing systems report success without checking retrieved evidence support.
Motivation: This matters because benchmark scores can hide ungrounded guessing.
Solution: The paper adds grounded evidence checks before scoring answers.
Mechanism: It requires each answer to cite retrieved memory items.
Related Work: Prior memory benchmarks mostly measure answer match.
Novelty: The paper shifts evaluation from answer-only scoring to evidence-grounded scoring.
Limitation: It does not test long-horizon deployment.
Weakness: The setup may still depend on benchmark-specific retrieval formats.
Critical Bottom Line: The useful contribution is the evaluation lens, not a new memory architecture.
Essence: It reframes memory quality as grounded answerability.
Example: A correct answer without retrieved evidence should not receive full credit.
Unsupported Claim: The paper proves all memory agents are unreliable.""",
    )

    reading = heuristic_paper_reading(artifact)
    claims, findings = validate_paper_reading(reading)

    assert reading.problem_solution.problem.startswith("Existing systems")
    assert reading.area_context.active_questions == [
        "How should memory systems prove retrieved evidence supports answers?"
    ]
    assert reading.area_context.common_baselines == ["Answer-only benchmark scoring."]
    assert reading.problem_solution.solution.startswith("The paper adds")
    assert "evidence-grounded" in reading.related_work.novelty
    assert reading.limitations.explicit_limitations == ["It does not test long-horizon deployment."]
    assert "evaluation lens" in reading.critical_assessment.bottom_line
    assert any(claim.status == ClaimStatus.UNSUPPORTED for claim in claims)
    assert any("proves all memory agents" in (finding.claim_text or "") for finding in findings)


def test_unsupported_critical_claim_without_anchor_is_rejected() -> None:
    anchor = EvidenceAnchor(source_url="https://example.com/thin", quote="Grounded")
    reading = PaperReading(
        title="Thin Paper",
        area_context=AreaContext(background="Background", evidence=[anchor]),
        problem_solution=ProblemSolution(
            problem="Problem",
            why_it_matters="Motivation",
            hidden_assumptions=[],
            solution="Solution",
            mechanism="Mechanism",
            evidence=[anchor],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=["Prior"],
            novelty="Novelty",
            repackaging_risk="Risk",
            evidence=[anchor],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=["Limitation"],
            inferred_weaknesses=[],
            evidence=[anchor],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk="High",
            weak_evaluations=[],
            missing_ablations=[],
            bottom_line="Unsupported critique",
            evidence=[],
        ),
        essence="Essence",
        plain_language_example="Example",
    )
    claims, findings = validate_paper_reading(reading)

    unsupported = [
        claim
        for claim in claims
        if claim.text == "Critical assessment: Unsupported critique"
        and claim.status == ClaimStatus.UNSUPPORTED
    ]

    assert unsupported
    assert any("Critical assessment" in (finding.claim_text or "") for finding in findings)


def test_research_workflow_prompts_cover_planner_wide_deep_and_outline() -> None:
    source = SourceCandidate(
        title="Evidence-Checked Memory Agents",
        url="https://example.com/evidence-memory",
        source_type=SourceType.PAPER,
        source_name="fixture",
        summary="A paper about evidence checks for memory agents.",
    )
    artifact = Artifact(
        source=source,
        text="Problem: Memory benchmarks can reward unsupported answers.",
    )
    claim = Claim(
        text="The paper reframes memory evaluation around grounded answerability.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="It requires answers to cite retrieved memory items.",
                location="Method",
            )
        ],
    )

    planner = research_planner_prompt("agent-memory", ["agent memory benchmark"])
    wide = triage_prompt([artifact])
    deep = paper_reading_prompt(artifact)
    outline = synthesis_outline_prompt("agent-memory", [claim])

    assert "research_plan" in planner
    assert "neutral research scope" in planner
    assert "source_priorities" in planner
    assert "overclaiming risks" in planner
    assert "wide-scan stage" in wide
    assert "ranked_sources" in wide
    assert "deep_reading_candidates" in wide
    assert "deep-reading stage" in deep
    assert "perspective_questions" in deep
    assert "Do not draft the final article here" in deep
    assert "synthesis_outline" in outline
    assert "researcher, builder, evaluator, and skeptic" in outline
    assert "Outline first; do not write the finished article" in outline
    assert "unsupported_or_rejected_claims" in outline

    verifier = verifier_prompt([claim], topic_id="agent-memory", queries=["agent memory benchmark"])

    assert "MONITORED TOPIC: agent-memory" in verifier
    assert "- agent memory benchmark" in verifier
    assert "not supported by evidence" in verifier
