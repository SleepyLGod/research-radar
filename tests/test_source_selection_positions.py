"""Selected source blocks retain exact positions; unselected quotes stay legacy."""

import hashlib
import json
from dataclasses import replace

import pytest

from research_radar.analysis.anchor_repair import apply_anchor_repair, apply_anchor_resolution
from research_radar.analysis.experimental_results import (
    ExperimentalResult,
    bind_experimental_results,
    parse_experimental_results,
)
from research_radar.analysis.figures import PdfPageBbox, PdfTextWord
from research_radar.analysis.paper_reading import (
    _reading_response_example,
    parse_paper_reading,
    validate_paper_reading,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.source_references import build_source_index
from research_radar.evidence.pdf_tables import (
    _original_grid_rows,
    positioned_tables,
    quoted_table_context,
)
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)

ROWS = "Alpha 10 20\nBeta 30 40"


def _artifact(text: str) -> Artifact:
    return Artifact(SourceCandidate("Offline", "https://example.test/paper",
                                    SourceType.PAPER, "fixture"), text)


def _tables(*, positioned: bool = False) -> Artifact:
    artifact = _artifact(
        f"[page 1]\nTable 1: First experiment\nMethod Accuracy Latency\n{ROWS}\n\n"
        f"[page 2]\nTable 2: Second experiment\nMethod Latency Accuracy\n{ROWS}\n"
    )
    if not positioned:
        return artifact
    tables = []
    for page, metrics in ((1, ("Accuracy", "Latency")), (2, ("Latency", "Accuracy"))):
        lines = [(10, [(10, f"Table {page}: Results")]),
                 (30, [(10, "Method"), (110, metrics[0]), (210, metrics[1])]),
                 (50, [(10, "Alpha"), (110, "10"), (210, "20")]),
                 (70, [(10, "Beta"), (110, "30"), (210, "40")])]
        bbox = PdfPageBbox(300, 200, [
            PdfTextWord(text, x, y, x + 40, y + 10)
            for y, words in lines for x, text in words
        ])
        table = positioned_tables(bbox, physical_page=page)[0]
        source_rows = _original_grid_rows(table, artifact.text)
        assert table["complete_grid"] and source_rows
        tables.append({**table, "table_id": f"table-{page}",
            "source_url": artifact.source.url, "document_sha256": "offline-document",
            "source_text_sha256": hashlib.sha256(artifact.text.encode()).hexdigest(),
            "source_rows": source_rows,
            "cells": [{"cell_id": f"c{i}", **cell}
                      for i, cell in enumerate(table["cells"], 1)]})
    return replace(artifact, metadata={"table_evidence": tables})


def _selection(artifact: Artifact, text: str) -> dict[str, str]:
    index = build_source_index(artifact)
    start = artifact.text.rindex(text)
    return index.reference_for_span(start, start + len(text))


def _anchor(artifact: Artifact, text: str) -> EvidenceAnchor:
    selected = build_source_index(artifact).resolve(_selection(artifact, text))
    return EvidenceAnchor(artifact.source.url, selected["quote"].strip(), selected["location"])


def _experiment(artifact: Artifact, anchor: EvidenceAnchor) -> ExperimentalResult:
    return parse_experimental_results([{
        "result_id": "r1", "question": "What latency does Alpha report?", "conditions": [],
        "metric": "Latency", "observations": [{"subject": "Alpha", "value": "10"}],
        "comparison_scope": [], "uncertainty": [], "supporting_claim_ids": ["c1"],
        "evidence": [{"quote": anchor.quote, "location": anchor.location}],
        "source_kind": "table", "source_label": "Table 2", "physical_page": 2,
        "binding_status": "text_bound",
    }], artifact, claim_ids={"c1"})[0]


@pytest.mark.parametrize("positioned", [False, True])
@pytest.mark.parametrize(("value", "publishable"), [("10", True), ("20", False)])
def test_fresh_selection_uses_second_page_columns(
    positioned: bool, value: str, publishable: bool,
) -> None:
    artifact = _tables(positioned=positioned)
    reference = _selection(artifact, ROWS)
    payload = json.loads(_reading_response_example(
        facts_only=True, source_id=reference["source_id"],
    ))
    payload["deep_readings"][0]["claim_units"][1]["text"] = (
        f"Alpha reports Latency of {value}."
    )
    reading = parse_paper_reading(json.dumps(payload), artifact,
        require_source_references=True, require_explanation_bindings=True,
        require_method_assertions=True)
    claims, _ = validate_paper_reading(reading, artifact)
    claim = next(c for c in claims if c.metadata.get("paper_reading", {}).get("claim_id") == "c2")
    assert claim.evidence[0].location.startswith("page 2; source block ")
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].page == 2
    assert checked[0].is_publishable() is publishable
    if positioned and publishable:
        contexts = checked[0].metadata["anchor_resolution"]["evidence_contexts"]
        assert contexts[0]["positioned"]["table"]["table_id"] == "table-2"


