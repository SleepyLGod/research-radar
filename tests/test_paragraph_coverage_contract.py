"""Keep explicit paragraph coverage distinct from factual support."""

import json
from dataclasses import replace

import pytest
from test_publication_composition import Composer, candidates
from test_review_targets import SchemaReviewer

from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import (
    PaperReading,
    ReaderExplanation,
    ReaderExplanationParagraph,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reading_review import paragraph_is_public
from research_radar.analysis.review import (
    ModelReviewResult,
    model_review_publishable_claims,
    review_publication_facts,
)
from research_radar.analysis.review_targets import ReviewContractError
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

METHOD_START = (
    "数据集构建先从 SGD 采样任务目标，用 GPT-4 为每个目标合成三个按时间排序的会话，"
    "每个会话以前一会话的槽位填充状态为条件；流程先生成这些多会话对话，再进入记忆构建。"
)
MEMORY_DETAILS = "对每个已完成会话，GPT-4 生成意图描述和记录槽位特定事实的 QA 对。"
STAGES = ("multi-session dialogue generation; (2) confirmation-type response annotation; "
          "(3) QA-style memory bank construction")
GENERATION = (
    "For every task, we synthesize three temporally ordered sessions using GPT-4, "
    "each conditioned on the slot-filling status of the previous session."
)
MEMORY = (
    "For each completed session, we use GPT-4 to generate an intent description "
    "along with a set of QA pairs, each capturing a slot-specific fact for retrieval."
)


class CoverageReviewer(SchemaReviewer):
    """Return explicit offline decisions, reproducing the saved c22 omission when requested."""

    def __init__(self, status: str, coverage: list[str]) -> None:
        super().__init__()
        self.status = status
        self.coverage = coverage

    def complete_with_schema(
        self, messages: list[Message], *, model: str, response_schema: dict,
    ) -> ModelResponse:
        response = super().complete_with_schema(
            messages, model=model, response_schema=response_schema)
        payload = json.loads(response.content)
        for key, target in self.requests[-1][2].items():
            if target.get("paragraph_id") == "p1.solution_walkthrough.1":
                payload["decisions"][key].update(
                    status=self.status, covered_claim_ids=self.coverage)
        return ModelResponse(json.dumps(payload), model)


def run_review(
    provider: CoverageReviewer, *, complete: bool = False,
) -> tuple[PaperReading, ModelReviewResult]:
    """Exercise the shared final path with unchanged prose or a synthetic full-scope control."""
    reading, _ = candidates()
    url = reading.source_url
    claims = [
        Claim(text, ClaimStatus.SUPPORTED,
              evidence=[EvidenceAnchor(source_url=url, quote=quote) for quote in quotes],
              metadata={"paper_reading": {"claim_id": identity, "section": "solution",
                  **({"source": "reading_context", "context_field": "problem_solution.mechanism"}
                     if identity in {"c3", "c22"} else {})}})
        for identity, text, quotes in (
            ("c3", GENERATION, [GENERATION]),
            ("c22", "The dataset pipeline generates multi-session dialogues before constructing "
             "intent descriptions and QA memory from completed sessions.", [STAGES, MEMORY]),
            ("c5", MEMORY, [MEMORY]),
        )
    ]
    artifact = Artifact(SourceCandidate("MemGuide", url, SourceType.PAPER, "offline"),
                        "\n".join([STAGES, GENERATION, MEMORY]))
    facts = review_publication_facts(claims, Composer({"decisions": [
        {"claim_index": i, "status": "supported", "reason": "Offline fixture approval."}
        for i in range(1, 4)]}), model="offline", readings=[reading], artifacts=[artifact]).claims
    first = METHOD_START if not complete else (
        METHOD_START + "构建时从已完成的会话生成意图描述和 QA 记忆。")
    reading = replace(reading, reader_explanation=ReaderExplanation(solution_walkthrough=[
        ReaderExplanationParagraph(text=first, supporting_claim_ids=["c3", "c22"]),
        ReaderExplanationParagraph(text=MEMORY_DETAILS, supporting_claim_ids=["c5"]),
    ]))
    result = model_review_publishable_claims(
        facts, provider, model="offline", readings=[reading], artifacts=[artifact],
        analysis_claims=facts)
    return reading, result


def test_supported_receipt_missing_required_c22_is_rejected_at_the_target() -> None:
    provider = CoverageReviewer("supported", ["c3"])
    with pytest.raises(ReviewContractError, match="review_incomplete_paragraph_coverage") as error:
        run_review(provider)
    assert error.value.diagnostics["paragraph_id"] == "p1.solution_walkthrough.1"
    assert error.value.diagnostics["missing_claim_ids"] == ["c22"]
    assert "p1.solution_walkthrough.1 missing c22" in str(error.value)
    assert len(provider.requests) == 1


def test_uncertain_c22_still_blocks_full_report_despite_adjacent_details() -> None:
    provider = CoverageReviewer("needs_review", ["c3"])
    with pytest.raises(AnalysisError, match="Final report omitted reviewed context coverage"):
        run_review(provider)
    assert len(provider.requests) == 1


def test_explicit_full_coverage_passes_without_rewriting_prose() -> None:
    provider = CoverageReviewer("supported", ["c3", "c22"])
    reading, result = run_review(provider, complete=True)
    paragraphs = result.readings[0].reader_explanation.solution_walkthrough
    assert [p.text for p in paragraphs] == [
        p.text for p in reading.reader_explanation.solution_walkthrough]
    assert all(paragraph_is_public(p, result.claims, source_url=reading.source_url)
               for p in paragraphs)
    targets = {t["paragraph_id"]: t for t in provider.requests[0][2].values()
               if t["kind"] == "paragraph"}
    assert set(targets["p1.solution_walkthrough.1"]["required_covered_claim_ids"]) == {"c3", "c22"}
    assert "required_covered_claim_ids" not in targets["p1.solution_walkthrough.2"]
@pytest.mark.parametrize("preexisting", [False, True])
def test_cache_rejects_incomplete_coverage_and_only_reuses_valid_reply(
    tmp_path, preexisting: bool,
) -> None:
    provider = CoverageReviewer("supported", ["c3"])
    cache = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="verifier")
    # Keep the request and candidate identical; only the explicit decision changes.
    with pytest.raises(ReviewContractError, match="review_incomplete_paragraph_coverage"):
        run_review(cache, complete=True)
    assert not list(tmp_path.rglob("*.json"))
    assert len(provider.requests) == 1
    if preexisting:
        # The generic schema cache can still contain an older shape-valid reply.
        messages, schema, _ = provider.requests[0]
        cache.complete_with_schema(messages, model="offline", response_schema=schema)
        assert len(list(tmp_path.rglob("*.json"))) == 1
    provider.coverage = ["c3", "c22"]
    run_review(cache, complete=True)
    run_review(cache, complete=True)
    assert len(provider.requests) == (3 if preexisting else 2)
    assert cache.hit_count == 1


def test_cache_can_reuse_valid_abstention_without_publishing(tmp_path) -> None:
    provider = CoverageReviewer("needs_review", ["c3"])
    cache = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="verifier")
    for _ in range(2):
        with pytest.raises(AnalysisError, match="Final report omitted reviewed context coverage"):
            run_review(cache)
    assert len(provider.requests) == 1 and cache.hit_count == 1
