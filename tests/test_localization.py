import json
from dataclasses import replace

import pytest

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
    ReaderExplanationParagraph,
    RelatedWorkAssessment,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.wechat import render_wechat_html
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


@pytest.mark.parametrize(
    ("original", "translated"),
    [
        ("Accuracy is 70.0%.", "准确率为99.9%。"),
        ("Accuracy is 70.0%.", "准确率为70.0。"),
        ("Accuracy is 70.0 percent.", "准确率为70.0。"),
        ("Latency is 100 ms.", "延迟为100 s。"),
        ("Memory is 4 GB.", "内存为4 MB。"),
        ("The change is -5%.", "变化为+5%。"),
        ("Latency is <10 ms.", "延迟为>10 ms。"),
        ("The score is 0.01.", "分数为1。"),
        ("Latency is 10 ms and storage is 20 MB.", "延迟为20 ms，存储为10 MB。"),
        ("Throughput is 10 MB/s.", "吞吐量为10 MB/ms。"),
        ("Speedup is 2×.", "加速为2。"),
    ],
)
def test_localization_rejects_changed_quantities_before_publication(
    original: str, translated: str,
) -> None:
    source = _source()
    claim = replace(_claim(), text=f"Experiment: {original}")
    provider = CapturingProvider(json.dumps({"claims": [{"index": 0, "text": translated}]}))

    result = localize_report_content(
        readings=[], claims=[claim], sources=[source],
        provider=provider, model="offline", language="zh",
    )
    draft = build_daily_draft("offline", result.sources, result.claims, language="zh")

    assert result.claims[0] == claim
    assert draft.claims[0].text == claim.text
    assert translated not in render_wechat_html(draft)
    assert any(finding.metadata.get("kind") == "report_localization_quantity_changed"
               for finding in result.findings)
    assert len(provider.messages) == 1


@pytest.mark.parametrize(
    ("original", "translated"),
    [
        ("Accuracy is 70.0%.", "准确率为70.0%。"),
        ("Accuracy is 70.0 percent.", "准确率为70.0%。"),
        ("Latency is 100 ms.", "延迟为100毫秒。"),
        ("Memory is 4 GB.", "内存为4 GB。"),
        ("The change is -5%.", "变化为−5％。"),
        ("Latency is <10 ms.", "延迟为<10 ms。"),
        ("The score is 1e-3.", "分数为1e-3。"),
        ("BM25 uses 4 GB.", "BM25 使用4 GB。"),
        ("Throughput is 10 MB/s.", "吞吐量为10 MB/秒。"),
    ],
)
def test_localization_accepts_preserved_quantities(original: str, translated: str) -> None:
    claim = replace(_claim(), text=f"Experiment: {original}")
    provider = CapturingProvider(json.dumps({"claims": [{"index": 0, "text": translated}]}))

    result = localize_report_content(
        readings=[], claims=[claim], sources=[],
        provider=provider, model="offline", language="zh",
    )

    assert result.claims[0].text == f"Experiment: {translated}"
    assert result.claims[0].status == claim.status
    assert result.claims[0].evidence == claim.evidence
    assert result.claims[0].metadata == claim.metadata
    assert not result.findings


def test_localization_preserves_original_explanation_and_figure_on_quantity_change() -> None:
    source = _source()
    reading = replace(_reading(), reader_explanation=ReaderExplanation(
        experiment_interpretation=[_paragraph("Accuracy is 70.0% with latency of 100 ms.")],
    ))
    claim = replace(_claim(), text="Experiment: Accuracy is 70.0% with latency of 100 ms.")
    figures = {source.url: [{
        "title": "fig:latency", "caption": "Latency of 100 ms.",
        "explanation": "The measured latency is 100 ms.",
        "relative_path": "figures/latency.png", "renderable": True,
    }]}
    provider = SequenceProvider([
        json.dumps({"readings": [{"index": 0, "reader_explanation": {
            "experiment_interpretation": [{"text": "准确率为99.9%，延迟为100 ms。",
                                           "supporting_claim_ids": ["c1"]}],
        }}]}),
        json.dumps({"claims": [{"index": 0, "text": claim.text}],
                    "figures": [{"source_url": source.url, "title": "fig:latency",
                                 "localized_caption": "延迟为100 s。",
                                 "explanation": "测得延迟为100 s。"}]}),
    ])

    result = localize_report_content(
        readings=[reading], claims=[claim], sources=[source], figures_by_source_url=figures,
        provider=provider, model="offline", language="zh",
    )
    draft = build_daily_draft(
        "offline", result.sources, result.claims, language="zh", readings=result.readings,
        deep_read_sources=[source], figures_by_source_url=result.figures_by_source_url,
    )

    assert result.readings[0].reader_explanation == reading.reader_explanation
    assert result.figures_by_source_url == figures
    assert "99.9" not in render_wechat_html(draft)
    assert len(result.findings) == 1
    assert len(provider.messages) == 1
    assert localization_failed(result)


