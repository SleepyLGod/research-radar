from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    ReaderExplanation,
    RelatedWorkAssessment,
    heuristic_paper_reading,
    model_paper_reading_with_attempts,
    paper_reading_prompt,
    parse_paper_reading,
    reading_to_claims,
    render_deep_reading_report,
    validate_paper_reading,
)
from research_radar.analysis.prompts import (
    research_planner_prompt,
    synthesis_outline_prompt,
    triage_prompt,
    verifier_prompt,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)


class SequenceProvider:
    """Test provider that returns a sequence of model responses."""

    name = "sequence"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return the next response and record the prompt."""

        self.messages.append(messages)
        if not self.responses:
            raise AssertionError("No more fixture responses")
        return ModelResponse(content=self.responses.pop(0), model=model)


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


def test_model_paper_reading_retries_invalid_json_once() -> None:
    provider = SequenceProvider(
        [
            "not json",
            _claim_units_fixture(["Memory benchmark fixture."]),
        ]
    )

    result = model_paper_reading_with_attempts(_artifact(), provider, model="fake-reader")

    assert result.reading.title == "Evidence-Checked Memory Agents"
    assert [attempt.status for attempt in result.attempts] == ["failed", "succeeded"]
    assert "not valid JSON" in (result.attempts[0].error_message or "")
    assert "Repair the previous paper-reading JSON response" in provider.messages[1][-1].content
    assert "exact substring" in provider.messages[1][-1].content


def test_model_paper_reading_retries_missing_required_problem_field_once() -> None:
    provider = SequenceProvider(
        [
            _claim_unit_fixture(
                section="experiment",
                claim_kind="fact",
                text="Memory benchmark fixture.",
            ).replace('"problem": "Memory benchmark fixture.",', ""),
            _claim_units_fixture(["Memory benchmark fixture."]),
        ]
    )

    result = model_paper_reading_with_attempts(_artifact(), provider, model="fake-reader")

    assert result.reading.problem_solution.problem == "Memory benchmark fixture."
    assert result.attempts[0].status == "failed"
    assert "problem" in (result.attempts[0].error_message or "")
    assert result.attempts[1].status == "succeeded"


def test_model_paper_reading_does_not_retry_when_first_attempt_succeeds() -> None:
    provider = SequenceProvider([_claim_units_fixture(["Memory benchmark fixture."])])

    result = model_paper_reading_with_attempts(_artifact(), provider, model="fake-reader")

    assert len(result.attempts) == 1
    assert result.attempts[0].status == "succeeded"
    assert len(provider.messages) == 1


def test_model_paper_reading_reports_attempt_count_after_two_failures() -> None:
    provider = SequenceProvider(["not json", "still not json"])

    try:
        model_paper_reading_with_attempts(_artifact(), provider, model="fake-reader")
    except AnalysisError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected AnalysisError")

    assert "after 2 attempts" in message
    assert "not valid JSON" in message


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
    assert "exact substring copied from the full paper reading packet" in deep
    assert "ResearchRadar research contract" in deep
    assert "claim_units" in deep
    assert "required list of atomic claims" in deep
    assert "representative methods, baselines, datasets, or" in deep
    assert "related_work.prior_work" in deep
    assert "Experiments must separate setup" in deep
    assert "Author-reported superlatives" in deep
    assert "Broad essence statements must not bundle" in deep
    assert "reader_explanation" in deep
    assert "reader-facing explanation layer" in deep
    assert "must not introduce any new facts" in deep
    assert "Public writing style for reader_explanation" in deep
    assert "template summary or marketing copy" in deep
    assert "Preserve numbers, percentages, formulas" in deep
    assert "Accuracy is more important than fluency" in deep
    assert "broader area problem" in deep
    assert "data flow" in deep
    assert "how components interact" in deep
    assert "reported experiments" in deep
    assert "Do not draft the final article here" in deep
    assert "synthesis_outline" in outline
    assert "researcher, builder, evaluator, and skeptic" in outline
    assert "Outline first; do not write the finished article" in outline
    assert "unsupported_or_rejected_claims" in outline

    verifier = verifier_prompt([claim], topic_id="agent-memory", queries=["agent memory benchmark"])

    assert "MONITORED TOPIC: agent-memory" in verifier
    assert "- agent memory benchmark" in verifier
    assert "not supported by evidence" in verifier
    assert "follow_up_actions" in verifier
    assert "do not create new publishable claims" in verifier


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


def test_parse_model_json_allows_prose_around_json_object() -> None:
    artifact = _artifact()
    raw = """
    Here is the structured reading:
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture."
      }
    }
    End.
    """

    reading = parse_paper_reading(raw, artifact)

    assert reading.essence == "Memory benchmark fixture."


def test_area_context_background_can_fall_back_without_publishable_claims() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "active_questions": ["How should retrieval evidence be evaluated?"],
          "common_baselines": ["Answer-only scoring"]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture."
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)

    assert reading.area_context.background == "unknown"


def test_missing_essence_can_fall_back_without_publishable_claims() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "plain_language_example": "Memory benchmark fixture."
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert reading.essence == "unknown"
    assert not any(claim.text == "Essence: unknown" for claim in claims)


def test_parse_reader_explanation_without_creating_claims() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture.",
        "reader_explanation": {
          "opening_context": "This paragraph explains the benchmark setting.",
          "core_thesis": "This paragraph explains the paper's core thesis.",
          "problem_walkthrough": "This paragraph walks through the problem.",
          "solution_walkthrough": "This paragraph walks through the mechanism.",
          "experiment_interpretation": "This paragraph explains how to read results.",
          "related_work_context": "This paragraph compares named prior work.",
          "limitations_discussion": "This paragraph explains caveats.",
          "plain_language_story": "This paragraph gives a simple grounded story.",
          "reader_takeaway": "This paragraph states the reader takeaway."
        },
        "claim_units": [
          {
            "section": "problem",
            "claim_kind": "fact",
            "text": "Memory benchmark fixture.",
            "evidence": [{"quote": "Memory benchmark fixture."}],
            "publishable_default": true
          }
        ]
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)
    claims = reading_to_claims(reading)

    assert reading.reader_explanation.solution_walkthrough.startswith(
        "This paragraph walks through"
    )
    matching_claims = [
        claim for claim in claims if claim.text == "Problem: Memory benchmark fixture."
    ]
    assert len(matching_claims) == 1
    assert not any("reader takeaway" in claim.text.lower() for claim in claims)


def test_legacy_reader_json_uses_empty_reader_explanation() -> None:
    reading = parse_paper_reading(_claim_units_fixture(["Memory benchmark fixture."]), _artifact())

    assert reading.reader_explanation == ReaderExplanation()


def test_claim_units_convert_to_atomic_evidence_backed_claims() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture.",
        "claim_units": [
          {
            "section": "problem",
            "claim_kind": "fact",
            "text": "Memory benchmark fixture.",
            "evidence": [{"quote": "Memory benchmark fixture."}],
            "publishable_default": true
          },
          {
            "section": "critical_assessment",
            "claim_kind": "critique",
            "text": "This unmatched critique should not publish.",
            "evidence": [{"quote": "absent quote"}],
            "publishable_default": true
          },
          {
            "section": "related_work",
            "claim_kind": "novelty",
            "text": "This needs reviewer confirmation.",
            "evidence": [{"quote": "Memory benchmark fixture."}],
            "publishable_default": false
          }
        ]
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)
    claims, findings = validate_paper_reading(reading, artifact)

    assert [claim.text for claim in claims] == [
        "Problem: Memory benchmark fixture.",
        "Critical assessment: This unmatched critique should not publish.",
        "Related work: This needs reviewer confirmation.",
    ]
    assert claims[0].status == ClaimStatus.SUPPORTED
    assert claims[1].status == ClaimStatus.UNSUPPORTED
    assert claims[2].status == ClaimStatus.NEEDS_REVIEW
    assert any(
        finding.metadata.get("kind") == "evidence_anchor_unmatched" for finding in findings
    )


def test_top_level_claim_units_are_preserved_for_model_compatibility() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture."
      },
      "claim_units": [
        {
          "section": "essence",
          "claim_kind": "essence",
          "text": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}],
          "publishable_default": true
        }
      ]
    }
    """

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert len(reading.claim_units) == 1
    assert claims[0].text == "Essence: Memory benchmark fixture."


