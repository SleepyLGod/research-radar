"""Translation regressions minimized from the stopped real publication batch."""

import json
from dataclasses import replace

import pytest
from test_localization import CapturingProvider, SequenceProvider, _claim, _paragraph, _reading

from research_radar.analysis.localization import localization_failed, localize_report_content
from research_radar.analysis.paper_reading import ReaderExplanation


@pytest.mark.parametrize(("original", "translated"), [
    ("The timeline spans January 2022 to December 2025.",
     "时间线从2022年1月至2025年12月。"),
    ("Jan 2022–Dec 2025.", "2022 年 1 月至 2025 年 12 月。"),
    ("The value is 0.8435 in Table 3.", "数值在 Table 3 中为 0.8435。"),
    ("The suggestion in Section 4.6 is not validated.", "第4.6节的建议未验证。"),
    ("The value is 0.8435 in Table 3.", "表3的数值为0.8435。"),
    ("Runtime is 41210.8349 s in Table 6.", "运行时间在 Table 6 中为 41210.8349 s。"),
    ("The context contains 203,910.83 tokens.", "上下文包含203,910.83个 token。"),
    ("~16.65 and ~16.86 queries per instance.", "每个实例约16.65和16.86个查询。"),
    ("SEH@K rises from 0.5239 at K=2 to 0.7251 at K=5, with SRS from 0.4651 to 0.5571.",
     "SEH@K 从 K=2 时的0.5239增至 K=5 时的0.7251，SRS 从0.4651增至0.5571。"),
    ("Accuracy is 70% at K=2.", "准确率为 K=2 时的70%。"),
    ("203 tokens at K=2.", "K=2时的203个 token。"),
    ("SRS assigns zero if the gold memory is not retrieved.",
     "若未检索到 gold memory，SRS 赋值为0。"),
    ("The cost is zero tokens.", "开销为0个 token。"),
    ("SRS assigns zero.", "SRS 赋值为零。"),
])
def test_equivalent_real_translation_preserves_values_and_can_continue(
    original: str, translated: str,
) -> None:
    claim = replace(_claim(), text=f"Experiment: {original}")
    result = localize_report_content(
        readings=[], claims=[claim], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"claims": [{"index": 0, "text": translated}]})),
    )

    assert not localization_failed(result)
    assert result.claims[0].text == f"Experiment: {translated}"
    assert result.claims[0].evidence == claim.evidence
    assert result.claims[0].status == claim.status  # Translation is not a new approval.


@pytest.mark.parametrize(("original", "translated"), [
    ("January 2022 to December 2025.", "2022年2月至2025年12月。"),
    ("0.8435 in Table 3.", "Table 4 中为0.8435。"),
    ("0.8435 in Table 3.", "图3中为0.8435。"),
    ("The suggestion in Section 4.6.", "第4.7节的建议。"),
    ("~16.65 and ~16.86 queries.", "16.65和16.86个查询。"),
    ("The context contains 203,910.83 tokens.", "上下文包含203,910.83个字节。"),
    ("0.5239 at K=2 to 0.7251 at K=5.", "从 K=5 时的0.5239到 K=2 时的0.7251。"),
    ("0.5239 at K=2.", "N=2时的0.5239。"),
    ("0.5239 at K=2.", "K=2时的0.5239 s。"),
    ("0.5239 at t=2 ms.", "0.5239 at t=2 s。"),
    ("70% at K=2.", "K=2时的70 ms。"),
    ("70 at K=2.", "K=2时的70个 token。"),
    ("0.5239 at K=2 to 0.7251 at K=5.", "从 K=2 时的0.7251到 K=5 时的0.5239。"),
    ("Latency is 10 ms and storage is 20 MB.", "延迟为20 ms，存储为10 MB。"),
    ("Accuracy is 88% to 99%.", "准确率从99%降至88%。"),
    ("Latency is <10 ms.", "延迟为>10 ms。"),
    ("SRS assigns zero.", "SRS 赋值为1。"),
    ("The cost is non-zero.", "开销为0。"),
])
def test_fact_or_condition_changes_cannot_pass_by_reordering_numbers(
    original: str, translated: str,
) -> None:
    claim = replace(_claim(), text=f"Experiment: {original}")
    result = localize_report_content(
        readings=[], claims=[claim], sources=[], language="zh", model="offline",
        provider=CapturingProvider(json.dumps({"claims": [{"index": 0, "text": translated}]})),
    )

    assert localization_failed(result)
    assert result.claims == [claim]


@pytest.mark.parametrize("failure", ["json", "omitted", "changed_id", "quantity"])
def test_body_failure_stops_before_other_papers_or_display_calls(failure: str) -> None:
    reading = replace(_reading(), reader_explanation=ReaderExplanation(
        solution_walkthrough=[_paragraph("Accuracy is 70%.")],
    ))
    entry = {"text": "准确率为70%。", "supporting_claim_ids": ["c1"]}
    if failure == "changed_id":
        entry["supporting_claim_ids"] = ["c2"]
    elif failure == "quantity":
        entry["text"] = "准确率为99%。"
    reply = json.dumps({"readings": [{"index": 0, "reader_explanation": {
        "solution_walkthrough": [] if failure == "omitted" else [entry],
    }}]})
    if failure == "json":
        reply = "not JSON"
    provider = SequenceProvider([reply, reply, json.dumps({"claims": []})])

    result = localize_report_content(
        readings=[reading, reading], claims=[_claim()], sources=[], language="zh",
        provider=provider, model="offline",
    )

    assert localization_failed(result)
    assert len(result.attempts) == 1
    assert len(provider.messages) == 1
    assert result.readings[1] == reading
    assert result.claims == [_claim()]


def test_valid_body_can_continue_to_display_with_source_bound_ids_unchanged() -> None:
    reading = replace(_reading(), reader_explanation=ReaderExplanation(
        solution_walkthrough=[_paragraph("January 2022 to December 2025.")],
    ))
    provider = SequenceProvider([
        json.dumps({"readings": [{"index": 0, "reader_explanation": {
            "solution_walkthrough": [{"text": "2022年1月至2025年12月。",
                                      "supporting_claim_ids": ["c1"]}],
        }}]}),
        json.dumps({"claims": [{"index": 0, "text": _claim().text}]}),
    ])

    result = localize_report_content(
        readings=[reading], claims=[_claim()], sources=[], language="zh",
        provider=provider, model="offline",
    )

    assert not localization_failed(result)
    assert len(provider.messages) == 2
    paragraph = result.readings[0].reader_explanation.solution_walkthrough[0]
    assert paragraph.supporting_claim_ids == ["c1"]
