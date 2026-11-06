"""PDF coordinates establish table cells without splitting strings of glued digits."""

import copy
import json
from pathlib import Path

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.figures import PdfPageBbox, PdfTextWord
from research_radar.evidence.pdf_tables import attach_table_evidence
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

DATA = json.loads(
    (Path(__file__).parent / "fixtures/method_flow/positioned_tables.json").read_text()
)


def positioned(name: str, tmp_path: Path, *, mutate=None) -> Artifact:
    """Use observed public coordinates; the PDF byte stand-in is never parsed by the fake."""
    case = copy.deepcopy(next(c for c in DATA["cases"] if c["name"] == name))
    if mutate:
        mutate(case)
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"offline-original-identity")
    page = case["bbox"]
    bbox = PdfPageBbox(page["width"], page["height"], [PdfTextWord(**w) for w in page["words"]])
    artifact = Artifact(
        SourceCandidate(name, case["source_url"], SourceType.PAPER, "offline"),
        case["text"], str(pdf), "application/pdf",
    )
    return attach_table_evidence(artifact, page_reader=lambda *_: bbox)


def table(artifact: Artifact) -> dict:
    resolved = [t for t in artifact.metadata["table_evidence"] if t["binding"] == "positioned"]
    assert len(resolved) == 1
    return resolved[0]


@pytest.mark.parametrize(("name", "row", "column", "value"), [
    ("conflict3", ["LangMem"], ["Dynamic", "AA"], "0.4966"),
    ("conflict3", ["MemOS"], ["Static", "AA"], "0.4375"),
    ("conflict3", ["MemOS"], ["Conditional", "AA"], "0.8449"),
    ("conflict4", ["MemOS"], ["Average", "SEH@3"], "0.6710"),
    ("conflict4", ["MemOS"], ["Average", "SRS"], "0.5879"),
    ("conflict6", ["MemOS"], ["Total Runtime"], "1356.3033"),
    ("guide3", ["Mistral-7B", "FCP"], ["JGA"], "0.73"),
    ("guide3", ["Mistral-7B", "MemGuide"], ["DTE"], "1.21"),
    ("guide3", ["GPT-4o-mini", "MemGuide"], ["DTE"], "3.19"),
])
def test_observed_layout_keeps_exact_row_column_group_and_value(
    name, row, column, value, tmp_path,
):
    artifact = positioned(name, tmp_path)
    result = table(artifact)
    matches = [c for c in result["cells"] if c["row_headers"] == row
               and c["column_headers"] == column]
    assert len(matches) == 1 and matches[0]["value"] == value
    assert matches[0]["box"][2] > matches[0]["box"][0]
    assert result["physical_page"] > 0 and result["document_sha256"]
    assert result["source_text_sha256"]
    assert result["complete_grid"] is True


def test_source_text_and_original_digit_strings_are_not_rewritten(tmp_path):
    artifact = positioned("conflict3", tmp_path)
    assert "LangMem0.49660.3579" in artifact.text
    assert "0.43750.23610.8449" in artifact.text
    assert "0.4375" in [cell["value"] for cell in table(artifact)["cells"]]


@pytest.mark.parametrize(("column", "value", "eligible"), [
    ("Static AA", "0.4375", True), ("Static AA", "0.3793", False),
    ("Conditional AA", "0.8449", True), ("Conditional AA", "0.4375", False),
])
def test_literal_source_quote_gets_cells_without_borrowing_another_column(
    column, value, eligible, tmp_path,
):
    artifact = positioned("conflict3", tmp_path)
    quote = artifact.text.split("AA UOCS AA CRS AA AA\n")[1]
    claim = Claim(f"MemOS reports {column} of {value}.", ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(artifact.source.url, quote)])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].is_publishable() is eligible
    assert "fact_review" not in checked[0].metadata
    assert checked[0].evidence == claim.evidence


def test_glued_word_without_geometric_cell_boundaries_stays_unresolved(tmp_path):
    def glue(case):
        case["bbox"]["words"] = [w for w in case["bbox"]["words"] if w["text"] != "0.2361"]
        w = next(w for w in case["bbox"]["words"] if w["text"] == "0.4375")
        w["text"] = "0.43750.2361"
    artifact = positioned("conflict3", tmp_path, mutate=glue)
    assert not any(t["binding"] == "positioned" for t in artifact.metadata["table_evidence"])


def test_missing_word_is_not_silently_a_complete_comparison(tmp_path):
    def remove(case):
        case["bbox"]["words"] = [w for w in case["bbox"]["words"] if w["text"] != "0.4375"]
    artifact = positioned("conflict3", tmp_path, mutate=remove)
    assert not any(t["binding"] == "positioned" for t in artifact.metadata["table_evidence"])


