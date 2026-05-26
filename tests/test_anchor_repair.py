import json

from research_radar.analysis.anchor_repair import (
    apply_anchor_repair,
    apply_anchor_resolution,
    resolve_claim_anchors,
    resolve_quote,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)


class CapturingRepairProvider:
    name = "repair"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.messages.append(messages)
        return ModelResponse(content=self.content, model=model)


def test_resolve_quote_handles_pdf_extraction_noise() -> None:
    artifact = _artifact(
        "[page 1]\nThe framework decom-\nposes memory mechanisms into four stages."
    )

    resolution = resolve_quote(
        "The framework decomposes memory mechanisms into four stages.",
        artifact,
    )

    assert resolution.status == "matched"
    assert resolution.page == 1
    assert "decom-" in resolution.resolved_quote


def test_resolve_quote_rejects_paraphrase() -> None:
    artifact = _artifact("[page 1]\nThe paper compares memory methods.")

    resolution = resolve_quote("The study evaluates agent memory architectures.", artifact)

    assert resolution.status == "failed"
    assert resolution.resolved_quote is None


def test_apply_anchor_repair_accepts_exact_quote_for_unanchored_claim() -> None:
    artifact = _artifact(
        "[page 12]\n"
        "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"
    )
    claim = Claim(
        text="Experiment: Ours reaches 38.79 overall F1 in Table 7.",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[],
        metadata={"paper_reading": {"status_reason": "missing evidence"}},
    )
    provider = CapturingRepairProvider(
        """
        {
          "repairs": [
            {
              "claim_index": 1,
              "quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79",
              "location": "page 12, Table 7",
              "reason": "Exact table row supports the numeric claim.",
              "source_url": "https://evil.example/not-used"
            }
          ]
        }
        """
    )

    repaired, resolutions, attempts, findings = apply_anchor_repair(
        [claim],
        artifact,
        provider,
        model="fake-repair",
    )

    assert repaired[0].status == ClaimStatus.SUPPORTED
    assert repaired[0].evidence[0].source_url == artifact.source.url
    assert "Ours 38.79" in repaired[0].evidence[0].quote
    assert resolutions[0].status == "failed"
    assert attempts[0].status == "accepted"
    assert attempts[0].claim_text == claim.text
    assert findings[0].metadata["status"] == "accepted"


def test_apply_anchor_repair_rejects_nonexistent_quote() -> None:
    artifact = _artifact("[page 12]\nTable 7 Overall Ours 38.79")
    claim = Claim(
        text="Experiment: Ours reaches 38.79 overall F1 in Table 7.",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[],
        metadata={"paper_reading": {"status_reason": "missing evidence"}},
    )
    provider = CapturingRepairProvider(
        """{"repairs": [
            {"claim_index": 1, "quote": "A paraphrased table result", "location": "page 12"}
        ]}"""
    )

    repaired, _, attempts, findings = apply_anchor_repair(
        [claim],
        artifact,
        provider,
        model="fake-repair",
    )

    assert repaired[0].status == ClaimStatus.UNSUPPORTED
    assert repaired[0].evidence == []
    assert attempts[0].status == "rejected"
    assert any(
        finding.metadata.get("kind") == "anchor_repair"
        and finding.metadata.get("status") == "rejected"
        for finding in findings
    )


def test_apply_anchor_repair_records_missing_provider_result() -> None:
    artifact = _artifact("[page 12]\nTable 7 Overall Ours 38.79")
    claim = Claim(
        text="Experiment: Ours reaches 38.79 overall F1 in Table 7.",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[],
        metadata={"paper_reading": {"status_reason": "missing evidence"}},
    )
    provider = CapturingRepairProvider("""{"repairs": []}""")

    repaired, _, attempts, findings = apply_anchor_repair(
        [claim],
        artifact,
        provider,
        model="fake-repair",
    )

    assert repaired[0].status == ClaimStatus.UNSUPPORTED
    assert attempts[0].status == "rejected"
    assert attempts[0].reason == "no repair returned"
    assert findings[0].metadata["reason"] == "no repair returned"


def test_apply_anchor_repair_skips_broad_claims() -> None:
    artifact = _artifact(
        "[page 7]\n"
        "The default backbone is Qwen2.5-7B and retrieval uses top-k 10."
    )
    claim = Claim(
        text=(
            "Experiment: The default backbone is Qwen2.5-7B and retrieval uses "
            "top-k 10 with greedy decoding."
        ),
        status=ClaimStatus.NEEDS_REVIEW,
        evidence=[
            EvidenceAnchor(
                source_url="https://example.com/paper",
                quote="missing setup quote",
            )
        ],
        metadata={
            "paper_reading": {
                "status_reason": "claim too broad; split setup facets",
            }
        },
    )
    provider = CapturingRepairProvider("""{"repairs": []}""")

    repaired, resolutions, attempts, findings = apply_anchor_repair(
        [claim],
        artifact,
        provider,
        model="fake-repair",
    )

    assert provider.messages == []
    assert repaired[0].status == ClaimStatus.NEEDS_REVIEW
    assert resolutions[0].status == "failed"
    assert attempts[0].status == "skipped"
    assert attempts[0].reason == "claim too broad; split setup facets"
    assert any(finding.metadata.get("status") == "skipped" for finding in findings)


