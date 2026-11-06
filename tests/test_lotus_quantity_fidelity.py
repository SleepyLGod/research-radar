"""Exact scale notation and explicitly repeated cutoffs do not authorize new facts."""

import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from test_publication_composition import Composer, candidates
from test_review_targets import SchemaReviewer

from research_radar.analysis.anchor_repair import AnchorResolution, _numeric_anchor_failure
from research_radar.analysis.localization import (
    _preserve_quantities,
    localization_failed,
    localize_report_content,
)
from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)
from research_radar.security.secrets import KeychainSecretBackend

SAVED = json.loads((Path(__file__).parent / "fixtures/lotus_quantity_rejections.json").read_text())


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs) -> None:
        raise AssertionError("No service or secret access during quantity regression")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


@pytest.mark.parametrize("original,chinese", [
    (SAVED["c19"]["original"], SAVED["c19"]["chinese"]),
    ("5.5 million articles.", "550万篇文章。"),
    ("550万篇文章。", "5.5 million articles."),
    ("5.5百万篇文章。", "550万篇文章。"),
    ("0.5 million records.", "50万条记录。"),
    ("5500000 articles.", "550万篇文章。"),
    ("About 5.5 million articles.", "约550万篇文章。"),
    ("<5.5 million articles.", "<550万篇文章。"),
    ("+5.5 million records.", "+550万条记录。"),
    ("-5.5 million records.", "-550万条记录。"),
    ("5.5 million bytes.", "550万字节。"),
    ("5.5 million tokens/s.", "550万个token/秒。"),
    ("5.5 billion records.", "550000万条记录。"),
    ("5.5 trillion records.", "5.5万亿条记录。"),
    ("55 thousand records.", "5.5万条记录。"),
    ("±5.5 million records.", "±550万条记录。"),
    ("5.5 million m.", "550万米。"),
    ("5.5 million kg.", "550万千克。"),
    ("1.2345678901234567890123456789 million records.",
     "123.45678901234567890123456789万条记录。"),
])
def test_exact_count_scale_notation_preserves_original_quantity(
    original: str, chinese: str,
) -> None:
    findings = []
    assert _preserve_quantities(original, chinese, findings=findings, field="claims") == chinese
    assert not findings


@pytest.mark.parametrize("original,wrong", [
    ("5.5 million records.", "55万条记录。"),
    ("5.5 million records.", "5500万条记录。"),
    ("5.5 million records.", "550百万条记录。"),
    ("5.5 million records.", "550万亿条记录。"),
    ("-5.5 million records.", "+550万条记录。"),
    ("+5.5 million records.", "550万条记录。"),
    ("±5.5 million records.", "550万条记录。"),
    ("About 5.5 million records.", "550万条记录。"),
    ("<5.5 million records.", ">550万条记录。"),
    ("5.5 million bytes.", "550万个token。"),
    ("5.5 million bytes/s.", "550万字节/毫秒。"),
    ("5.5 million bytes.", "550万。"),
    ("5.5 million records.", "5500千克。"),
    ("5.5 million records.", "550万米。"),
    ("-0 million records.", "0万条记录。"),
    ("5.5 million A records and 2 million B records.", "A有200万条，B有550万条。"),
    ("1.2345678901234567890123456789 million records.",
     "123.45678901234567890123456788万条记录。"),
    ("5,5 million records.", "550万条记录。"),
])
def test_scale_equivalence_cannot_change_values_order_units_or_qualifiers(
    original: str, wrong: str,
) -> None:
    findings = []
    assert _preserve_quantities(original, wrong, findings=findings, field="claims") == original
    assert findings


def numeric_failure(text: str, evidence: str) -> str | None:
    """Only the numeric predicate; source identity/row/semantic gates are separate."""
    claim = Claim(text, ClaimStatus.SUPPORTED,
                  [EvidenceAnchor(SAVED["source_url"], evidence)])
    resolution = AnchorResolution(0, text, "matched", "source_block",
                                  quote=evidence, resolved_quote=evidence)
    assert not fact_is_reviewed(claim)
    return _numeric_anchor_failure(claim, [resolution])


@pytest.mark.parametrize("text,evidence", [
    (SAVED["c35"]["candidate"], SAVED["c35"]["evidence"]),
    ("The metrics are rank-precision at 5 (RP@5) and at 10 (RP@10).",
     "The metrics are rank-precision@5 (RP@5) and rank-precision@10 (RP@10)."),
    ("The metrics are RP@5 and RP@10.",
     "The metrics are rank-precision at 5 (RP@5) and at 10 (RP@10)."),
    ("The metrics are sample-score at 8 (SS@8) and at 16 (SS@16).",
     "The metrics are sample-score@8 (SS@8) and sample-score@16 (SS@16)."),
])
def test_coordinated_cutoff_requires_an_explicit_matching_metric_reference(
    text: str, evidence: str,
) -> None:
    assert numeric_failure(text, evidence) is None


@pytest.mark.parametrize("text", [
    "The metrics are rank-precision at 5 (RP@5) and at 10 (RP@20).",
    "The metrics are rank-precision at 5 (RP@5) and at 10 (Other@10).",
    "The metrics are rank-precision at 5 (RP@5) and at 10.",
    "The metrics are rank-precision at 5 (RP@5) and at 20 (RP@20).",
    "The observed score is 10.",
    "The observed score is 0.280 and at 10 (RP@10).",
    SAVED["c35"]["candidate"].replace("0.265", "0.999"),
])
def test_cutoffs_do_not_supply_other_indices_aliases_or_measured_values(text: str) -> None:
    assert numeric_failure(text, SAVED["c35"]["evidence"]) is not None


def test_saved_count_translation_reaches_composition_without_inheriting_final_approval() -> None:
    reading, base = candidates()
    claim = replace(base, text=SAVED["c19"]["original"],
        evidence=[replace(base.evidence[0], quote=SAVED["c19"]["original"])])
    source = SourceCandidate(
        "Public FEVER excerpt", reading.source_url, SourceType.PAPER, "fixture",
    )
    artifact = Artifact(source, claim.text)
    reviewer = SchemaReviewer()
    facts = review_publication_facts([claim], reviewer, model="offline",
                                    readings=[reading], artifacts=[artifact])
    chinese = SAVED["c19"]["chinese"]
    writer = Composer({"claims": [{"claim_id": "c1", "text": chinese}],
        "reader_explanation": {"experiment_interpretation": [
            {"text": chinese.removeprefix("Experiment: "), "supporting_claim_ids": ["c1"]}]}})
    result = localize_report_content(readings=facts.readings, claims=facts.claims,
        sources=[source], provider=writer, model="offline", language="zh", verified_facts=True)
    assert not localization_failed(result)
    assert len(writer.requests) == 1
    assert result.claims[0].text == chinese
    assert result.claims[0].evidence == facts.claims[0].evidence
    assert result.claims[0].metadata == facts.claims[0].metadata
    assert not fact_is_reviewed(result.claims[0])
    assert result.readings[0].reader_explanation.experiment_interpretation[0].review is None
