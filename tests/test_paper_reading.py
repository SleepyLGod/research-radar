from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    RelatedWorkAssessment,
    heuristic_paper_reading,
    paper_reading_prompt,
    parse_paper_reading,
    render_deep_reading_report,
    validate_paper_reading,
)
from research_radar.analysis.prompts import (
    research_planner_prompt,
    synthesis_outline_prompt,
    triage_prompt,
    verifier_prompt,
)
from research_radar.exceptions import AnalysisError
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
Future Work: Future work should test deployed multi-session agents.
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
    assert reading.limitations.future_work == [
        "Future work should test deployed multi-session agents."
    ]
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
    assert "2-4 concrete sentences per field" in deep
    assert "exact substring copied from TEXT" in deep
    assert "Do not draft the final article here" in deep
    assert "synthesis_outline" in outline
    assert "researcher, builder, evaluator, and skeptic" in outline
    assert "Outline first; do not write the finished article" in outline
    assert "unsupported_or_rejected_claims" in outline

    verifier = verifier_prompt([claim], topic_id="agent-memory", queries=["agent memory benchmark"])

    assert "MONITORED TOPIC: agent-memory" in verifier
    assert "- agent memory benchmark" in verifier
    assert "not supported by evidence" in verifier


def test_paper_reading_prompt_can_request_chinese_without_translating_quotes() -> None:
    prompt = paper_reading_prompt(_artifact(), language="zh")

    assert "Simplified Chinese" in prompt
    assert "Only evidence quote fields may remain in the original source language" in prompt


def test_parse_model_json_into_paper_reading() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Agent memory systems combine storage and retrieval.",
          "active_questions": ["How should retrieval evidence be evaluated?"],
          "common_baselines": ["Answer-only scoring"],
          "evidence": [{"quote": "Agent memory systems combine storage and retrieval."}]
        },
        "problem_solution": {
          "problem": "Memory benchmarks can reward unsupported answers.",
          "why_it_matters": "Ungrounded scores hide failures.",
          "hidden_assumptions": ["Retrieved evidence is available."],
          "solution": "Require answers to cite retrieved memory items.",
          "mechanism": "The method checks answer support against retrieved evidence.",
          "evidence": [{"quote": "Require answers to cite retrieved memory items."}]
        },
        "related_work": {
          "prior_work": ["Answer-only memory benchmarks"],
          "novelty": "It shifts evaluation from answer match to grounded answerability.",
          "repackaging_risk": "It is an evaluation lens, not a new memory architecture.",
          "evidence": [{"quote": "shifts evaluation from answer match"}]
        },
        "limitations": {
          "explicit_limitations": ["It does not test long-horizon deployment."],
          "inferred_weaknesses": ["It may depend on benchmark-specific formats."],
          "future_work": ["Future work should test deployed agents."],
          "evidence": [{"quote": "does not test long-horizon deployment"}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Medium",
          "weak_evaluations": ["No deployment eval"],
          "missing_ablations": ["No retrieval-format ablation"],
          "bottom_line": "The contribution is the evaluation lens.",
          "evidence": [{"quote": "evaluation lens"}]
        },
        "plain_language_example": "A correct answer without evidence should not get full credit.",
        "essence": "The paper reframes memory quality as grounded answerability.",
        "unsupported_or_rejected_claims": ["It proves all agents are unreliable."]
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)
    claims, findings = validate_paper_reading(reading)

    assert reading.problem_solution.problem.startswith("Memory benchmarks")
    assert reading.limitations.future_work == ["Future work should test deployed agents."]
    assert reading.essence.startswith("The paper reframes")
    assert any(claim.text.startswith("Problem:") for claim in claims)
    assert any("proves all agents" in (finding.claim_text or "") for finding in findings)


def test_render_deep_reading_report_supports_chinese_labels() -> None:
    anchor = EvidenceAnchor(source_url="https://example.com/paper", quote="Grounded")
    reading = PaperReading(
        title="Memory Paper",
        area_context=AreaContext(background="背景", evidence=[anchor]),
        problem_solution=ProblemSolution(
            problem="问题",
            why_it_matters="动机",
            hidden_assumptions=["假设"],
            solution="方法",
            mechanism="机制",
            evidence=[anchor],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=["已有工作"],
            novelty="新意",
            repackaging_risk="风险",
            evidence=[anchor],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=["局限"],
            inferred_weaknesses=["弱点"],
            evidence=[anchor],
            future_work=["未来工作"],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk="中等",
            weak_evaluations=["薄弱评估"],
            missing_ablations=["缺失消融"],
            bottom_line="底线判断",
            evidence=[anchor],
        ),
        essence="本质",
        plain_language_example="通俗例子",
        experiment_summary="实验",
        experiment_evidence=[anchor],
    )
    claims, _ = validate_paper_reading(reading)

    report = render_deep_reading_report([reading], claims, language="zh")

    assert "# 深度阅读报告" in report
    assert "## Memory Paper" in report
    assert "### 问题与动机" in report
    assert "### 局限与未来工作" in report
    assert "未来工作" in report