def test_partial_anchor_claim_is_not_publishable_without_repair() -> None:
    artifact = _artifact("[page 6]\nLOCOMO and LONGMEMEVAL are benchmark datasets.")
    claim = Claim(
        text=(
            "Experiment: LOCOMO and LONGMEMEVAL are benchmark datasets, and F1 "
            "and BLEU-1 are reported metrics."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="LOCOMO and LONGMEMEVAL are benchmark datasets.",
            ),
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="F1 and BLEU-1 are reported metrics.",
            ),
        ],
    )

    checked, resolutions, findings = apply_anchor_resolution([claim], artifact)

    assert resolutions[0].status == "partial"
    assert checked[0].status == ClaimStatus.UNSUPPORTED
    assert findings[0].metadata["status"] == "partial"


def test_partial_anchor_claim_can_be_repaired_with_exact_combined_quote() -> None:
    combined_quote = (
        "LOCOMO and LONGMEMEVAL are benchmark datasets. "
        "F1 and BLEU-1 are reported metrics."
    )
    artifact = _artifact(
        "[page 6]\n"
        f"{combined_quote}"
    )
    claim = Claim(
        text=(
            "Experiment: LOCOMO and LONGMEMEVAL are benchmark datasets, and F1 "
            "and BLEU-1 are reported metrics."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="LOCOMO and LONGMEMEVAL are benchmark datasets.",
            ),
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="missing metric quote",
            ),
        ],
    )
    provider = CapturingRepairProvider(
        json.dumps(
            {
                "repairs": [
                    {
                        "claim_index": 1,
                        "quote": combined_quote,
                        "location": "page 6",
                    }
                ]
            }
        )
    )

    repaired, resolutions, attempts, _ = apply_anchor_repair(
        [claim],
        artifact,
        provider,
        model="fake-repair",
    )

    assert resolutions[0].status == "partial"
    assert attempts[0].status == "accepted"
    assert repaired[0].status == ClaimStatus.SUPPORTED