def test_experiment_detail_fields_are_preserved_in_summary() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": ["Memory benchmark fixture."],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "experiments": {
          "setup": "Memory benchmark fixture.",
          "metrics_benchmarks": ["Memory benchmark fixture."],
          "main_findings": "Memory benchmark fixture.",
          "cost_robustness_findings": "Memory benchmark fixture.",
          "known_caveats": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture."
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)

    assert "Setup: Memory benchmark fixture." in reading.experiment_summary
    assert "Metrics/benchmarks: Memory benchmark fixture." in reading.experiment_summary
    assert "Known caveats: Memory benchmark fixture." in reading.experiment_summary


def test_experiment_summary_object_is_preserved_in_summary() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": ["Memory benchmark fixture."],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "experiments": {
          "summary": {
            "setup": "Memory benchmark fixture.",
            "metrics_or_benchmarks": "Memory benchmark fixture.",
            "cost_or_robustness_findings": "Memory benchmark fixture."
          },
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture."
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)

    assert "{" not in reading.experiment_summary
    assert "Metrics/benchmarks: Memory benchmark fixture." in reading.experiment_summary
    assert "Cost/robustness findings: Memory benchmark fixture." in reading.experiment_summary


def test_model_dict_fields_are_normalized_for_rendering() -> None:
    artifact = _artifact()
    raw = """
    {
      "deep_readings": {
        "area_context": {
          "background": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "problem_solution": {
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "related_work": {
          "prior_work": [
            {
              "name": "MemGPT",
              "reported_profile": "hierarchical vector storage"
            }
          ],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "limitations": {
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "critical_assessment": {
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        },
        "essence": "Memory benchmark fixture.",
        "plain_language_example": {
          "text": "A grounded memory example.",
          "evidence": [{"quote": "Memory benchmark fixture."}]
        }
      }
    }
    """

    reading = parse_paper_reading(raw, artifact)

    assert reading.plain_language_example == "A grounded memory example."
    assert reading.related_work.prior_work == ["MemGPT: hierarchical vector storage"]