def test_figure_quantity_guards_remain_active_without_a_failed_body_chunk() -> None:
    source = _source()
    figures = {source.url: [{
        "title": "fig:latency", "caption": "Latency of 100 ms.",
        "explanation": "The measured latency is 100 ms.",
        "relative_path": "figures/latency.png", "renderable": True,
    }]}
    provider = CapturingProvider(json.dumps({"figures": [{
        "source_url": source.url, "title": "fig:latency",
        "localized_caption": "延迟为100 s。", "explanation": "测得延迟为100 s。",
    }]}))

    result = localize_report_content(
        readings=[], claims=[], sources=[], figures_by_source_url=figures,
        provider=provider, model="offline", language="zh",
    )

    assert result.figures_by_source_url == figures
    assert len(result.findings) == 2
    assert len(provider.messages) == 1


def test_localization_quantity_warning_does_not_include_generated_text() -> None:
    source = replace(_source(), metadata={"source_gist": {"text": "Latency is 100 ms."}})
    provider = CapturingProvider(json.dumps({"sources": [{
        "url": source.url, "gist": "private-generated-marker: 延迟为100 s。",
    }]}))

    result = localize_report_content(
        readings=[], claims=[], sources=[source], provider=provider,
        model="offline", language="zh",
    )

    assert result.sources[0].metadata == source.metadata
    assert len(result.findings) == 1
    assert "private-generated-marker" not in repr(result.findings)


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
    assert "Chinese public writing style" in prompt
    assert "natural Simplified Chinese" in prompt
    assert "Do not add claims, URLs, critique, rankings" in prompt
    assert "综上所述" in prompt
    assert "不仅仅是...更是..." in prompt
    assert "Preserve numbers, percentages, formulas" in prompt


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
                "opening_context": [{
                  "text": "这篇论文讨论 LOCOMO 和 LongMemEval 这类 benchmark。",
                  "supporting_claim_ids": ["c1"]
                }],
                "core_thesis": [{
                  "text": "核心是 scoring target 会影响结论。",
                  "supporting_claim_ids": ["c1"]
                }],
                "problem_walkthrough": [{
                  "text": "问题在于 Raw、Source、Canonical 会改变评价对象。",
                  "supporting_claim_ids": ["c1"]
                }],
                "solution_walkthrough": [{
                  "text": "论文把这些 target 分开比较。",
                  "supporting_claim_ids": ["c1"]
                }],
                "experiment_interpretation": [{
                  "text": "70.4% 这样的数字需要放在对应 target 下理解。",
                  "supporting_claim_ids": ["c1"]
                }],
                "related_work_context": [{
                  "text": "BM25 是一个保留英文的 baseline。",
                  "supporting_claim_ids": ["c1"]
                }],
                "limitations_discussion": [{
                  "text": "局限是没有 deployment evaluation。",
                  "supporting_claim_ids": ["c1"]
                }],
                "plain_language_story": [{
                  "text": "可以把它理解为同一答案用不同 credit target 打分。",
                  "supporting_claim_ids": ["c1"]
                }],
                "reader_takeaway": [{
                  "text": "读者应该先问 benchmark 到底在奖励什么。",
                  "supporting_claim_ids": ["c1"]
                }]
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
    assert result.readings[0].reader_explanation.core_thesis[0].text == (
        "核心是 scoring target 会影响结论。"
    )
    assert "LOCOMO" in result.readings[0].reader_explanation.opening_context[0].text
    assert "70.4%" in result.readings[0].reader_explanation.experiment_interpretation[0].text
    assert result.readings[0].reader_explanation.core_thesis[0].supporting_claim_ids == ["c1"]
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
    assert result.readings[0].problem_solution.problem == ("The paper evaluates LLM agent memory.")
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
                  "problem_solution": {"problem": "论文评估 LLM agent memory。"},
                  "reader_explanation": {
                    "opening_context": [{"text": "论文解释 LOCOMO 与 LongMemEval 的评估。",
                      "supporting_claim_ids": ["c1"]}],
                    "core_thesis": [{"text": "核心问题是评估目标不一致。",
                      "supporting_claim_ids": ["c1"]}],
                    "problem_walkthrough": [{"text": "Raw、Source 和 Canonical 目标奖励不同内容。",
                      "supporting_claim_ids": ["c1"]}],
                    "solution_walkthrough": [{"text": "论文明确比较这些目标。",
                      "supporting_claim_ids": ["c1"]}],
                    "experiment_interpretation": [{"text": "70.4% 必须结合目标定义理解。",
                      "supporting_claim_ids": ["c1"]}],
                    "related_work_context": [{"text": "BM25 作为 baseline。",
                      "supporting_claim_ids": ["c1"]}],
                    "limitations_discussion": [{"text": "分析没有部署评估。",
                      "supporting_claim_ids": ["c1"]}],
                    "plain_language_story": [{"text": "同一回答在不同目标下得分不同。",
                      "supporting_claim_ids": ["c1"]}],
                    "reader_takeaway": [{"text": "先看 benchmark 奖励什么，再看分数。",
                      "supporting_claim_ids": ["c1"]}]
                  }
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


