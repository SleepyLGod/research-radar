"""Saved two-column PDF evidence stays literal, source-scoped and conservative."""

import copy
import hashlib
import json
import socket
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import current_source_anchors, legacy_saved_anchors

from research_radar.analysis.anchor_repair import apply_anchor_resolution, resolve_quote
from research_radar.analysis.figures import PdfPageBbox, PdfTextWord
from research_radar.evidence.pdf_tables import attach_table_evidence, quoted_table_context
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)
from research_radar.security.secrets import KeychainSecretBackend

DATA = json.loads((Path(__file__).parent / "fixtures/method_flow/memguide_evidence_rejections.json"
                   ).read_text())


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("No network or credentials in saved-evidence regression")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def saved_pdf(
    tmp_path: Path, *, mutate: Callable[[list[dict]], None] | None = None,
) -> Artifact:
    """Use original word coordinates; the fake PDF only gives the fixture a byte identity."""
    pages = copy.deepcopy(DATA["pages"])
    if mutate:
        mutate(pages)
    boxes = {p["page"]: PdfPageBbox(p["width"], p["height"], [PdfTextWord(*w) for w in p["words"]])
             for p in pages}
    path = tmp_path / "source.pdf"
    path.write_bytes(b"offline-original-identity")
    original = Artifact(SourceCandidate(DATA["title"], DATA["source_url"], SourceType.PAPER,
                                        "offline"), "".join(p["text"] for p in pages),
                        str(path), "application/pdf")
    return attach_table_evidence(original, page_reader=lambda _path, n: boxes.get(n))


def resolved_table(artifact: Artifact, label: str) -> dict:
    matches = [t for t in artifact.metadata["table_evidence"]
               if t["label"] == label and t["binding"] == "positioned"]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize(("label", "row", "column", "value"), [
    ("Table 2", ["Domains"], ["Evaluation"], "16"),
    ("Table 2", ["Number of individuals"], ["Evaluation"], "132"),
    ("Table 5", ["SGD", "MemGuide ∗"], ["JGA"], "0.846"),
    ("Table 5", ["MultiWOZ 2.2", "MemGuide ∗"], ["JGA"], "0.879"),
    ("Table 12", ["Mistral-7B", "FCP"], ["BLEU"], "10.09"),
    ("Table 12", ["Mistral-7B", "MemGuide"], ["BLEU"], "6.66"),
])
def test_saved_column_tables_preserve_exact_cells(
    tmp_path: Path, label: str, row: list[str], column: list[str], value: str,
) -> None:
    artifact = saved_pdf(tmp_path)
    table = resolved_table(artifact, label)
    assert any(c["row_headers"] == row and c["column_headers"] == column and c["value"] == value
               for c in table["cells"])
    assert artifact.metadata["table_evidence_identity"][1] == hashlib.sha256(
        artifact.text.encode()).hexdigest()


def test_a_missing_metric_is_a_literal_dash_not_zero(tmp_path: Path) -> None:
    table = resolved_table(saved_pdf(tmp_path), "Table 5")
    missing = [c for c in table["cells"]
               if c["row_headers"] == ["MultiWOZ 2.2", "TRADE"] and c["column_headers"] == ["AGA"]]
    assert len(missing) == 1 and missing[0]["value"] == "-"
    assert table["complete_grid"] is True


@pytest.mark.parametrize("value", ["0", "0.976"])
def test_unreported_metric_cannot_borrow_a_number_from_another_row(
    tmp_path: Path, value: str,
) -> None:
    artifact = saved_pdf(tmp_path)
    quote = next(c for c in DATA["claims"] if c["claim_id"] == "c51")["evidence"][0]["quote"]
    claim = Claim(f"On MultiWOZ 2.2, TRADE reports AGA {value}.", ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(artifact.source.url, quote)])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("bad", ["missing_row", "missing_digit", "glued_cells", "missing_marker"])
def test_column_isolation_never_repairs_incomplete_geometry(tmp_path: Path, bad: str) -> None:
    def mutate(pages: list[dict]) -> None:
        words = next(p for p in pages if p["page"] == 12)["words"]
        target = next(w for w in words if w[0] == "10.09")
        if bad == "missing_row":
            words[:] = [w for w in words if not (abs(w[2] - target[2]) < 1 and w[1] > 300)]
        elif bad == "missing_digit":
            words.remove(target)
        elif bad == "glued_cells":
            target[0] = "10.0928.42"
        else:
            page = next(p for p in pages if p["page"] == 6)
            page["words"][:] = [w for w in page["words"] if w[0] != "∗"]
    artifact = saved_pdf(tmp_path, mutate=mutate)
    label = "Table 5" if bad == "missing_marker" else "Table 12"
    assert not any(t["label"] == label and t["binding"] == "positioned"
                   for t in artifact.metadata["table_evidence"])