def test_parse_model_json_rejects_malformed_response() -> None:
    try:
        parse_paper_reading("not json", _artifact())
    except AnalysisError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")


def test_parse_model_json_rejects_missing_anchors() -> None:
    raw = """
    {
      "deep_readings": {
        "area_context": {"background": "Background"},
        "problem_solution": {
          "problem": "Problem",
          "why_it_matters": "Motivation",
          "solution": "Solution",
          "mechanism": "Mechanism",
          "evidence": []
        },
        "related_work": {"novelty": "Novelty", "repackaging_risk": "Risk", "evidence": []},
        "limitations": {"explicit_limitations": ["Limitation"], "evidence": []},
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "bottom_line": "Bottom line",
          "evidence": []
        },
        "plain_language_example": "Example",
        "essence": "Essence"
      }
    }
    """

    try:
        parse_paper_reading(raw, _artifact())
    except AnalysisError as exc:
        assert "no evidence anchors" in str(exc)
    else:
        raise AssertionError("Expected AnalysisError")


def test_validate_paper_reading_downgrades_unfound_evidence_quote() -> None:
    anchor = EvidenceAnchor(
        source_url="https://example.com/thin",
        quote="This quote is absent from the artifact.",
    )
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
            overclaiming_risk="Low",
            weak_evaluations=[],
            missing_ablations=[],
            bottom_line="Critique",
            evidence=[anchor],
        ),
        essence="Essence",
        plain_language_example="Example",
    )
    artifact = Artifact(
        source=SourceCandidate(
            title="Thin Paper",
            url="https://example.com/thin",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text="The artifact contains different evidence.",
    )

    claims, findings = validate_paper_reading(reading, artifact)

    assert all(claim.status == ClaimStatus.UNSUPPORTED for claim in claims)
    assert any(
        finding.metadata.get("kind") == "evidence_anchor_unmatched" for finding in findings
    )


def test_validate_paper_reading_handles_pdf_extraction_noise() -> None:
    anchor = EvidenceAnchor(
        source_url="https://example.com/paper",
        quote="The framework decomposes memory mechanisms into four stages.",
    )
    reading = PaperReading(
        title="PDF Paper",
        area_context=AreaContext(background="Background", evidence=[anchor]),
        problem_solution=ProblemSolution(
            problem="Problem",
            why_it_matters="Motivation",
            hidden_assumptions=[],
            solution="The framework decomposes memory mechanisms into four stages.",
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
            overclaiming_risk="Low",
            weak_evaluations=[],
            missing_ablations=[],
            bottom_line="Critique",
            evidence=[anchor],
        ),
        essence="Essence",
        plain_language_example="Example",
    )
    artifact = Artifact(
        source=SourceCandidate(
            title="PDF Paper",
            url="https://example.com/paper",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text="The framework decom-\nposes memory mechanisms into four stages.",
    )

    claims, findings = validate_paper_reading(reading, artifact)

    assert all(claim.status == ClaimStatus.SUPPORTED for claim in claims)
    assert not any(
        finding.metadata.get("kind") == "evidence_anchor_unmatched" for finding in findings
    )


def test_empty_limitation_claim_is_not_publishable() -> None:
    anchor = EvidenceAnchor(source_url="https://example.com/paper", quote="Grounded")
    reading = PaperReading(
        title="Paper Without Explicit Limitations",
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
            explicit_limitations=[],
            inferred_weaknesses=["Weakness"],
            evidence=[anchor],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk="Low",
            weak_evaluations=[],
            missing_ablations=[],
            bottom_line="Critique",
            evidence=[anchor],
        ),
        essence="Essence",
        plain_language_example="Example",
    )

    claims, _ = validate_paper_reading(reading)

    assert not any(claim.text == "Limitations: " for claim in claims)


def test_parse_paper_reading_ignores_model_supplied_source_urls() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture.", "source_url": "https://evil.example"}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture.", "source_url": "https://evil.example"}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture.", "source_url": "https://evil.example"}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture.", "source_url": "https://evil.example"}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture.", "source_url": "https://evil.example"}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture."
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)

    assert reading.problem_solution.evidence[0].source_url == artifact.source.url
    assert reading.problem_solution.evidence[0].source_title == artifact.source.title


def _artifact() -> Artifact:
    return Artifact(
        source=SourceCandidate(
            title="Evidence-Checked Memory Agents",
            url="https://example.com/evidence-memory",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text="Memory benchmark fixture.",
    )