def test_localization_drops_explanation_paragraph_when_claim_ids_change() -> None:
    provider = CapturingProvider(
        """
        {
          "readings": [{
            "index": 0,
            "reader_explanation": {
              "opening_context": [{
                "text": "背景译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "core_thesis": [{
                "text": "本段篡改了 claim id。",
                "supporting_claim_ids": ["different-id"]
              }],
              "problem_walkthrough": [{
                "text": "问题译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "solution_walkthrough": [{
                "text": "方法译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "experiment_interpretation": [{
                "text": "实验译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "related_work_context": [{
                "text": "相关工作译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "limitations_discussion": [{
                "text": "局限译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "plain_language_story": [{
                "text": "通俗解释译文。",
                "supporting_claim_ids": ["c1"]
              }],
              "reader_takeaway": [{
                "text": "读者结论译文。",
                "supporting_claim_ids": ["c1"]
              }]
            }
          }],
          "claims": [],
          "sources": [],
          "figures": []
        }
        """
    )

    result = localize_report_content(
        readings=[_reading()],
        claims=[],
        sources=[],
        provider=provider,
        model="fake-localizer",
        language="zh",
    )

    assert result.readings[0].reader_explanation.core_thesis == []
    assert result.readings[0].reader_explanation.opening_context[0].text == "背景译文。"
    finding = next(
        finding
        for finding in result.findings
        if finding.metadata.get("kind") == "report_localization_claim_ids_changed"
    )
    assert finding.metadata["dropped_paragraph_count"] == 1


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
        metadata={"paper_reading": {"claim_id": "c1"}},
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
            opening_context=[_paragraph("This paper explains LOCOMO and LongMemEval evaluation.")],
            core_thesis=[_paragraph("The central point is target noninvariance.")],
            problem_walkthrough=[
                _paragraph("Raw, Source, and Canonical targets reward different things.")
            ],
            solution_walkthrough=[_paragraph("The paper compares those targets explicitly.")],
            experiment_interpretation=[
                _paragraph("70.4% only makes sense under its target definition.")
            ],
            related_work_context=[_paragraph("BM25 is treated as a baseline.")],
            limitations_discussion=[
                _paragraph("The analysis does not include deployment evaluation.")
            ],
            plain_language_story=[
                _paragraph("The same answer can score differently under different targets.")
            ],
            reader_takeaway=[
                _paragraph("Ask what the benchmark is rewarding before trusting the score.")
            ],
        ),
    )


def _paragraph(text: str) -> ReaderExplanationParagraph:
    return ReaderExplanationParagraph(text=text, supporting_claim_ids=["c1"])


@pytest.mark.parametrize(("original", "translated"), [
    ("Storage is 10 PB.", "存储为10 EB。"),
    ("The corpus has 10 million items.", "语料有10 billion个条目。"),
    ("The change is - 5%.", "变化为+ 5%。"),
    ("Latency is 10 MB/epoch.", "延迟为10 MB/step。"),
    ("Storage is 10 XU.", "存储为10 YU。"),
    ("The top-3 retrieved items.", "检索到的前4个条目。"),
    ("The score is -3.", "分数为+3。"),
])
def test_translation_cannot_change_unrecognized_scale_sign_or_unit(
    original: str, translated: str,
) -> None:
    claim = replace(_claim(), text=f"Experiment: {original}")
    result = localize_report_content(
        readings=[], claims=[claim], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"claims": [{"index": 0, "text": translated}]})),
    )

    assert result.claims[0] == claim
    assert any(f.metadata.get("kind") == "report_localization_quantity_changed"
               for f in result.findings)


@pytest.mark.parametrize(("original", "translated"), [
    ("The top-3 retrieved memory items.", "检索到的前3个记忆项。"),
    ("The change is - 5%.", "变化为−5%。"),
    ("The corpus has 10 million items.", "语料有10百万个条目。"),
    ("Storage is 10 PB.", "存储为10 PB。"),
    ("Throughput is 10 MB/epoch.", "吞吐量为10 MB/epoch。"),
    ("Latency ranges from 10 - 20 ms.", "延迟范围为10到20 ms。"),
])
def test_translation_preserves_lexical_top_k_and_spaced_signs(
    original: str, translated: str,
) -> None:
    claim = replace(_claim(), text=f"Experiment: {original}")
    result = localize_report_content(
        readings=[], claims=[claim], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"claims": [{"index": 0, "text": translated}]})),
    )

    assert result.claims[0].text == f"Experiment: {translated}"
    assert not result.findings


