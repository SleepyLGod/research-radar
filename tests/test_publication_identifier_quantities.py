"""Model identifiers are conserved as identities, not interleaved experimental quantities."""

import pytest

from research_radar.analysis.localization import _preserve_quantities

SOURCE = ("Table 10 reports pre-correction slot accuracy of 0.62 for LLaMA3-8B, "
          "0.48 for Qwen-7B, 0.59 for Mistral-7B, and 0.61 for GPT-4o-mini.")
CHINESE = ("Table 10 报告纠正前的槽位准确率：LLaMA3-8B 为 0.62，Qwen-7B 为 0.48，"
           "Mistral-7B 为 0.59，GPT-4o-mini 为 0.61。")


def test_saved_model_names_can_precede_their_values_in_chinese() -> None:
    findings = []
    assert _preserve_quantities(SOURCE, CHINESE, findings=findings, field="claims") == CHINESE
    assert not findings


@pytest.mark.parametrize("wrong", [
    CHINESE.replace("LLaMA3-8B", "LLaMA3-70B"),
    CHINESE.replace("GPT-4o-mini", "GPT-4o"),
    CHINESE.replace("0.62", "0.48").replace("为 0.48，Mistral", "为 0.62，Mistral"),
    CHINESE.replace("0.62", "62%"),
    CHINESE.replace("Qwen-7B", "Mistral-7B").replace("Mistral-7B 为 0.59", "Qwen-7B 为 0.59"),
])
def test_model_identity_value_order_and_units_still_cannot_change(wrong: str) -> None:
    findings = []
    assert _preserve_quantities(SOURCE, wrong, findings=findings, field="claims") == SOURCE
    assert findings


def test_parameters_and_measurements_are_not_misclassified_as_model_names() -> None:
    original = "Retrieval uses K=3 and 16 GB; Recall@5 is 0.832."
    wrong = "检索使用 K=5 和 16 GB；Recall@5 为 0.832。"
    findings = []
    assert _preserve_quantities(original, wrong, findings=findings, field="claims") == original
    assert findings


def test_dataset_version_is_an_explicit_source_identity_not_an_outcome_value() -> None:
    original = "JGA is 0.846 on SGD and 0.879 on MultiWOZ 2.2."
    chinese = "SGD 上 JGA 为 0.846，MultiWOZ 2.2 上为 0.879。"
    findings = []
    assert _preserve_quantities(original, chinese, findings=findings, field="claims",
                               source_identifiers=("MultiWOZ 2.2",)) == chinese
    assert not findings
    wrong = chinese.replace("MultiWOZ 2.2", "MultiWOZ 3.0")
    assert _preserve_quantities(original, wrong, findings=findings, field="claims",
                               source_identifiers=("MultiWOZ 2.2",)) == original
    assert findings