def test_unattributed_superlative_claim_needs_review() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="solution",
        claim_kind="fact",
        text="The method achieves the best performance.",
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert (
        claims[0].metadata["paper_reading"]["status_reason"]
        == "author-reported superlative needs attribution"
    )


def test_author_reported_superlative_claim_can_remain_publishable() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="solution",
        claim_kind="fact",
        text="The authors report that the method achieves the best performance.",
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert claims[0].status == ClaimStatus.SUPPORTED


def test_setup_facet_bundle_claim_needs_review() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="experiment",
        claim_kind="fact",
        text=(
            "Default LLM backbone is Qwen2.5-7B-Instruct; embedding model is "
            "all-MiniLM-L6-v2; top-k retrieval uses k=10; greedy decoding is used."
        ),
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert claims[0].metadata["paper_reading"]["status_reason"] == (
        "claim too broad; split setup facets"
    )


def test_split_setup_facets_can_remain_publishable() -> None:
    artifact = _artifact()
    raw = _claim_units_fixture(
        [
            "Default LLM backbone is Qwen2.5-7B-Instruct.",
            "The embedding model is all-MiniLM-L6-v2.",
            "Top-k retrieval uses k=10.",
            "Greedy decoding is used.",
        ]
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert [claim.status for claim in claims] == [ClaimStatus.SUPPORTED] * 4


def test_result_and_cost_bundle_claim_needs_review() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="experiment",
        claim_kind="fact",
        text=(
            "The method achieves the best overall F1 score while consuming fewer "
            "than 450 tokens per dialogue."
        ),
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading, artifact)

    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert claims[0].metadata["paper_reading"]["status_reason"] == (
        "claim too broad; split result and cost"
    )