def test_repeated_prose_on_one_page_uses_selected_section_context() -> None:
    artifact = _artifact(
        "[page 1]\n1 First Condition\nFirst-context-only.\n\nShared observation.\n\n"
        "2 Second Condition\nSecond-context-only.\n\nShared observation.\n"
    )
    claim = Claim("A measured observation.", ClaimStatus.SUPPORTED,
                  evidence=[_anchor(artifact, "Shared observation.")])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].page == 1
    assert "Second-context-only." in resolutions[0].resolved_quote
    assert "First-context-only." not in resolutions[0].resolved_quote
    contexts = checked[0].metadata["anchor_resolution"]["evidence_contexts"]
    assert "Second-context-only." in contexts[0]["text"]
    assert "First-context-only." not in contexts[0]["text"]


@pytest.mark.parametrize("defect", [
    "foreign_url", "mutated_source", "wrong_page", "unknown_block", "malformed", "quote",
    "normalized_quote",
])
def test_invalid_selected_reference_never_falls_back_to_matching_text(defect: str) -> None:
    artifact = _tables()
    anchor = _anchor(artifact, ROWS)
    if defect == "foreign_url":
        artifact = replace(artifact, source=replace(artifact.source, url="https://other.test/p"))
        anchor = replace(anchor, source_url=artifact.source.url)
    elif defect == "mutated_source":
        artifact = replace(artifact, text=artifact.text + "\nNew source text.\n")
    elif defect == "wrong_page":
        anchor = replace(anchor, location=anchor.location.replace("page 2;", "page 1;"))
    elif defect == "unknown_block":
        anchor = replace(anchor, location=anchor.location.rsplit(":", 1)[0] + ":99999")
    elif defect == "malformed":
        anchor = replace(anchor, location="page 2; source block not-a-source-id")
    elif defect == "quote":
        anchor = replace(anchor, quote="Method Accuracy Latency")
    else:
        anchor = replace(anchor, quote=anchor.quote.lower())
    claim = Claim("A measured observation.", ClaimStatus.SUPPORTED, evidence=[anchor])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()


@pytest.mark.parametrize("extra_anchor", [False, True])
@pytest.mark.parametrize("defect", ["unknown_block", "empty_quote", "foreign_anchor"])
def test_invalid_selection_cannot_be_replaced_by_quote_repair(
    extra_anchor: bool, defect: str,
) -> None:
    artifact = _tables()
    anchor = _anchor(artifact, ROWS)
    if defect == "empty_quote":
        anchor = replace(anchor, quote="")
    elif defect == "foreign_anchor":
        foreign = replace(artifact, source=replace(artifact.source, url="https://other.test/p"))
        anchor = _anchor(foreign, ROWS)
    else:
        anchor = replace(anchor, location=anchor.location.rsplit(":", 1)[0] + ":99999")
    evidence = [anchor]
    if extra_anchor:
        evidence.append(EvidenceAnchor(artifact.source.url, "First experiment"))
    claim = Claim("A measured observation.", ClaimStatus.SUPPORTED, evidence=evidence)

    class NoRepair:
        name = "offline-forbidden-repair"

        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            pytest.fail("Invalid source selection must not request a replacement quote.")

    checked, resolutions, repairs, _ = apply_anchor_repair(
        [claim], artifact, NoRepair(), model="offline",
    )
    assert resolutions[0].status == "failed"
    assert not checked[0].is_publishable()
    assert [repair.status for repair in repairs] == ["skipped"]