def test_exact_citation_selects_only_its_own_table(tmp_path: Path) -> None:
    artifact = saved_pdf(tmp_path)
    case = next(c for c in DATA["claims"] if c["claim_id"] == "c49")
    result = resolve_quote(case["evidence"][0]["quote"], artifact)
    assert result.table["positioned"]["table"]["label"] == "Table 12"
    assert result.table["positioned"]["table"]["physical_page"] == 12
    assert result.quote == case["evidence"][0]["quote"]


@pytest.mark.parametrize(("value", "eligible"), [("10.09", True), ("10.90", False)])
def test_table12_uses_exact_source_rows_despite_neighbouring_table11_caption(
    tmp_path: Path, value: str, eligible: bool,
) -> None:
    artifact = saved_pdf(tmp_path)
    assert resolved_table(artifact, "Table 11")
    quote = next(c for c in DATA["claims"] if c["claim_id"] == "c49")["evidence"][0]["quote"]
    claim = Claim(f"Mistral-7B FCP reports BLEU {value}.", ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(artifact.source.url, quote)])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].is_publishable() is eligible


@pytest.mark.parametrize(("value", "eligible"), [("0.846", True), ("0.879", False)])
def test_caption_and_prose_anchor_does_not_disable_the_actual_table_grid(
    tmp_path: Path, value: str, eligible: bool,
) -> None:
    artifact = saved_pdf(tmp_path)
    case = next(c for c in DATA["claims"] if c["claim_id"] == "c51")
    claim = Claim(f"On SGD, MemGuide reports JGA {value}.", ClaimStatus.SUPPORTED,
                  evidence=legacy_saved_anchors(case["evidence"]))
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].is_publishable() is eligible


def test_a_quote_spanning_two_real_tables_does_not_choose_either(tmp_path: Path) -> None:
    artifact = saved_pdf(tmp_path)
    first, second = resolved_table(artifact, "Table 11"), resolved_table(artifact, "Table 12")
    quote = artifact.text[first["source_rows"][0]["start"]:second["source_rows"][-1]["end"]]
    assert quoted_table_context(
        artifact, quote, "Table 11: retrieval. Table 12: quality.", 12,
    ) is None


def test_nearby_caption_cannot_override_the_quoted_rows(tmp_path: Path) -> None:
    artifact = saved_pdf(tmp_path)
    quote = next(c for c in DATA["claims"] if c["claim_id"] == "c49")["evidence"][0]["quote"]
    assert quoted_table_context(artifact, quote, "Table 11: retrieval.", 12) is None


@pytest.mark.parametrize("identity", ["c2", "c4", "c33", "c35", "c49", "c51"])
def test_original_unresolved_assertions_are_not_auto_approved(
    tmp_path: Path, identity: str,
) -> None:
    artifact = saved_pdf(tmp_path)
    case = next(c for c in DATA["claims"] if c["claim_id"] == identity)
    claim = Claim(case["text"], ClaimStatus.SUPPORTED,
                  evidence=legacy_saved_anchors(case["evidence"]))
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert not checked[0].is_publishable()
    assert checked[0].evidence == claim.evidence


def test_current_layout_metadata_can_be_reused_without_rereading_pdf(tmp_path: Path) -> None:
    artifact = saved_pdf(tmp_path)

    def forbidden(*_args) -> None:
        raise AssertionError("Current layout metadata should be reused")

    assert attach_table_evidence(artifact, page_reader=forbidden) is artifact


def test_legacy_layout_metadata_is_recomputed_without_mutating_the_record(tmp_path: Path) -> None:
    artifact = saved_pdf(tmp_path)
    legacy = replace(artifact, metadata={**artifact.metadata,
        "table_evidence_identity": artifact.metadata["table_evidence_identity"][:2],
        "table_evidence": []})
    before = copy.deepcopy(legacy)
    boxes = {p["page"]: PdfPageBbox(p["width"], p["height"], [PdfTextWord(*w) for w in p["words"]])
             for p in DATA["pages"]}
    fresh = attach_table_evidence(legacy, page_reader=lambda _path, n: boxes.get(n))
    assert legacy == before
    assert resolved_table(fresh, "Table 5")
    assert len(fresh.metadata["table_evidence_identity"]) == 3


@pytest.mark.parametrize("text", [
    "Shared observation.\n\nShared observation.\n",
    "Prefix. Shared observation. Suffix.\n",
    "No matching observation.\n",
])
def test_excerpt_readdressing_never_guesses_ambiguous_partial_or_missing_blocks(text: str) -> None:
    artifact = Artifact(SourceCandidate("Fixture", "https://example.test/paper", SourceType.PAPER,
                                        "offline"), text)
    with pytest.raises(ValueError):
        current_source_anchors(artifact, [{"source_url": artifact.source.url,
                                         "quote": "Shared observation.", "location": "page 1"}])


def test_snapshot_legacy_projection_preserves_saved_records_and_human_page() -> None:
    records = next(c for c in DATA["claims"] if c["claim_id"] == "c51")["evidence"]
    before = copy.deepcopy(records)
    anchors = legacy_saved_anchors(records)
    assert records == before
    assert [a.quote for a in anchors] == [r["quote"] for r in records]
    assert [a.location for a in anchors] == ["page 6", "page 6"]
