"""Keep malformed live quotes rejected while separating a generation adjective from a name."""

import json
from pathlib import Path

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_resolution, resolve_quote
from research_radar.evidence.quotes import find_quote
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

DATA = json.loads(
    (Path(__file__).parent / 'fixtures/method_flow/memconflict_quote_audit.json').read_text()
)


def artifact() -> Artifact:
    return Artifact(SourceCandidate('MemConflict', DATA['source_url'], SourceType.PAPER, 'offline'),
                    '\n\n'.join(DATA['source_excerpts']))


@pytest.mark.parametrize('index', [0, 1, 2])
def test_unchanged_reader_quotes_do_not_acquire_a_literal_match(index: int) -> None:
    reading = DATA['reader_claims'][index]
    quote = reading['evidence'][0]['quote']
    assert find_quote(quote, artifact().text) is None
    assert resolve_quote(quote, artifact()).status == 'failed'


@pytest.mark.parametrize('index', [2, 3])
def test_original_multiline_formulas_match_without_reconstructing_math(index: int) -> None:
    quote = DATA['source_excerpts'][index]
    matched = find_quote(quote, artifact().text)
    assert matched is not None
    assert artifact().text[matched.start:matched.end] == quote


def test_continuous_quote_control_is_not_blocked_by_a_generation_adjective() -> None:
    original = DATA['reader_claims'][0]
    evidence = [EvidenceAnchor(source_url=DATA['source_url'], quote=quote)
                for quote in DATA['literal_c9_control']]
    candidate = Claim('Solution: '+original['text'], ClaimStatus.SUPPORTED, evidence=evidence)
    checked, resolved, _ = apply_anchor_resolution([candidate], artifact())
    assert resolved[0].status == 'matched'
    assert checked[0].is_publishable()  # Local eligibility only; no factual/model approval.
    assert checked[0].text == candidate.text
    assert checked[0].evidence == candidate.evidence
    assert 'model_review' not in checked[0].metadata


def test_invalid_joined_quote_remains_a_failure_after_the_entity_fix() -> None:
    original = DATA['reader_claims'][0]
    candidate = Claim('Solution: '+original['text'], ClaimStatus.SUPPORTED, evidence=[
        EvidenceAnchor(source_url=DATA['source_url'], quote=e['quote'])
        for e in original['evidence']])
    checked, resolved, _ = apply_anchor_resolution([candidate], artifact())
    assert resolved[0].status == 'partial'
    assert not checked[0].is_publishable()
    assert checked[0].evidence == candidate.evidence