def test_experimental_selection_keeps_second_page_span_and_cells() -> None:
    artifact = _tables(positioned=True)
    anchor = _anchor(artifact, ROWS)
    result = _experiment(artifact, anchor)
    record = bind_experimental_results([result], artifact, [Claim(
        "Alpha reports Latency of 10.", ClaimStatus.SUPPORTED, evidence=[anchor],
        metadata={"paper_reading": {"claim_id": "c1"}},
    )])[0]
    source = record["source_evidence"]
    assert source["status"] == "positioned"
    assert [(s["start"], s["end"]) for s in source["spans"]] == [
        (artifact.text.rindex(ROWS), len(artifact.text)),
    ]
    assert {c["table_id"] for c in source["cells"]} == {"table-2"}
    assert {c["physical_page"] for c in source["cells"]} == {2}
    assert [(c["row_headers"], c["column_headers"], c["value"]) for c in source["cells"]] == [
        (["Alpha"], ["Latency"], "10"), (["Alpha"], ["Accuracy"], "20"),
        (["Beta"], ["Latency"], "30"), (["Beta"], ["Accuracy"], "40"),
    ]
    observation = record["observations"][0]
    assert observation["status"] == "cell_bound"
    assert observation["cell"]["table_id"] == "table-2"
    assert observation["cell"]["cell_id"] == "c1"


@pytest.mark.parametrize("defect", ["forged_id", "foreign_anchor", "mutated_source", "quote"])
def test_experimental_binding_rejects_invalid_selection_without_quote_fallback(defect: str) -> None:
    artifact = _tables(positioned=True)
    anchor = _anchor(artifact, ROWS)
    result = _experiment(artifact, anchor)
    if defect == "forged_id":
        anchor = replace(anchor, location=anchor.location.rsplit(":", 1)[0] + ":99999")
    elif defect == "foreign_anchor":
        foreign = replace(artifact, source=replace(artifact.source, url="https://other.test/p"))
        anchor = replace(_anchor(foreign, ROWS), source_url=artifact.source.url)
    elif defect == "mutated_source":
        artifact = replace(artifact, text=artifact.text + "\nNew source text.\n")
    else:
        anchor = replace(anchor, quote=anchor.quote.lower())
    record = bind_experimental_results([replace(result, evidence=[anchor])], artifact, [])[0]
    assert record["source_evidence"] == {"status": "unavailable", "spans": [], "cells": []}
    assert record["observations"][0]["status"] == "unresolved"


@pytest.mark.parametrize("defect", ["forged_location", "extra_key", "source_id_only"])
def test_direct_experimental_parser_preserves_strict_evidence_contract(defect: str) -> None:
    artifact = _tables()
    anchor = _anchor(artifact, ROWS)
    reference = _selection(artifact, ROWS)
    payload = json.loads(_reading_response_example(
        facts_only=True, source_id=reference["source_id"],
    ))["deep_readings"][0]["experimental_results"]
    evidence = {"quote": anchor.quote, "location": anchor.location}
    if defect == "forged_location":
        evidence["location"] = anchor.location.rsplit(":", 1)[0] + ":99999"
    elif defect == "extra_key":
        evidence["source_url"] = artifact.source.url
    else:
        evidence = reference
    payload[0]["evidence"] = [evidence]
    with pytest.raises(AnalysisError):
        parse_experimental_results(payload, artifact, claim_ids={"c2"})


def test_positioned_table_selection_requires_matching_page_and_source_location() -> None:
    artifact = _tables(positioned=True)
    anchor = _anchor(artifact, ROWS)
    selected = quoted_table_context(artifact, anchor.quote, "Table 2:", 2,
                                    location=anchor.location)
    assert selected["table"]["table_id"] == "table-2"
    assert selected["selected_cell_ids"] == ["c1", "c2", "c3", "c4"]
    assert quoted_table_context(artifact, anchor.quote, "Table 2:", 1,
                                location=anchor.location) is None
    assert quoted_table_context(artifact, anchor.quote, "Table 1:", 2,
                                location=anchor.location) is None
    assert quoted_table_context(artifact, "Method Accuracy Latency", "Table 2:", 2,
                                location=anchor.location) is None


@pytest.mark.parametrize("location", [None, "page 2"])
def test_legacy_quote_without_source_id_keeps_first_match(location: str | None) -> None:
    artifact = _tables()
    claim = Claim("Alpha reports Latency of 20.", ClaimStatus.SUPPORTED,
                  evidence=[EvidenceAnchor(artifact.source.url, ROWS, location)])
    checked, resolutions, _ = apply_anchor_resolution([claim], artifact)
    assert resolutions[0].page == 1
    assert checked[0].is_publishable()
