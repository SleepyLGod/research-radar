"""Whole-page caption ownership precedes numeric grid assignment."""

import copy
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from research_radar.analysis.figures import PdfPageBbox, PdfTextWord
from research_radar.evidence.pdf_tables import attach_table_evidence
from research_radar.models import Artifact, SourceCandidate, SourceType

DATA = json.loads((Path(__file__).parent / "fixtures/method_flow/memguide_full_page12.json")
                  .read_text())


def full_page(tmp_path: Path, *, defect: str | None = None, renumber: bool = False) -> Artifact:
    """Retain every word on the original page, including the crossing caption."""
    data = copy.deepcopy(DATA)
    words = data["words"]
    if renumber:
        for word in words:
            if re.fullmatch(r"(?:9|10|11|12|13):", word[0]):
                word[0] = f"{int(word[0][:-1]) + 100}:"
        data["text"] = re.sub(r"Table (\d+):", lambda m: f"Table {int(m[1]) + 100}:",
                              data["text"])
    target = next(w for w in words if w[0] == "0.62")
    if defect == "missing_value":
        words.remove(target)
    elif defect == "glued_values":
        target[0] = "0.620.92"
        words[:] = [w for w in words if not (w[0] == "0.92" and abs(w[2] - target[2]) < 1)]
    elif defect == "missing_header":
        header = next(w for w in words if w[0] == "(Pre)")
        words[:] = [w for w in words if not (w[3] < data["width"] / 2
                                             and abs(w[2] - header[2]) < 1)]
    elif defect == "text_disagrees":
        data["text"] = data["text"].replace("LLaMA3-8B 0.62 0.92", "LLaMA3-8B 0.63 0.92")
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"whole-page-offline-identity")
    source = SourceCandidate(data["title"], data["source_url"], SourceType.PAPER, "offline")
    artifact = Artifact(source, data["text"], str(pdf), "application/pdf")
    page = PdfPageBbox(data["width"], data["height"], [PdfTextWord(*w) for w in words])
    return attach_table_evidence(artifact, page_reader=lambda *_: page)


@pytest.mark.parametrize("renumber", [False, True])
def test_crossing_caption_cannot_claim_a_column_grid(tmp_path: Path, renumber: bool) -> None:
    artifact = full_page(tmp_path, renumber=renumber)
    label = "Table 110" if renumber else "Table 10"
    (table,) = [t for t in artifact.metadata["table_evidence"] if t["label"] == label]
    assert table["binding"] == "positioned"
    assert table["header_lines"] == ["Model Slot Acc. (Pre) Task Rate (Post)"]
    assert [(c["row_headers"], c["column_headers"], c["value"]) for c in table["cells"]] == [
        ([model], [metric], value)
        for model, pre, post in [("LLaMA3-8B", "0.62", "0.92"), ("Qwen-7B", "0.48", "0.87"),
                                 ("Mistral-7B", "0.59", "1.00"), ("GPT4o-mini", "0.61", "0.99")]
        for metric, value in [("Slot Acc. (Pre)", pre), ("Task Rate (Post)", post)]
    ]
    crossing = "Table 109" if renumber else "Table 9"
    assert not any(t["label"] == crossing and t["binding"] == "positioned"
                   for t in artifact.metadata["table_evidence"])
    assert len(table["source_rows"]) == 4
    assert artifact.text == (re.sub(r"Table (\d+):", lambda m: f"Table {int(m[1]) + 100}:",
                                    DATA["text"]) if renumber else DATA["text"])


@pytest.mark.parametrize("defect", ["missing_value", "glued_values", "missing_header",
                                    "text_disagrees"])
def test_full_page_does_not_repair_bad_cells_or_text(tmp_path: Path, defect: str) -> None:
    artifact = full_page(tmp_path, defect=defect)
    assert not any(t["label"] == "Table 10" and t["binding"] == "positioned"
                   for t in artifact.metadata["table_evidence"])


def test_previous_layout_cache_is_recomputed_without_mutating_it(tmp_path: Path) -> None:
    artifact = full_page(tmp_path)
    old_identity = [*artifact.metadata["table_evidence_identity"][:2], 2]
    old = replace(artifact, metadata={"table_evidence_identity": old_identity,
                                     "table_evidence": [{"label": "old-unresolved-cache"}]})
    page = PdfPageBbox(DATA["width"], DATA["height"], [PdfTextWord(*w) for w in DATA["words"]])
    fresh = attach_table_evidence(old, page_reader=lambda *_: page)
    assert fresh.metadata["table_evidence_identity"][-1] > 2
    assert any(t["label"] == "Table 10" and t["binding"] == "positioned"
               for t in fresh.metadata["table_evidence"])
    assert old.metadata["table_evidence"] == [{"label": "old-unresolved-cache"}]
    assert old.metadata["table_evidence_identity"] == old_identity