def test_numeric_claim_requires_numeric_anchor() -> None:
    artifact = _artifact("[page 1]\nThe method improves overall performance.")
    claim = Claim(
        text="Experiment: The method reaches 38.79 overall F1.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="The method improves overall performance.",
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "failed"
    assert resolutions[0].reason == "numeric anchor missing claim values"


def test_metric_and_model_names_are_not_treated_as_numeric_values() -> None:
    artifact = _artifact(
        "[page 6]\n"
        "We employ two benchmark datasets, LOCOMO and LONGMEMEVAL.\n"
        "F1 measures token-level overlap. BLEU-1 captures unigram-level precision.\n"
        "[page 11]\n"
        "Qwen2.5-7B, Qwen2.5-72B, LLaMA3.1-8B, and GPT-4o-mini are compared."
    )
    claims = [
        Claim(
            text=(
                "Experiment: The methods were evaluated on LOCOMO and LONGMEMEVAL "
                "using F1 and BLEU-1 metrics."
            ),
            status=ClaimStatus.SUPPORTED,
            evidence=[
                EvidenceAnchor(
                    source_url=artifact.source.url,
                    quote="We employ two benchmark datasets, LOCOMO and LONGMEMEVAL.",
                ),
                EvidenceAnchor(
                    source_url=artifact.source.url,
                    quote=(
                        "F1 measures token-level overlap. BLEU-1 captures unigram-level "
                        "precision."
                    ),
                ),
            ],
        ),
        Claim(
            text=(
                "Experiment: Qwen2.5-7B, Qwen2.5-72B, LLaMA3.1-8B, and GPT-4o-mini "
                "are compared."
            ),
            status=ClaimStatus.SUPPORTED,
            evidence=[
                EvidenceAnchor(
                    source_url=artifact.source.url,
                    quote=(
                        "Qwen2.5-7B, Qwen2.5-72B, LLaMA3.1-8B, and GPT-4o-mini "
                        "are compared."
                    ),
                )
            ],
        ),
    ]

    resolutions = resolve_claim_anchors(claims, artifact)

    assert [resolution.status for resolution in resolutions] == ["matched", "matched"]


def test_anchor_completeness_requires_key_entities() -> None:
    artifact = _artifact(
        "[page 7]\n"
        "Unless otherwise stated, we use Qwen2.5-7B-Instruct as the default LLM backbone."
    )
    claim = Claim(
        text=(
            "Experiment: Default LLM backbone is Qwen2.5-7B-Instruct and the "
            "embedding model is all-MiniLM-L6-v2."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote=(
                    "Unless otherwise stated, we use Qwen2.5-7B-Instruct as "
                    "the default LLM backbone."
                ),
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "failed"
    assert resolutions[0].reason == "anchor missing key entities: all-MiniLM-L6-v2"


def test_anchor_completeness_ignores_lowercase_hyphen_descriptions() -> None:
    artifact = _artifact(
        "[page 6]\n"
        "LOCOMO is grounded in dialogues between two human users, whereas "
        "LONGMEMEVAL is based on user-AI interactions."
    )
    claim = Claim(
        text=(
            "Experiment: LOCOMO is a human-human dialogue benchmark, and "
            "LONGMEMEVAL is based on user-AI interactions."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote=(
                    "LOCOMO is grounded in dialogues between two human users, "
                    "whereas LONGMEMEVAL is based on user-AI interactions."
                ),
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "matched"


def test_anchor_completeness_normalizes_math_italic_letters() -> None:
    artifact = _artifact(
        "[page 7]\n"
        "For all methods that involve top-𝑘 retrieval, we set 𝑘=10."
    )
    claim = Claim(
        text="Experiment: Top-k retrieval k is set to 10.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="For all methods that involve top-𝑘 retrieval, we set 𝑘=10.",
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "matched"


def test_table_window_can_complete_late_numeric_experiment_anchor() -> None:
    artifact = _artifact(
        "[page 12]\n"
        "Table 7: LOCOMO results with Qwen2.5-7B-Instruct.\n"
        "Method Overall F1 Overall BLEU-1\n"
        "A-MEM 25.53 20.11\n"
        "MemOS 37.05 30.30\n"
        "Ours 38.03 31.73\n"
    )
    claim = Claim(
        text=(
            "Experiment: On LOCOMO with Qwen2.5-7B-Instruct, MemOS reaches "
            "37.05 overall F1 and 30.30 overall BLEU-1."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="MemOS 37.05 30.30",
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "matched"
    assert "Table 7: LOCOMO results with Qwen2.5-7B-Instruct." in (
        resolutions[0].resolved_quote or ""
    )
    assert "Method Overall F1 Overall BLEU-1" in (resolutions[0].resolved_quote or "")


def test_table_window_does_not_complete_wrong_benchmark_claim() -> None:
    artifact = _artifact(
        "[page 12]\n"
        "Table 7: LOCOMO results with Qwen2.5-7B-Instruct.\n"
        "Method Overall F1 Overall BLEU-1\n"
        "MemOS 37.05 30.30\n"
    )
    claim = Claim(
        text=(
            "Experiment: On LONGMEMEVAL with Qwen2.5-7B-Instruct, MemOS reaches "
            "37.05 overall F1 and 30.30 overall BLEU-1."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="MemOS 37.05 30.30",
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "failed"
    assert resolutions[0].reason == "anchor missing key entities: LONGMEMEVAL"


def test_table_window_does_not_publish_method_misread() -> None:
    artifact = _artifact(
        "[page 12]\n"
        "Table 7: LOCOMO results with Qwen2.5-7B-Instruct.\n"
        "Method Overall F1 Overall BLEU-1\n"
        "MemTree 36.92 31.05\n"
        "Ours 38.79 32.11\n"
    )
    claim = Claim(
        text=(
            "Experiment: On LOCOMO with Qwen2.5-7B-Instruct, MemTree reaches "
            "38.79 overall F1."
        ),
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=artifact.source.url,
                quote="Ours 38.79 32.11",
            )
        ],
    )

    resolutions = resolve_claim_anchors([claim], artifact)

    assert resolutions[0].status == "failed"
    assert resolutions[0].reason == "table anchor row missing method entity: MemTree"


def test_anchor_repair_does_not_upgrade_claim_linted_broad_claim() -> None:
    quote = (
        "Qwen2.5-7B-Instruct is the default backbone, all-MiniLM-L6-v2 is the "
        "embedding model, top-k retrieval uses k=10, and greedy decoding is used."
    )
    artifact = _artifact(f"[page 7]\n{quote}")
    claim = Claim(
        text=(
            "Experiment: Default backbone is Qwen2.5-7B-Instruct; embedding model "
            "is all-MiniLM-L6-v2; top-k retrieval uses k=10; greedy decoding is used."
        ),
        status=ClaimStatus.NEEDS_REVIEW,
        evidence=[],
        metadata={
            "paper_reading": {
                "status_reason": "claim too broad; split setup facets",
            }
        },
    )
    provider = CapturingRepairProvider(
        json.dumps(
            {
                "repairs": [
                    {
                        "claim_index": 1,
                        "quote": quote,
                        "location": "page 7",
                    }
                ]
            }
        )
    )

    repaired, _, attempts, _ = apply_anchor_repair(
        [claim],
        artifact,
        provider,
        model="fake-repair",
    )

    assert provider.messages == []
    assert attempts[0].status == "skipped"
    assert attempts[0].reason == "claim too broad; split setup facets"
    assert repaired[0].status == ClaimStatus.NEEDS_REVIEW
    assert "anchor_repair" not in repaired[0].metadata


def _artifact(text: str) -> Artifact:
    return Artifact(
        source=SourceCandidate(
            title="Fixture Paper",
            url="https://example.com/paper",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text=text,
    )
