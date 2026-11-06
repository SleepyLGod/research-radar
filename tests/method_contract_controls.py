"""Editorial source-grounded controls, not repaired or newly generated model answers."""

import copy
from dataclasses import replace

from test_method_flow import fixture


def control(name: str):
    """Declare roles, relation endpoints and Chinese expectations explicitly for two papers."""
    artifact, response, data = fixture(name)
    body = response["deep_readings"]
    body["method_flow"] = {
        "operations": copy.deepcopy(data["operation_records"]),
        "links": [],
        "gaps": [],
    }
    relations = {
        "memconflict": {
            "r1": ("m1", "m2"),
            "r2": ("m2", "m3"),
            "r3": ("m3", "m4"),
            "r4": ("m4", "m5"),
        },
        "memguide": {"r1": ("m2", "m3"), "r2": ("m3", "m4")},
    }[name]
    operation_ids = {op["operation_claim_id"] for op in data["operation_records"]}
    for unit in body["claim_units"]:
        identity = unit["claim_id"]
        unit["method"] = None
        if identity in operation_ids:
            unit["method"] = {"kind": "operation", "from_claim_id": None, "to_claim_id": None}
        if identity in relations:
            start, end = relations[identity]
            unit["method"] = {"kind": "precedes", "from_claim_id": start, "to_claim_id": end}
            body["method_flow"]["links"].append(
                {"from_claim_id": start, "to_claim_id": end, "relation_claim_id": identity}
            )
    # r5 states shared query identity, not a separate chronology fact; no r5 edge is invented.
    if name == "memconflict":
        unit = next(unit for unit in body["claim_units"] if unit["claim_id"] == "m5")
        unit["text"] = (
            "The framework issues a query after the corresponding evaluable session "
            "has been ingested and uses only the available history prefix."
        )
        extra = [
            (
                "e1",
                "experiment",
                "The main white-box evaluation uses K=3.",
                "The main white-box evaluation uses 𝐾= 3.",
                "Experiment: 主要白盒评估使用 K=3。",
            ),
            (
                "e2",
                "experiment",
                "Overall averages are macro-averages over conflict types.",
                "we report metrics separately by conflict type and compute overall averages "
                "as macro-averages over\nconflict types",
                "Experiment: 总体平均按冲突类型取宏平均。",
            ),
            (
                "e3",
                "experiment",
                "The authors report that no system dominates all metrics and conflict types.",
                "No system dominates\nall metrics and conflict types.",
                "Experiment: 作者报告，没有系统在所有指标与冲突类型上占优。",
            ),
            (
                "l1",
                "limitations",
                "The benchmark is constructed through controlled simulation rather than "
                "naturally occurring long-term human interactions.",
                "it is still constructed through controlled simulation\nrather than collected "
                "from naturally occurring long-term human interactions.",
                "Limitations: 基准通过受控模拟构建，而非采集自然发生的长期人类交互。",
            ),
        ]
        experiment = [
            {
                "text": ("这些是两种不同的评测视角：黑盒检查答案，白盒检查检索和排序。"
                         "白盒默认取 top-3 条记忆；总体分数按冲突类型做宏平均，"
                         "而不是让数量更多的一类主导总分。"
                         "作者报告，没有系统在所有指标和冲突类型上占优。"),
                "supporting_claim_ids": ["m6", "e1", "e2", "e3"],
            }
        ]
        limitations = [
            {
                "text": "这些结论来自受控模拟的交互，不能当作自然发生的长期人类交互实验。",
                "supporting_claim_ids": ["l1"],
            }
        ]
    else:
        unit = next(unit for unit in body["claim_units"] if unit["claim_id"] == "m4")
        unit["text"] = (
            "Response Generation produces a response using dialogue context, core "
            "memory facts and missing slots, omitting auxiliary questions."
        )
        extra = [
            (
                "e1",
                "experiment",
                "The evaluation uses MS-TOD sessions annotated with confirmation-type responses.",
                "we evaluate MemGuide on ses-\nsions from the MS-TOD benchmark that are "
                "annotated with\nconfirmation-type responses",
                "Experiment: 评估使用带有确认型回复标注的 MS-TOD 会话。",
            ),
            (
                "e2",
                "experiment",
                "With Mistral-7B as the reader, the authors report JGA increasing from 0.73 "
                "to 0.80 and DTE decreasing from 2.52 to 1.21.",
                "when using Mistral-7B as the\nLLM Reader, MemGuide increases JGA from "
                "0.73 to 0.80\nand reduces DTE from 2.52 to 1.21",
                "Experiment: 在 Mistral-7B reader 设置下，作者报告 JGA 从 0.73 升至 0.80，"
                "DTE 从 2.52 降至 1.21。",
            ),
            (
                "l1",
                "limitations",
                "The single-session MemGuide variant disables missing slot guided filtering "
                "while retaining QA memory.",
                "MemGuide∗ is a single-session variant of\nMemGuide, where the missing slot "
                "guided filtering is dis-\nabled while retaining the QA memory.",
                "Limitations: 单会话 MemGuide 变体关闭缺失槽位引导筛选，但保留 QA 记忆。",
            ),
        ]
        experiment = [
            {
                "text": ("实验使用 MS-TOD 中带有确认型回复标注的会话。"
                         "在 Mistral-7B reader 这一设置下，作者报告 JGA 从 0.73 升至 0.80，"
                         "DTE 从 2.52 降至 1.21；这组数值对应该模型与任务设置，"
                         "不是所有模型的统一结果。"),
                "supporting_claim_ids": ["e1", "e2"],
            }
        ]
        limitations = [
            {
                "text": ("单会话实验还使用一个关闭缺失槽位引导筛选、保留 QA 记忆的变体。"
                         "它不是完整多会话流程，阅读单会话结果时需要保留这个区别。"),
                "supporting_claim_ids": ["l1"],
            }
        ]
    for identity, section, text, quote, translated in extra:
        body["claim_units"].append(
            {
                "claim_id": identity,
                "section": section,
                "claim_kind": "fact",
                "text": text,
                "evidence": [{"quote": quote}],
                "publishable_default": True,
                "method": None,
            }
        )
        data["writer_control"]["claims"].append({"claim_id": identity, "text": translated})
    body["reader_explanation"] = {}
    data["writer_control"]["reader_explanation"].update(
        experiment_interpretation=experiment, limitations_discussion=limitations
    )
    artifact = replace(artifact, text=artifact.text + "\n\n" + "\n\n".join(row[3] for row in extra))
    return artifact, response, data["writer_control"]
