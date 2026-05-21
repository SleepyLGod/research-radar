from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    RelatedWorkAssessment,
)
from research_radar.compose.paper import render_paper_brief
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor


def test_paper_brief_body_only_uses_publishable_claims() -> None:
    anchor = EvidenceAnchor(source_url="https://example.com/paper", quote="Supported method.")
    reading = PaperReading(
        title="Fixture Paper",
        area_context=AreaContext(background="Unverified background text."),
        problem_solution=ProblemSolution(
            problem="Unverified problem text.",
            why_it_matters="Unverified motivation text.",
            hidden_assumptions=["Unverified assumption."],
            solution="Unverified solution text.",
            mechanism="Unsupported mechanism with fewer than 450 tokens.",
            evidence=[anchor],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=["Unverified prior work."],
            novelty="Unverified novelty.",
            repackaging_risk="Unverified risk.",
            evidence=[anchor],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=["Unverified limitation."],
            inferred_weaknesses=["Unverified weakness."],
            evidence=[anchor],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk="Unverified overclaiming risk.",
            weak_evaluations=["Unverified weak evaluation."],
            missing_ablations=["Unverified ablation gap."],
            bottom_line="Unverified critique.",
            evidence=[anchor],
        ),
        essence="Unverified essence.",
        plain_language_example="Unverified example.",
    )
    claims = [
        Claim(
            text="Solution: Supported method.",
            status=ClaimStatus.SUPPORTED,
            evidence=[anchor],
        ),
        Claim(
            text="Experiment: Unsupported token claim.",
            status=ClaimStatus.UNSUPPORTED,
            evidence=[],
        ),
    ]

    brief = render_paper_brief(reading, claims)

    assert "Supported method." in brief
    assert "Unsupported mechanism with fewer than 450 tokens." not in brief
    assert "Unverified background text." not in brief
    assert "Unverified example." not in brief
    assert "Unsupported token claim." not in brief