def test_missing_entire_row_does_not_turn_remaining_rows_into_a_complete_comparison(tmp_path):
    def remove(case):
        case["bbox"]["words"] = [w for w in case["bbox"]["words"]
                                  if not 219 < w["y_min"] < 231]
    artifact = positioned("conflict3", tmp_path, mutate=remove)
    assert not any(t["binding"] == "positioned" for t in artifact.metadata["table_evidence"])


@pytest.mark.parametrize(("model", "value", "eligible"), [
    ("Mistral-7B", "1.21", True), ("Mistral-7B", "3.19", False),
    ("GPT-4o-mini", "1.21", False),
])
def test_model_group_and_setting_identify_one_row_not_two_competing_methods(
    model, value, eligible, tmp_path,
):
    artifact = positioned("guide3", tmp_path)
    quote = artifact.text[artifact.text.index("Mistral-7B FCP"):
                          artifact.text.index("GPT-4o-mini FCP")]
    claim = Claim(f"Under {model}, MemGuide reports DTE of {value}.", ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(artifact.source.url, quote)])
    checked, _, _ = apply_anchor_resolution([claim], artifact)
    assert checked[0].is_publishable() is eligible


def test_unrecognized_glued_row_cannot_disappear_from_comparison_scope(tmp_path):
    def remove(case):
        line = next(line for line in case["text"].splitlines() if line.startswith("Memobase"))
        case["text"] = case["text"].replace(line, "".join(line.split()))
        case["bbox"]["words"] = [w for w in case["bbox"]["words"]
                                  if not 219 < w["y_min"] < 231]
    artifact = positioned("conflict3", tmp_path, mutate=remove)
    assert not any(t["binding"] == "positioned" for t in artifact.metadata["table_evidence"])


@pytest.mark.parametrize(("column", "value", "eligible"), [
    ("UOCS", "0.3818", True), ("UOCS", "0.4375", False),
    ("CRS", "0.2361", True), ("CRS", "0.8449", False),
    ("Static UOCS", "0.3818", False), ("AA", "0.4375", False),
])
def test_unique_leaf_metric_binds_a_column_without_borrowing_another_group(
    column, value, eligible, tmp_path,
):
    artifact = positioned("conflict3", tmp_path)
    quote = artifact.text.split("AA UOCS AA CRS AA AA\n")[1]
    checked, _, _ = apply_anchor_resolution([Claim(
        f"MemOS reports {column} of {value}.", ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(artifact.source.url, quote)],
    )], artifact)
    assert checked[0].is_publishable() is eligible


def test_table_number_is_not_a_claimed_cell_value(tmp_path):
    artifact = positioned("conflict3", tmp_path)
    quote = artifact.text.split("AA UOCS AA CRS AA AA\n")[1]
    checked, _, _ = apply_anchor_resolution([Claim(
        "In Table 3, MemOS reports Static AA of 0.4375.", ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(artifact.source.url, quote)],
    )], artifact)
    assert checked[0].is_publishable()


def test_multiword_row_labels_are_compared_with_symmetric_whitespace_handling(tmp_path):
    def multiword(case):
        case["text"] = case["text"].replace("A-Mem", "A Mem")
        next(w for w in case["bbox"]["words"] if w["text"] == "A-Mem")["text"] = "A Mem"
    artifact = positioned("conflict3", tmp_path, mutate=multiword)
    assert table(artifact)["binding"] == "positioned"


def test_quote_selects_original_row_span_not_a_suffix_named_other_row(tmp_path):
    from research_radar.analysis.anchor_repair import resolve_quote

    def similar_names(case):
        old = next(line for line in case["text"].splitlines() if line.startswith("Letta"))
        memos = next(line for line in case["text"].splitlines() if line.startswith("MemOS"))
        case["text"] = case["text"].replace(old, memos.replace("MemOS", "No-MemOS"))
        words = case["bbox"]["words"]
        original = sorted([w for w in words if 178 < w["y_min"] < 189], key=lambda w:w["x_min"])
        values = sorted([w for w in words if 192 < w["y_min"] < 203], key=lambda w:w["x_min"])
        for target, source in zip(original, values, strict=True):
            target["text"] = source["text"]
        original[0]["text"] = "No-MemOS"
    artifact = positioned("conflict3", tmp_path, mutate=similar_names)
    quote = next(line for line in artifact.text.splitlines() if line.startswith("No-MemOS"))
    context = resolve_quote(quote, artifact).table["positioned"]
    selected = [c for c in context["table"]["cells"]
                if c["cell_id"] in context["selected_cell_ids"]]
    assert {tuple(c["row_headers"]) for c in selected} == {("No-MemOS",)}
    checked, _, _ = apply_anchor_resolution([Claim(
        "MemOS reports Static AA of 0.4375.", ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(artifact.source.url, quote)],
    )], artifact)
    assert not checked[0].is_publishable()
