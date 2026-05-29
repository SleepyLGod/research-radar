from research_radar.analysis.localization import (
    localization_body_failed,
    localization_failed,
    localize_report_content,
    report_localization_prompt,
)
from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    ReaderExplanation,
    RelatedWorkAssessment,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, SourceCandidate, SourceType


class CapturingProvider:
    """Provider fixture that records localization messages."""

    name = "capturing-localizer"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.messages.append(messages)
        return ModelResponse(content=self.content, model=model)


class SequenceProvider:
    """Provider fixture that returns localization responses in order."""

    name = "sequence-localizer"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.messages.append(messages)
        if not self.responses:
            raise AssertionError("No more localization responses")
        return ModelResponse(content=self.responses.pop(0), model=model)


def test_localization_prompt_preserves_terms_numbers_and_quotes() -> None:
    prompt = report_localization_prompt(
        readings=[_reading()],
        claims=[_claim()],
        sources=[_source()],
        figures_by_source_url={
            _source().url: [
                {
                    "title": "fig:overview",
                    "caption": "Overview of Raw, Source, and Canonical targets.",
                    "explanation": "This figure aligns with LOCOMO evidence.",
                    "reuse_status": "needs_manual_review",
                }
            ]
        },
    )

    assert "Preserve the original meaning" in prompt
    assert "Keep technical terms" in prompt
    assert "LOCOMO" in prompt
    assert "LongMemEval" in prompt
    assert "Keep claim prefixes exactly" in prompt
    assert "Do not translate evidence quotes" in prompt
    assert "reader_explanation" in prompt
    assert "localized_caption" in prompt
    assert "translate explanation into" in prompt
    assert "Overview of Raw, Source, and Canonical targets." in prompt


def test_localization_changes_display_text_only() -> None:
    source = _source()
    claim = _claim()
    provider = CapturingProvider(
        """
        {
          "readings": [
            {
              "index": 0,
              "area_context": {
                "background": "Agent memory 研究关注长期 recall。",
                "active_questions": ["如何评估 LOCOMO？"],
                "common_baselines": ["BM25"]
              },
              "problem_solution": {
                "problem": "论文评估 LLM agent memory。",
                "why_it_matters": "benchmark 结论会影响系统设计。",
                "hidden_assumptions": ["LOCOMO 足够代表真实任务。"],
                "solution": "它比较 LOCOMO 和 LongMemEval。",
                "mechanism": "它保留 Raw、Source、Canonical 区分。"
              },
              "related_work": {
                "prior_work": ["BM25"],
                "novelty": "它强调 target noninvariance。",
                "repackaging_risk": "风险较低。"
              },
              "experiments": {"summary": "LOCOMO 结果保持 70.4%。"},
              "limitations": {
                "explicit_limitations": ["没有 deployment evaluation。"],
                "inferred_weaknesses": ["样本范围有限。"],
                "future_work": ["扩展到更多 agent。"]
              },
              "critical_assessment": {
                "overclaiming_risk": "低",
                "weak_evaluations": ["样本有限"],
                "missing_ablations": ["没有全部 ablation"],
                "bottom_line": "结论有用但范围有限。"
              },
              "essence": "论文说明 scoring target 会改变 benchmark 结论。",
              "plain_language_example": "同一条记忆用不同 credit target 评分会得到不同结果。",
              "reader_explanation": {
                "opening_context": "这篇论文讨论 LOCOMO 和 LongMemEval 这类 benchmark。",
                "core_thesis": "核心是 scoring target 会影响结论。",
                "problem_walkthrough": "问题在于 Raw、Source、Canonical 会改变评价对象。",
                "solution_walkthrough": "论文把这些 target 分开比较。",
                "experiment_interpretation": "70.4% 这样的数字需要放在对应 target 下理解。",
                "related_work_context": "BM25 是一个保留英文的 baseline。",
                "limitations_discussion": "局限是没有 deployment evaluation。",
                "plain_language_story": "可以把它理解为同一答案用不同 credit target 打分。",
                "reader_takeaway": "读者应该先问 benchmark 到底在奖励什么。"
              }
            }
          ],
          "claims": [
            {"index": 0, "text": "Problem: 论文评估 LLM agent memory。"}
          ],
          "sources": [
            {"url": "https://arxiv.org/abs/2605.00001", "gist": "这是一篇 LOCOMO 相关论文。"}
          ],
          "figures": [
            {
              "source_url": "https://arxiv.org/abs/2605.00001",
              "title": "fig:overview",
              "localized_caption": "Raw、Source、Canonical 三种 target 的概览。",
              "explanation": "这张图说明 Raw、Source、Canonical 的区别。"
            }
          ]
        }
        """
    )
    figures = {
        source.url: [
            {
                "title": "fig:overview",
                "source_url": source.url,
                "caption": "Overview of Raw, Source, and Canonical targets.",
                "explanation": "This figure aligns with verified evidence.",
                "reuse_status": "needs_manual_review",
            }
        ]
    }

    result = localize_report_content(
        readings=[_reading()],
        claims=[claim],
        sources=[source],
        figures_by_source_url=figures,
        provider=provider,
        model="fake-localizer",
        language="zh",
    )

    assert result.readings[0].problem_solution.problem == "论文评估 LLM agent memory。"
    assert result.readings[0].reader_explanation.core_thesis == (
        "核心是 scoring target 会影响结论。"
    )
    assert "LOCOMO" in result.readings[0].reader_explanation.opening_context
    assert "70.4%" in result.readings[0].reader_explanation.experiment_interpretation
    assert result.claims[0].text == "Problem: 论文评估 LLM agent memory。"
    assert result.claims[0].status == claim.status
    assert result.claims[0].evidence == claim.evidence
    assert result.sources[0].url == source.url
    assert result.sources[0].metadata["source_gist"]["text"] == "这是一篇 LOCOMO 相关论文。"
    assert result.figures_by_source_url[source.url][0]["reuse_status"] == "needs_manual_review"
    assert (
        result.figures_by_source_url[source.url][0]["localized_caption"]
        == "Raw、Source、Canonical 三种 target 的概览。"
    )
    assert result.figures_by_source_url[source.url][0]["caption"] == (
        "Overview of Raw, Source, and Canonical targets."
    )
    assert (
        result.figures_by_source_url[source.url][0]["explanation"]
        == "这张图说明 Raw、Source、Canonical 的区别。"
    )
    assert result.status == "succeeded"
    assert result.attempts[0].status == "succeeded"
    assert [attempt.scope for attempt in result.attempts] == ["reading", "display"]
    assert len(provider.messages) == 2


