"""Offline production-boundary checks for input, comparison evidence and review."""

import json
from pathlib import Path

import pytest
from reader_fixtures import OfflineStaticProvider as StaticProvider
from test_pipeline_fake import DEEP_READING_FIXTURE_TEXT, FakeConnector

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.paper_reading import paper_reading_prompt
from research_radar.analysis.prompts import verifier_prompt
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import model_review_publishable_claims
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.wechat import render_wechat_html
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)
from research_radar.pipeline import daily, paper
from research_radar.storage.files import read_jsonl


def test_reader_contract_separates_coverage_from_author_limitations() -> None:
    artifact = Artifact(source=SourceCandidate(title="A study", url="https://example.test/paper",
                                              source_type=SourceType.PAPER, source_name="offline"),
                        text="3 Method\nA measured pipeline.")
    prompt = paper_reading_prompt(artifact)

    assert "missing from extracted text is not absent from the PDF" in prompt
    assert "baseline and target rows" in prompt
    assert "do not choose a preferred number" in prompt


def test_literal_table_context_and_contradiction_review_reach_public_gate() -> None:
    url = "https://example.test/paper"
    row = "MethodA 0.80 3.19"
    source = SourceCandidate(title="A study", url=url, source_type=SourceType.PAPER,
                             source_name="offline")
    artifact = Artifact(source=source, text=(
        f"[page 1]\nTable 3: Controlled evaluation.\nMethod JGA DTE\n{row}\n"
        "4 Results\nThe prose instead reports DTE 4.30."
    ))
    claim = Claim(text="MethodA reports DTE of 3.19.", status=ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(source_url=url, quote=row)])
    checked, _, _ = apply_anchor_resolution([claim], artifact)

    class Reviewer:
        name = "offline-contract-reviewer"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            prompt = messages[1].content
            assert "Table binding:" in prompt
            assert "Method JGA DTE" in prompt
            assert "Contradictory supplied evidence requires needs_review" in prompt
            return ModelResponse(model=model, content=json.dumps({"decisions": [{
                "claim_index": 1, "status": "needs_review", "risk": "high",
                "reason": "Offline test decision; no new semantic verification.",
            }]}))

    result = model_review_publishable_claims(checked, Reviewer(), model="offline")
    draft = build_daily_draft("study", [source], result.claims)

    assert result.reviewed_count == 1
    assert not draft.publishable_claims()
    assert claim.text not in render_wechat_html(draft)


def test_table_context_cannot_be_attached_to_a_different_paper_or_quote() -> None:
    claim = Claim(text="A statement.", status=ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(
                      source_url="https://example.test/a", quote="A statement.",
                  )],
                  metadata={"anchor_resolution": {"status": "matched", "evidence_contexts": [{
                      "source_url": "https://example.test/b", "quote": "A statement.",
                      "text": "foreign-paper-marker", "binding": "unresolved column layout",
                  }]}})

    assert "foreign-paper-marker" not in verifier_prompt([claim])


@pytest.mark.parametrize("mode", ["daily", "paper"])
def test_actual_selected_input_is_persisted_even_when_reader_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    monkeypatch.setattr(daily if mode == "daily" else paper, "ingest_source", lambda source, _: (
        Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)
    ))
    reader = StaticProvider("not valid JSON")
    if mode == "daily":
        daily.run_daily(tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
                        deep_limit=1, verifier=StaticProvider('{"decisions": []}'),
                        figure_extractor=lambda *_args, **_kwargs: [])
    else:
        with pytest.raises(AnalysisError):
            paper.run_paper(tmp_path, config, "memory", "https://example.test/paper",
                            reader, model="offline")

    paths = list(tmp_path.rglob("paper_reading_inputs.jsonl"))
    assert len(paths) == 1
    records = read_jsonl(paths[0])
    assert len(records) == 1
    assert records[0]["source_url"]
    assert records[0]["source_text"] == DEEP_READING_FIXTURE_TEXT
    assert records[0]["chunks"]
    assert records[0]["coverage"]
