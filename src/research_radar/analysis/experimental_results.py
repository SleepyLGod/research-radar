"""Source-bound experimental observations, never an independent approval channel."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields

from research_radar.analysis.source_references import SourceReferenceError, selected_source_unit
from research_radar.evidence.pdf_tables import quoted_table_context
from research_radar.evidence.quotes import QuoteMatch, find_quote
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, Claim, EvidenceAnchor, dataclass_to_dict


@dataclass(frozen=True)
class ExperimentalObservation:
    """One method/condition's reported value, with no inferred numeric conversion."""

    subject: str
    value: str


@dataclass(frozen=True)
class ExperimentalResult:
    """Reader proposal linking a result to its scope, conditions and literal sources."""

    result_id: str
    question: str
    conditions: list[str]
    metric: str
    observations: list[ExperimentalObservation]
    comparison_scope: list[str]
    uncertainty: list[str]
    supporting_claim_ids: list[str]
    evidence: list[EvidenceAnchor]
    source_kind: str
    source_label: str
    physical_page: int | None
    binding_status: str


def parse_experimental_results(
    value: object, artifact: Artifact, *, claim_ids: set[str],
) -> list[ExperimentalResult]:
    """Validate the new optional contract; never reconstruct a missing table/figure cell."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisError("experimental_results must be a list.")
    result = []
    known: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {f.name for f in fields(ExperimentalResult)}:
            raise AnalysisError("experimental_results requires complete, explicit records.")
        for key in ("result_id", "question", "metric", "source_label"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise AnalysisError(f"experimental_results.{key} must be nonempty text.")
        for key in ("conditions", "comparison_scope", "uncertainty", "supporting_claim_ids"):
            if (not isinstance(item[key], list)
                    or any(not isinstance(t, str) or not t.strip() for t in item[key])
                    or len(set(item[key])) != len(item[key])):
                raise AnalysisError(f"experimental_results.{key} must be distinct text items.")
        ids = item["supporting_claim_ids"]
        if not ids or not set(ids) <= claim_ids or item["result_id"] in known:
            raise AnalysisError("Experimental result ids must be unique and claim-bound.")
        if item["source_kind"] not in ("text", "table", "figure"):
            raise AnalysisError("Unknown experimental result source kind.")
        if item["binding_status"] not in ("text_bound", "unresolved", "source_conflict"):
            raise AnalysisError("Experimental results cannot declare themselves approved.")
        page = item["physical_page"]
        if page is not None and (type(page) is not int or page < 1):
            raise AnalysisError("Experimental result physical_page must be positive or null.")
        observations = item["observations"]
        if not isinstance(observations, list) or any(
            not isinstance(o, dict) or set(o) != {"subject", "value"}
            or any(not isinstance(o[k], str) or not o[k].strip() for k in ("subject", "value"))
            for o in observations
        ):
            raise AnalysisError("Experimental observations require exact subject/value text.")
        anchors = item["evidence"]
        if not isinstance(anchors, list) or not anchors:
            raise AnalysisError("Experimental results require literal source context.")
        evidence = []
        for anchor in anchors:
            if (not isinstance(anchor, dict) or set(anchor) != {"quote", "location"}
                    or any(not isinstance(anchor[k], str) or not anchor[k].strip()
                           for k in ("quote", "location"))
                    or find_quote(anchor["quote"], artifact.text) is None):
                raise AnalysisError("Experimental source quotation is missing or unmatched.")
            selected_source_unit(artifact, anchor["quote"], anchor["location"])
            evidence.append(EvidenceAnchor(source_url=artifact.source.url,
                source_title=artifact.source.title, quote=anchor["quote"],
                location=anchor["location"]))
        result.append(ExperimentalResult(**{**item,
            "observations": [ExperimentalObservation(**o) for o in observations],
            "evidence": evidence}))
        known.add(item["result_id"])
    return result


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def experimental_assertion_identity(claim: Claim) -> str:
    """Bind an offered assertion to its exact text, identity, status and source anchors."""
    return _digest({"text": claim.text, "identity": claim.metadata.get("paper_reading"),
                    "status": claim.status.value,
                    "evidence": [dataclass_to_dict(e) for e in claim.evidence]})


def _label(value: str) -> str:
    # A detached PDF superscript is typography; the variant marker itself is identity.
    return re.sub(r"\s+\*", "*", " ".join(value.casefold().replace("∗", "*").split()))


def _contains_label(subject: str, label: str) -> bool:
    return re.search(r"(?<![\w*])" + re.escape(_label(label)) + r"(?![\w*])",
                     _label(subject)) is not None


def _source_evidence(result: ExperimentalResult, artifact: Artifact) -> dict:
    """Expose unchanged spans and cells; anchor indexes address result.evidence, not row order."""
    spans = []
    selections: dict[tuple[str, str], dict] = {}
    for anchor in result.evidence:
        if anchor.source_url != artifact.source.url:
            continue
        try:
            unit = selected_source_unit(artifact, anchor.quote, anchor.location)
        except SourceReferenceError:
            continue
        match = (find_quote(anchor.quote, artifact.text) if unit is None
                 else QuoteMatch(unit.start, unit.end, "source_block"))
        if match:
            spans.append({**dataclass_to_dict(anchor), "start": match.start, "end": match.end,
                          "source_text_sha256": hashlib.sha256(artifact.text.encode()).hexdigest()})
    labels = re.findall(r"\bTable \d+\b", result.source_label)
    if labels:
        for anchor_index, anchor in enumerate(result.evidence):
            if anchor.source_url != artifact.source.url:
                continue
            positioned = quoted_table_context(artifact, anchor.quote,
                " ".join(f"{label}:" for label in labels), result.physical_page,
                location=anchor.location)
            if not positioned or not positioned["table"].get("complete_grid"):
                continue
            table = positioned["table"]
            for cell in table["cells"]:
                if cell["cell_id"] not in positioned["selected_cell_ids"]:
                    continue
                key = (table["table_id"], cell["cell_id"])
                record = selections.setdefault(key, {"source_url": artifact.source.url,
                    "source_text_sha256": table["source_text_sha256"],
                    "document_sha256": table["document_sha256"],
                    "table_id": table["table_id"], "physical_page": table["physical_page"],
                    "cell_id": cell["cell_id"], "row_headers": cell["row_headers"],
                    "column_headers": cell["column_headers"], "value": cell["value"],
                    "anchor_indexes": []})
                if anchor_index not in record["anchor_indexes"]:
                    record["anchor_indexes"].append(anchor_index)
    return {"status": "positioned" if selections else "text" if spans else "unavailable",
            "spans": spans, "cells": list(selections.values())}


def _observation_cells(result: ExperimentalResult, source: dict) -> list[dict]:
    bound = []
    for observation in result.observations:
        if result.source_kind == "text":
            bound.append({"observation": dataclass_to_dict(observation),
                "status": "text_bound" if source["spans"] else "unresolved",
                "reason": "text_requires_semantic_review" if source["spans"] else "source_missing",
                "cell": None})
            continue
        # Resolve row/metric identity BEFORE inspecting the value. A value cannot choose a row.
        matches = [c for c in source["cells"]
                   if c["row_headers"] and all(_contains_label(observation.subject, h)
                                               for h in c["row_headers"])
                   and _label(result.metric) == _label(" ".join(c["column_headers"]))]
        cell = matches[0] if len(matches) == 1 else None
        if cell is not None and cell["value"] == "-":
            reason, cell = "value_not_reported", None
        elif cell is not None and observation.value != cell["value"]:
            reason, cell = "literal_value_mismatch", None
        else:
            reason = "unique_literal_cell" if cell is not None else "no_unique_quoted_cell"
        if cell is not None:
            cell = {**cell, "anchors": [dataclass_to_dict(result.evidence[i])
                                        for i in cell["anchor_indexes"]]}
        bound.append({"observation": dataclass_to_dict(observation),
                      "status": "cell_bound" if cell is not None else "unresolved",
                      "reason": reason, "cell": cell})
    return bound


def bind_experimental_results(
    results: list[ExperimentalResult], artifact: Artifact, claims: list[Claim],
) -> list[dict]:
    """Connect proposals to quoted cells and exact pending assertions, never approve prose.

    Row labels are literal identity candidates, not semantic entailment. Compound values,
    inferred metric aliases, rankings and source conflicts remain for explicit review.
    """
    records = []
    for result in results:
        source = _source_evidence(result, artifact)
        observations = _observation_cells(result, source)
        assertions = []
        for identity in result.supporting_claim_ids:
            matches = [c for c in claims
                       if c.metadata.get("paper_reading", {}).get("claim_id") == identity
                       and {e.source_url for e in c.evidence} == {artifact.source.url}]
            assertion = {"claim_id": identity, "status": "unavailable", "cell_ids": []}
            if len(matches) > 1:
                assertion["status"] = "ambiguous_identity"
            elif len(matches) == 1:
                claim = matches[0]
                anchors = [dataclass_to_dict(e) for e in claim.evidence]
                cells = []
                for observation in observations:
                    if (cell := observation["cell"]) is None:
                        continue
                    own = [e for e in anchors if any(
                        e["source_url"] == selected["source_url"]
                        and e["quote"].strip() == selected["quote"].strip()
                        for selected in cell["anchors"])]
                    if own and not any(c["cell_id"] == cell["cell_id"]
                                       and c["table_id"] == cell["table_id"] for c in cells):
                        cells.append({**cell, "anchors": own})
                shared = any(e.source_url == a["source_url"]
                             and e.quote.strip() == a["quote"].strip()
                             for e in result.evidence for a in anchors)
                assertion.update(text=claim.text, claim_status=claim.status.value,
                    assertion_sha256=experimental_assertion_identity(claim), cells=cells,
                    cell_ids=[c["cell_id"] for c in cells],
                    status=("source_conflict"
                            if shared and result.binding_status == "source_conflict"
                            else "pending_review" if cells else "unresolved"))
            assertions.append(assertion)
        record = {"proposal": dataclass_to_dict(result), "source_url": artifact.source.url,
                  "source_text_sha256": hashlib.sha256(artifact.text.encode()).hexdigest(),
                  "source_evidence": source, "observations": observations,
                  "assertions": assertions}
        records.append({**record, "binding_sha256": _digest(record)})
    return records


def table_comparison_unit(claim: Claim, proposal: dict, source_cells: list[dict]) -> dict:
    """Present a closed original metric slice; never infer pairs, aliases or directions."""
    tables: dict[str, dict] = {}
    owned: dict[str, set[str]] = {}
    complete = True
    for context in claim.metadata.get("anchor_resolution", {}).get("evidence_contexts", []):
        positioned = context.get("positioned")
        if not positioned or not any(e.source_url == context.get("source_url")
                                    and e.quote.strip() == context.get("quote", "").strip()
                                    for e in claim.evidence):
            continue
        table = positioned["table"]
        identity = table["table_id"]
        if identity in tables and tables[identity] != table:
            complete = False
        tables[identity] = table
        owned.setdefault(identity, set()).update(positioned["selected_cell_ids"])
    available = {(c["table_id"], c["cell_id"]): c for c in source_cells}
    if len(available) != len(source_cells):
        complete = False
    selected = []
    exact = True
    for identity in sorted({c["table_id"] for c in source_cells}):
        table = tables.get(identity)
        if (not table or not table.get("complete_grid")
                or not table.get("document_sha256") or not table.get("source_text_sha256")
                or (proposal.get("physical_page") is not None
                    and proposal["physical_page"] != table.get("physical_page"))
                or {e.source_url for e in claim.evidence} != {table.get("source_url")}):
            complete = False
            continue
        columns = {tuple(c["column_headers"]) for c in table["cells"]}
        matched = [c for c in columns if _label(" ".join(c)) == _label(proposal["metric"])]
        literal = len(matched) == 1
        exact = exact and literal
        wanted = set(matched) if literal else columns
        cells = [c for c in table["cells"] if tuple(c["column_headers"]) in wanted]
        if not cells:
            complete = False
        coordinates = [(tuple(c["row_headers"]), tuple(c["column_headers"])) for c in cells]
        if len(set(coordinates)) != len(coordinates):
            complete = False
        for cell in cells:
            original = available.get((identity, cell["cell_id"]))
            if (not original or cell["cell_id"] not in owned.get(identity, set())
                    or original.get("source_url") != table["source_url"]
                    or any(original.get(k) != cell[k]
                           for k in ("row_headers", "column_headers", "value"))):
                complete = False
        selected.append({k: table[k] for k in (
            "table_id", "source_url", "document_sha256", "source_text_sha256", "physical_page"
        )} | {"column_headers": [list(c) for c in sorted(wanted)],
             "cells": [{k: cell[k] for k in ("cell_id", "row_headers", "column_headers", "value")}
                       for cell in cells]})
    return {"kind": "table_comparison", "proposal": proposal,
            "metric_binding": "exact" if exact and selected else "semantic_review_required",
            "complete": complete and bool(selected), "tables": selected}
