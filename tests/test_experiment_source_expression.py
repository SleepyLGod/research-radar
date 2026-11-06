"""Text spans and literal source measurements are distinct from Reader comparison prose."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import legacy_saved_anchors
from test_experimental_cell_bindings import saved_result
from test_saved_memguide_evidence import DATA

from research_radar.analysis.experimental_results import bind_experimental_results


def test_text_observation_does_not_require_a_table_cell(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    result = replace(result, source_kind="text", source_label="Experimental discussion")
    record, = bind_experimental_results([result], artifact, [claim])
    assert all(o["status"] == "text_bound" for o in record["observations"])
    assert record["source_evidence"]["spans"]
    assert record["source_evidence"]["cells"] == []
    assert not claim.is_publishable()


def test_paired_strings_are_not_split_but_the_original_cells_are_explicit(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    case = next(c for c in DATA["claims"] if c["claim_id"] == "c33")
    evidence = legacy_saved_anchors(case["evidence"])
    claim = replace(claim, text=case["text"], evidence=evidence)
    result = replace(result, source_label="Table 3", physical_page=6, evidence=evidence,
        observations=[replace(result.observations[0], subject="LLaMA3-8B FCP to MemGuide",
                              value="0.64 to 0.63")])
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["observations"][0]["cell"] is None
    assert record["proposal"]["observations"][0]["value"] == "0.64 to 0.63"
    cells = record["source_evidence"]["cells"]
    assert all("anchors" not in cell and cell["anchor_indexes"] for cell in cells)
    assert all(i < len(result.evidence) for cell in cells for i in cell["anchor_indexes"])
    assert any(c["row_headers"] == ["LLaMA3-8B", "FCP"] and c["value"] == "0.64"
               and c["column_headers"] == ["JGA"] for c in cells)
    assert any(c["row_headers"] == ["LLaMA3-8B", "MemGuide"] and c["value"] == "0.63"
               and c["column_headers"] == ["JGA"] for c in cells)
    assert record["source_evidence"]["status"] == "positioned"


def test_a_mixed_source_label_keeps_both_prose_and_table_without_resolving_conflict(
    tmp_path: Path,
) -> None:
    artifact, result, claim = saved_result(tmp_path)
    case = next(c for c in DATA["claims"] if c["claim_id"] == "c49")
    evidence = legacy_saved_anchors(case["evidence"])
    result = replace(result, source_label="Table 12 and accompanying prose", physical_page=12,
                     binding_status="source_conflict", evidence=evidence)
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["proposal"]["binding_status"] == "source_conflict"
    assert len(record["source_evidence"]["spans"]) == len(evidence)
    assert any(c["row_headers"] == ["Mistral-7B", "FCP"] and c["value"] == "10.09"
               for c in record["source_evidence"]["cells"])
    assert "10.90" in json.dumps(record["source_evidence"]["spans"])


@pytest.mark.parametrize("bad", ["missing", "foreign", "stale"])
def test_no_source_span_or_cell_is_invented(tmp_path: Path, bad: str) -> None:
    artifact, result, claim = saved_result(tmp_path)
    if bad == "missing":
        result = replace(result, evidence=[replace(result.evidence[0], quote="No such quote")])
    elif bad == "foreign":
        result = replace(result, evidence=[replace(e, source_url="https://example.org/elsewhere")
                                          for e in result.evidence])
    else:
        artifact = replace(artifact, text="Changed source")
    record, = bind_experimental_results([result], artifact, [claim])
    assert not record["source_evidence"]["spans"]
    assert not record["source_evidence"]["cells"]