def test_localization_failed_reading_chunk_is_marked_not_silent_fallback() -> None:
    source = _source()
    provider = CapturingProvider("not json")

    result = localize_report_content(
        readings=[_reading()],
        claims=[_claim()],
        sources=[source],
        figures_by_source_url={},
        provider=provider,
        model="fake-localizer",
        language="zh",
    )

    assert result.status == "failed"
    assert localization_body_failed(result) is True
    assert localization_failed(result) is True
    assert result.readings[0].problem_solution.problem == (
        "The paper evaluates LLM agent memory."
    )
    assert result.attempts[0].scope == "reading"
    assert result.attempts[0].status == "failed"
    assert result.attempts[0].response_excerpt == "not json"


def test_localization_failed_display_chunk_is_marked_failed() -> None:
    source = _source()
    provider = SequenceProvider(
        [
            """
            {
              "readings": [
                {
                  "index": 0,
                  "problem_solution": {"problem": "论文评估 LLM agent memory。"}
                }
              ],
              "claims": [],
              "sources": [],
              "figures": []
            }
            """,
            "not json",
        ]
    )

    result = localize_report_content(
        readings=[_reading()],
        claims=[_claim()],
        sources=[source],
        figures_by_source_url={
            source.url: [
                {
                    "title": "fig:overview",
                    "caption": "Overview of Raw, Source, and Canonical targets.",
                }
            ]
        },
        provider=provider,
        model="fake-localizer",
        language="zh",
    )

    assert result.status == "partial_failed"
    assert localization_body_failed(result) is False
    assert localization_failed(result) is True
    assert result.readings[0].problem_solution.problem == "论文评估 LLM agent memory。"
    assert [attempt.scope for attempt in result.attempts] == ["reading", "display"]
    assert result.attempts[1].status == "failed"


def _source() -> SourceCandidate:
    return SourceCandidate(
        title="LOCOMO Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={"source_gist": {"text": "A LOCOMO memory benchmark paper."}},
    )


def _claim() -> Claim:
    return Claim(
        text="Problem: The paper evaluates LLM agent memory on LOCOMO.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://arxiv.org/abs/2605.00001",
                source_title="LOCOMO Memory Paper",
                quote="The paper evaluates LLM agent memory on LOCOMO.",
            )
        ],
    )


def _reading() -> PaperReading:
    return PaperReading(
        title="LOCOMO Memory Paper",
        area_context=AreaContext(
            background="Agent memory research studies long-term recall.",
            active_questions=["How should LOCOMO be evaluated?"],
            common_baselines=["BM25"],
        ),
        problem_solution=ProblemSolution(
            problem="The paper evaluates LLM agent memory.",
            why_it_matters="Benchmark conclusions affect system design.",
            hidden_assumptions=["LOCOMO represents realistic tasks."],
            solution="It compares LOCOMO and LongMemEval.",
            mechanism="It distinguishes Raw, Source, and Canonical targets.",
            evidence=[],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=["BM25"],
            novelty="It highlights target noninvariance.",
            repackaging_risk="Low.",
            evidence=[],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=["No deployment evaluation."],
            inferred_weaknesses=["Limited sample scope."],
            future_work=["Extend to more agents."],
            evidence=[],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk="Low.",
            weak_evaluations=["Limited sample."],
            missing_ablations=["No full ablation."],
            bottom_line="Useful within scope.",
            evidence=[],
        ),
        essence="The paper shows scoring targets can change benchmark conclusions.",
        plain_language_example="Different credit targets can change the score.",
        experiment_summary="LOCOMO results remain 70.4%.",
        reader_explanation=ReaderExplanation(
            opening_context="This paper explains LOCOMO and LongMemEval evaluation.",
            core_thesis="The central point is target noninvariance.",
            problem_walkthrough="Raw, Source, and Canonical targets reward different things.",
            solution_walkthrough="The paper compares those targets explicitly.",
            experiment_interpretation="70.4% only makes sense under its target definition.",
            related_work_context="BM25 is treated as a baseline.",
            limitations_discussion="The analysis does not include deployment evaluation.",
            plain_language_story="The same answer can score differently under different targets.",
            reader_takeaway="Ask what the benchmark is rewarding before trusting the score.",
        ),
    )