@pytest.mark.parametrize("entries", [
    None, [], [{"index": True}], [{"index": False}], [{"index": -1}],
    [{"index": 1}], [{"index": "0"}], [{"index": 0}, {"index": 0}],
    [{"index": 0}, "not an entry"],
])
def test_invalid_translation_indices_fail_chunk_without_replacing_reading(entries: object) -> None:
    original = _reading()
    result = localize_report_content(
        readings=[original], claims=[], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"readings": entries})),
    )

    assert result.status == "failed"
    assert localization_body_failed(result)
    assert result.readings == [original]
    assert len(result.attempts) == 1
    assert result.findings[0].metadata["kind"] == "report_localization_failed"


@pytest.mark.parametrize("entries", [
    [], [{"index": False, "text": "changed"}],
    [{"index": 0, "text": "first"}, {"index": 0, "text": "last"}],
    [{"index": 1, "text": "wrong slot"}],
])
def test_invalid_claim_translation_indices_preserve_verified_originals(entries: object) -> None:
    claim = _claim()
    result = localize_report_content(
        readings=[], claims=[claim], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"claims": entries})),
    )

    assert result.status == "failed"
    assert result.claims == [claim]
    assert len(result.attempts) == 1


@pytest.mark.parametrize("field", [
    "area_context.background", "area_context.active_questions",
    "problem_solution.problem", "problem_solution.hidden_assumptions",
    "problem_solution.mechanism", "related_work.prior_work",
    "limitations.explicit_limitations", "critical_assessment.bottom_line",
    "experiment_summary", "essence", "plain_language_example",
])
def test_structured_translation_checks_quantities_in_each_text_field(field: str) -> None:
    original = _reading()
    section, _, name = field.partition(".")
    if name:
        value = getattr(getattr(original, section), name)
        text: str | list[str] = (
            ["Latency is 10 ms."] if isinstance(value, list) else "Latency is 10 ms."
        )
        original = replace(original, **{
            section: replace(getattr(original, section), **{name: text}),
        })
        replacement: str | list[str] = (
            ["延迟为999 s。"] if isinstance(text, list) else "延迟为999 s。"
        )
        entry = {"index": 0, section: {name: replacement}}
    else:
        original = replace(original, **{section: "Latency is 10 ms."})
        entry = (
            {"index": 0, "experiments": {"summary": "延迟为999 s。"}}
            if section == "experiment_summary" else {"index": 0, section: "延迟为999 s。"}
        )
    result = localize_report_content(
        readings=[original], claims=[], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"readings": [entry]})),
    )

    localized = result.readings[0]
    actual = getattr(getattr(localized, section), name) if name else getattr(localized, section)
    assert actual == (
        getattr(getattr(original, section), name) if name else getattr(original, section)
    )
    assert any(f.metadata.get("kind") == "report_localization_quantity_changed"
               for f in result.findings)


def test_omitted_explanation_translation_retains_original_for_audit() -> None:
    original = _reading()
    result = localize_report_content(
        readings=[original], claims=[], sources=[], language="zh", model="offline",
        provider=CapturingProvider('{"readings": [{"index": 0, "essence": "核心。"}]}'),
    )

    assert result.readings[0].reader_explanation == original.reader_explanation
    finding = next(f for f in result.findings
                   if f.metadata.get("kind") == "report_localization_missing_paragraphs")
    assert finding.metadata["retained_original_paragraph_count"] == 9
    assert not any(f.metadata.get("kind") == "report_localization_claim_ids_changed"
                   for f in result.findings)


@pytest.mark.parametrize("key", ["readings", "claims"])
def test_invalid_unused_indices_are_handled_as_localization_failure(key: str) -> None:
    source = _source()
    result = localize_report_content(
        readings=[], claims=[], sources=[source], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({key: [{"index": False}]})),
    )

    assert result.status == "failed"
    assert result.sources == [source]
    assert len(result.attempts) == 1


def test_changed_structured_list_retains_original_instead_of_pairing_different_items() -> None:
    original = replace(_reading(), area_context=AreaContext(
        background="An evaluation.", active_questions=["Cost is 10 ms.", "Storage is 20 MB."],
    ))
    result = localize_report_content(
        readings=[original], claims=[], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"readings": [{"index": 0, "area_context": {
            "active_questions": ["成本为10 ms，存储为20 MB。"],
        }}]})),
    )

    assert result.readings[0].area_context.active_questions == (
        original.area_context.active_questions
    )
    assert any(
        f.metadata.get("kind") == "report_localization_list_changed" for f in result.findings
    )