def test_method_and_result_bundle_claim_needs_review() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="solution",
        claim_kind="fact",
        text=(
            "The method integrates tree-based organization and reports best "
            "performance on both benchmarks."
        ),
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading, artifact)

    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert claims[0].metadata["paper_reading"]["status_reason"] == (
        "claim too broad; split method and result"
    )


def test_same_kind_benchmark_pair_is_not_claim_linted() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="experiment",
        claim_kind="fact",
        text="LOCOMO and LONGMEMEVAL are benchmark datasets.",
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading, artifact)

    assert claims[0].status == ClaimStatus.SUPPORTED


def test_metric_definition_is_not_result_cost_linted() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="experiment",
        claim_kind="fact",
        text=(
            "Evaluation metrics are F1 (token-level overlap) and BLEU-1 "
            "(unigram modified precision with brevity penalty)."
        ),
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading)

    assert claims[0].status == ClaimStatus.SUPPORTED


def test_bundled_essence_claim_needs_review() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="essence",
        claim_kind="essence",
        text=(
            "The paper proposes a framework, compares existing methods, "
            "and introduces a new method."
        ),
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading, artifact)

    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert claims[0].metadata["paper_reading"]["status_reason"] == (
        "essence bundles multiple claims"
    )


def test_external_replication_critique_needs_review() -> None:
    artifact = _artifact()
    raw = _claim_unit_fixture(
        section="critical_assessment",
        claim_kind="critique",
        text="The result lacks independent replication evidence.",
    )

    reading = parse_paper_reading(raw, artifact)
    claims, _ = validate_paper_reading(reading, artifact)

    assert claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert claims[0].metadata["paper_reading"]["status_reason"] == (
        "claim requires external verification"
    )


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


def _claim_unit_fixture(*, section: str, claim_kind: str, text: str) -> str:
    return f"""
    {{
      "deep_readings": {{
        "area_context": {{
          "background": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "problem_solution": {{
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "related_work": {{
          "prior_work": ["Memory benchmark fixture."],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "limitations": {{
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "critical_assessment": {{
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture.",
        "claim_units": [
          {{
            "section": "{section}",
            "claim_kind": "{claim_kind}",
            "text": "{text}",
            "evidence": [{{"quote": "Memory benchmark fixture."}}],
            "publishable_default": true
          }}
        ]
      }}
    }}
    """


def _claim_units_fixture(texts: list[str]) -> str:
    units = ",\n".join(
        f"""
          {{
            "section": "experiment",
            "claim_kind": "fact",
            "text": "{text}",
            "evidence": [{{"quote": "Memory benchmark fixture."}}],
            "publishable_default": true
          }}"""
        for text in texts
    )
    return f"""
    {{
      "deep_readings": {{
        "area_context": {{
          "background": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "problem_solution": {{
          "problem": "Memory benchmark fixture.",
          "why_it_matters": "Memory benchmark fixture.",
          "hidden_assumptions": [],
          "solution": "Memory benchmark fixture.",
          "mechanism": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "related_work": {{
          "prior_work": ["Memory benchmark fixture."],
          "novelty": "Memory benchmark fixture.",
          "repackaging_risk": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "limitations": {{
          "explicit_limitations": ["Memory benchmark fixture."],
          "inferred_weaknesses": [],
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "critical_assessment": {{
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "Memory benchmark fixture.",
          "evidence": [{{"quote": "Memory benchmark fixture."}}]
        }},
        "essence": "Memory benchmark fixture.",
        "plain_language_example": "Memory benchmark fixture.",
        "claim_units": [
{units}
        ]
      }}
    }}
    """
