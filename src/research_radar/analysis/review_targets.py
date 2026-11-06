"""Source-bound required review targets for the existing constrained-output channel."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field

from research_radar.analysis.experimental_results import (
    experimental_assertion_identity,
    table_comparison_unit,
)
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, dataclass_to_dict

REVIEW_SCHEMA_ID = "urn:research-radar:review-targets:v4"
COMPARISON_SCHEMA_ID = "urn:research-radar:review-targets:v5"
LEGACY_SELECTION_SCHEMA_ID = "urn:research-radar:review-targets:v3"
LEGACY_EVIDENCE_SCHEMA_ID = "urn:research-radar:review-targets:v2"


def _share_source_values(payload: dict) -> dict:
    """Share exact repeated field values without factoring whole roles or changing bindings."""
    fields = {"row_headers", "column_headers", "row_header_boxes", "column_header_boxes",
              "quote", "location", "literal", "text", "source_url", "source_text_sha256",
              "document_sha256"}
    counts: Counter[str] = Counter()
    values: dict[str, object] = {}
    keys: dict[str, str] = {}

    def visit(value: object, *, writing: bool = False, field: str = "") -> object:
        if field in fields and isinstance(value, (str, list)):
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            if writing and encoded in keys:
                return {"source_value_ref": keys[encoded]}
            if not writing and len(encoded.encode()) >= 32:
                counts[encoded] += 1
            return value
        if isinstance(value, list):
            return [visit(item, writing=writing) for item in value]
        if not isinstance(value, dict):
            return value
        literal = {"full_sources", "paragraphs"} | ({"text"} if field == "assertion" else set())
        return {k: v if k in literal
                else visit(v, writing=writing, field=k) for k, v in value.items()}

    visit(payload)
    for encoded, count in counts.items():
        key = f"v{len(values) + 1}"
        # Include the directory entry and every reference before factoring short values.
        if (count - 1) * len(encoded.encode()) <= (
            count * len(f'{{"source_value_ref":"{key}"}}') + len(key) + 4
        ):
            continue
        keys[encoded] = key
        values[key] = json.loads(encoded)
    if not values:
        return payload
    packed = visit(payload, writing=True)
    packed["source_context"]["source_values"] = values
    return packed


def _pack_source_rows(value: object) -> object:
    """Compact uniform arrays and existing references in the scoped wire payload."""
    if isinstance(value, dict):
        keys = set(value)
        if keys == {"$"} or keys == {"field_names", "field_rows"}:
            raise ReviewContractError("review_reserved_source_encoding")
        if keys == {"source_record_ref"}:
            return {"$": value["source_record_ref"]}
        if keys == {"source_value_ref"}:
            return {"$": value["source_value_ref"]}
        return {key: item if key in {"full_sources", "paragraphs"} else _pack_source_rows(item)
                for key, item in value.items()}
    if not isinstance(value, list):
        return value
    rows = [_pack_source_rows(item) for item in value]
    if (len(rows) < 3 or not isinstance(rows[0], dict) or not rows[0]
            or not all(isinstance(row, dict) and row.keys() == rows[0].keys() for row in rows)):
        return rows
    fields = list(rows[0])
    packed = {"field_names": fields,
              "field_rows": [[row[field] for field in fields] for row in rows]}

    def size(item: object) -> int:
        return len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode())

    return packed if size(packed) < size(rows) else rows


def claim_source_bindings(claim: Claim) -> list[dict]:
    """Bind an assertion to selected cells, not to an unversioned reconstructed table."""
    return [{"table_id": p["table"]["table_id"], "cell_ids": p["selected_cell_ids"],
             "binding_sha256": hashlib.sha256(
                 json.dumps(p["table"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
            for context in claim.metadata.get("anchor_resolution", {}).get("evidence_contexts", [])
            if (p := context.get("positioned"))]


def _direct_evidence(claim: Claim) -> dict[str, dict]:
    result = {}
    contexts = claim.metadata.get("anchor_resolution", {}).get("evidence_contexts", [])
    source_bindings = claim_source_bindings(claim)
    for anchor_index, anchor in enumerate(claim.evidence):
        cells = []
        for context in contexts:
            if (context.get("source_url") != anchor.source_url
                    or context.get("quote") != anchor.quote
                    or not (positioned := context.get("positioned"))):
                continue
            table = positioned["table"]
            selected = set(positioned["selected_cell_ids"])
            if not selected or not selected <= {c["cell_id"] for c in table.get("cells", [])}:
                raise ReviewContractError("review_missing_positioned_evidence")
            cells.extend({"table_id": table["table_id"],
                          "physical_page": table.get("physical_page"),
                          "document_sha256": table.get("document_sha256"), "cell": cell}
                         for cell in table.get("cells", [])
                         if cell["cell_id"] in positioned["selected_cell_ids"])
        for binding in cells or [None]:
            value = {"assertion": claim.text, "claim_identity": claim.metadata.get("paper_reading"),
                     "anchor": dataclass_to_dict(anchor),
                     "source_bindings": source_bindings, "positioned_cell": binding}
            identity = "e" + hashlib.sha256(
                json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if binding:
                cell = binding["cell"]
                result[identity] = {"source_url": anchor.source_url, "anchor_index": anchor_index,
                    "table_id": binding["table_id"], "cell_id": cell["cell_id"],
                    "physical_page": binding["physical_page"], "row_headers": cell["row_headers"],
                    "column_headers": cell["column_headers"], "value": cell["value"]}
            else:
                result[identity] = dataclass_to_dict(anchor)
    return result


def _without_bundled_evidence(proofs: dict[str, dict], comparisons: list[str]) -> dict[str, dict]:
    """A complete comparison confirms its exact source context, not independent extra text."""
    def anchor_identity(record: dict) -> tuple | None:
        if record.get("source_contexts"):
            return None  # A caption inside a comparison does not cover its additional context.
        values = [record.get(key) for key in ("source_url", "quote", "location", "source_title")]
        if any(not isinstance(value, str) for value in values) or not all(values[:3]):
            return None
        return values[0], values[1].strip(), values[2], values[3]

    bundled = {identity for ref in comparisons if proofs[ref]["complete"] is True
               for anchor in proofs[ref]["proposal"]["evidence"]
               if (identity := anchor_identity(anchor)) is not None}
    return {ref: proof for ref, proof in proofs.items()
            if (identity := anchor_identity(proof)) is None or identity not in bundled}


class ReviewContractError(AnalysisError):
    """A structured response cannot cover or identify its offered review targets."""

    def __init__(self, code: str, *, detail: str = "", **details: object) -> None:
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"Review contract failed: {code}{suffix}")
        self.diagnostics = {"code": code, **details}


def _object(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def validate_review_response(raw: str, schema: dict) -> dict:
    """Validate our finite response shape locally, including duplicate JSON keys."""

    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReviewContractError("review_duplicate_key", key=key[:100])
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ReviewContractError("review_invalid_json")

    try:
        payload = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ReviewContractError("review_invalid_json") from exc
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        raise ReviewContractError("review_invalid_root")
    decisions = payload["decisions"]
    offered = schema["properties"]["decisions"]["properties"]
    if not isinstance(decisions, dict):
        raise ReviewContractError("review_expected_target_object")
    if set(decisions) != set(offered):
        raise ReviewContractError(
            "review_target_set_mismatch",
            missing=sorted(set(offered) - set(decisions)),
            unexpected=sorted(set(decisions) - set(offered))[:20],
        )
    for key, decision in decisions.items():
        shape = offered[key]["properties"]
        if not isinstance(decision, dict) or set(decision) != set(shape):
            raise ReviewContractError("review_invalid_decision_fields", target_id=key)
        if (
            decision["status"] not in shape["status"]["enum"]
            or not isinstance(decision["reason"], str)
            or not decision["reason"].strip()
        ):
            raise ReviewContractError("review_invalid_decision", target_id=key)
        if "covered_claim_ids" in shape:
            ids = decision["covered_claim_ids"]
            allowed = shape["covered_claim_ids"]["items"]["enum"]
            if (
                not isinstance(ids, list)
                or any(not isinstance(i, str) or i not in allowed for i in ids)
                or len(ids) != len(set(ids))
            ):
                raise ReviewContractError("review_invalid_coverage", target_id=key)
        if "comparison_checks" in shape:
            checks = decision["comparison_checks"]
            allowed = shape["comparison_checks"]["properties"]
            if (not isinstance(checks, dict) or set(checks) != set(allowed)
                    or any(type(value) is not bool for value in checks.values())):
                raise ReviewContractError("review_invalid_comparison_checks", target_id=key)
            if any(value not in allowed[ref].get("enum", [False, True])
                   for ref, value in checks.items()):
                raise ReviewContractError("review_incomplete_comparison_source", target_id=key)
            if decision["status"] == "supported" and not all(checks.values()):
                raise ReviewContractError("review_unconfirmed_comparison", target_id=key)
        if "evidence_ids" in shape:
            ids = decision["evidence_ids"]
            allowed = shape["evidence_ids"]["items"].get("enum", [])
            if (not isinstance(ids, list)
                    or any(not isinstance(i, str) or i not in allowed for i in ids)
                    or len(ids) != len(set(ids))
                    or (allowed and not ids)):
                raise ReviewContractError("review_invalid_evidence", target_id=key)
        if "evidence_selection" in shape:
            selection = decision["evidence_selection"]
            allowed = shape["evidence_selection"]["properties"]
            if (not isinstance(selection, dict) or set(selection) != set(allowed)
                    or any(type(value) is not bool for value in selection.values())):
                raise ReviewContractError("review_invalid_evidence_selection", target_id=key)
            if allowed and decision["status"] == "supported" and not any(selection.values()):
                raise ReviewContractError("review_supported_without_evidence", target_id=key)
        if "evidence_refs" in shape:
            refs = decision["evidence_refs"]
            allowed = shape["evidence_refs"]["items"].get("enum", [])
            if (not isinstance(refs, list)
                    or any(not isinstance(ref, str) or ref not in allowed for ref in refs)
                    or len(refs) != len(set(refs))):
                raise ReviewContractError("review_invalid_evidence_refs", target_id=key)
            if allowed and decision["status"] == "supported" and not refs:
                raise ReviewContractError("review_supported_without_evidence", target_id=key)
    return payload


@dataclass(frozen=True)
class ReviewTargets:
    """One immutable-in-use manifest binds each response key to exactly one offered target."""

    targets: dict[str, dict]
    evidence_bindings: dict[str, dict[str, str]] = field(default_factory=dict)

    def presentation(self, reading_context: str, *, share_source_parts: bool = False) -> dict:
        """Share exact evidence records on input without changing audited targets or decisions."""
        records: dict[str, dict] = {}
        references: dict[str, str] = {}

        def record_key(record: dict) -> str:
            try:
                return json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ReviewContractError("review_invalid_source_record") from exc

        def reference(record: object) -> str:
            if not isinstance(record, dict):
                raise ReviewContractError("review_invalid_source_record")
            encoded = record_key(record)
            if encoded not in references:
                identity = f"s{len(records) + 1}"
                references[encoded] = identity
                records[identity] = deepcopy(record)
            return references[encoded]

        def compact(value: object) -> object:
            if isinstance(value, list):
                return [compact(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {}
            for key, item in value.items():
                if key == "evidence" and isinstance(item, list):
                    result[key] = [reference(record) for record in item]
                elif key == "direct_evidence" and isinstance(item, dict):
                    result[key] = {choice: reference(record) for choice, record in item.items()}
                else:
                    result[key] = compact(item)
            return result

        context = compact(json.loads(reading_context) if reading_context else {})
        targets = compact(self.targets)
        if share_source_parts:
            # Only exact projections may borrow table fields. Role-specific fields stay inline.
            tables = context.get("table_sources", {})
            cell_fields = ("cell_id", "row_headers", "column_headers", "value")
            scope_fields = ("table_id", "source_url", "source_text_sha256",
                            "document_sha256", "physical_page")
            span_fields = ("source_text_sha256", "start", "end")
            cells = {}
            aliases = {}
            for table_id, table in tables.items():
                if not all(k in table for k in scope_fields) or table["table_id"] != table_id:
                    continue
                for cell in table.get("cells", []):
                    if all(k in cell for k in cell_fields):
                        key = (table_id, cell["cell_id"])
                        cells[key] = cell if key not in cells else None

            def source_parts(value: object, table_id: str | None = None) -> object:
                if isinstance(value, list):
                    return [source_parts(item, table_id) for item in value]
                if not isinstance(value, dict):
                    return value
                table_id = value.get("table_id", table_id)
                cell = cells.get((table_id, value.get("cell_id")))
                if cell is not None and all(value.get(k) == cell[k] for k in cell_fields):
                    table = tables[table_id]
                    if all(value[k] == table[k] for k in scope_fields if k in value):
                        alias = aliases.setdefault(table_id, f"t{len(aliases) + 1}")
                        shared = set(cell_fields)
                        scoped = all(k in value for k in scope_fields)
                        if scoped:
                            shared.update(scope_fields)
                        return {"cell_ref": [alias, cell["cell_id"]],
                                **({"table_scope": True} if scoped else {}),
                                **{k: source_parts(v, table_id) for k, v in value.items()
                                   if k not in shared}}
                literal = "text" if "text" in value else "quote"
                if (isinstance(value.get(literal), str) and all(k in value for k in span_fields)
                        and isinstance(value["source_text_sha256"], str)
                        and type(value["start"]) is type(value["end"]) is int):
                    span = {k: value[k] for k in span_fields} | {"literal": value[literal]}
                    return {"span_ref": reference(span),
                            **({"span_literal": "quote"} if literal == "quote" else {}),
                            **{k: source_parts(v, table_id) for k, v in value.items()
                               if k not in span_fields and k != literal}}
                return {k: v if k == "table_sources" else source_parts(v, table_id)
                        for k, v in value.items()}

            for identity, record in list(records.items()):
                records[identity] = source_parts(record)
            context = source_parts(context)
            targets = source_parts(targets)
            if aliases:
                context["table_aliases"] = {alias: table_id for table_id, alias in aliases.items()}
        for target in targets.values():
            if target["kind"] in ("fact", "paragraph"):
                if "assertion" in target or not isinstance(target.get("text"), str):
                    raise ReviewContractError("review_invalid_target_assertion")
                target["assertion"] = {"text": target.pop("text")}

        # Cells, bound spans and experiment assertions recur inside otherwise distinct proofs.
        # Factor exact records only when the reference is materially shorter than the record.
        counts: Counter[str] = Counter()
        inline = {"assertion", "direct_evidence"}

        def count_nested(value: object, *, root: bool = False) -> None:
            if isinstance(value, list):
                for item in value:
                    count_nested(item)
            elif isinstance(value, dict):
                if set(value) == {"source_record_ref"}:
                    raise ReviewContractError("review_invalid_source_record")
                if not root:
                    encoded = record_key(value)
                    if len(encoded.encode()) >= 160:
                        counts[encoded] += 1
                for key, item in value.items():
                    count_nested(item, root=key in inline)

        original_records = list(records.items())
        for root in [context, *targets.values(), *records.values()]:
            count_nested(root, root=True)
        factored_records: dict[str, dict] = {}

        def factor(value: object, *, root: bool = False) -> object:
            if isinstance(value, list):
                return [factor(item) for item in value]
            if not isinstance(value, dict):
                return value
            if not root and counts[record_key(value)] > 1:
                identity = reference(value)
                if identity not in factored_records:
                    factored_records[identity] = factor_record(value)
                return {"source_record_ref": identity}
            return factor_record(value)

        def factor_record(record: dict) -> dict:
            return {key: factor(item, root=key in inline) for key, item in record.items()}

        context = factor_record(context)
        targets = {key: factor_record(target) for key, target in targets.items()}
        for identity, record in original_records:
            if identity not in factored_records:
                factored_records[identity] = factor_record(record)
        payload = {"source_context": context, "targets": targets,
                   "source_records": factored_records}
        return _pack_source_rows(_share_source_values(payload)) if share_source_parts else payload

    @property
    def schema(self) -> dict:
        """Require every offered target, with no free-form response identity fields."""
        properties = {}
        for key, target in self.targets.items():
            statuses = ["supported", "unsupported", "needs_review"]
            if target.get("blocked_claim_ids"):
                statuses.remove("supported")
            if target["kind"] in ("fact", "paragraph"):
                statuses.append("speculative")
            units = target.get("comparison_units", [])
            if any(not target["direct_evidence"][ref]["complete"] for ref in units):
                statuses.remove("supported")
            fields = {
                "status": {"type": "string", "enum": statuses},
                "reason": {"type": "string", "minLength": 1},
            }
            if target["kind"] == "paragraph":
                fields["covered_claim_ids"] = {
                    "type": "array",
                    "items": {"type": "string", "enum": target["supporting_claim_ids"]},
                }
            if "direct_evidence" in target:
                identities = [ref for ref in target["direct_evidence"] if ref not in units]
                if self.evidence_bindings:
                    fields["evidence_refs"] = {"type": "array", "items":
                        {"type": "string", "enum": identities} if identities
                        else {"type": "string"}, "maxItems": len(identities)}
                else:
                    fields["evidence_ids"] = {"type": "array", "items":
                        {"type": "string", "enum": identities} if identities
                        else {"type": "string"}, "minItems": 1 if identities else 0,
                        **({} if identities else {"maxItems": 0})}
            if units:
                fields["comparison_checks"] = _object({ref: (
                    {"type": "boolean"} if target["direct_evidence"][ref]["complete"]
                    else {"type": "boolean", "enum": [False]}) for ref in units})
            properties[key] = _object(fields)
        identity = (COMPARISON_SCHEMA_ID if any(t.get("comparison_units")
                                               for t in self.targets.values())
                    else REVIEW_SCHEMA_ID if self.evidence_bindings else LEGACY_EVIDENCE_SCHEMA_ID
                    if any("direct_evidence" in t for t in self.targets.values())
                    else "urn:research-radar:review-targets:v1")
        return {"$id": identity, **_object({"decisions": _object(properties)})}

    def validate(self, raw: str) -> dict:
        """Check response shape and the coverage obligations of the exact offered targets."""
        payload = validate_review_response(raw, self.schema)
        for key, target in self.targets.items():
            required = target.get("required_covered_claim_ids")
            decision = payload["decisions"][key]
            if required and decision["status"] == "supported":
                if missing := sorted(set(required).difference(decision["covered_claim_ids"])):
                    paragraph = target["paragraph_id"]
                    raise ReviewContractError("review_incomplete_paragraph_coverage",
                        detail=f"{paragraph} missing {', '.join(missing)}",
                        target_id=key, paragraph_id=paragraph,
                        missing_claim_ids=missing)
        return payload

    def normalize(self, raw: str) -> str:
        """Adapt explicit targets to existing review consumers, preserving exact raw output."""
        result = self._normalized_payload(self.validate(raw))
        result["structured_review"]["raw_response"] = raw
        return json.dumps(result, ensure_ascii=False)

    def select(self, identities: set[str]) -> ReviewTargets:
        """Select explicit targets without renumbering their evidence references."""
        if not identities <= self.targets.keys():
            raise ReviewContractError("review_unknown_subset_target")
        return ReviewTargets(
            {k: deepcopy(t) for k, t in self.targets.items() if k in identities},
            {k: deepcopy(b) for k, b in self.evidence_bindings.items() if k in identities},
        )

    def context_for_batch(self, context: dict) -> dict:
        """Keep whole prose and source packets; scope auxiliary evidence by exact dependencies."""
        claim_keys: set[tuple[str, str | None]] = set()
        table_ids: set[str] = set()

        def collect_tables(value: object) -> None:
            if isinstance(value, dict):
                if isinstance(table := value.get("table_id"), str):
                    table_ids.add(table)
                for item in value.values():
                    collect_tables(item)
            elif isinstance(value, list):
                for item in value:
                    collect_tables(item)

        for target in self.targets.values():
            if target["kind"] == "fact":
                claim_keys.update((url, target.get("claim_id")) for url in target["source_urls"])
            else:
                claim_keys.update((target["source_url"], claim["claim_id"])
                                  for claim in target.get("supporting_claims", []))
            collect_tables(target)

        projected = dict(context)
        if "paragraphs" in context:
            # Each offered paragraph already contains its own unabridged supporting claims.
            projected["paragraphs"] = [{k: v for k, v in row.items() if k != "supporting_claims"}
                                       for row in context["paragraphs"]]
        if "text_evidence_contexts" in context:
            projected["text_evidence_contexts"] = [
                row for row in context["text_evidence_contexts"]
                if (row["source_url"], row["claim_id"]) in claim_keys]
        if "experimental_result_proposals" in context:
            experiments = []
            for source in context["experimental_result_proposals"]:
                ids = {result["result_id"] for result in source["results"]
                       if any((source["source_url"], claim) in claim_keys
                              for claim in result["supporting_claim_ids"])}
                if ids:
                    # The original binding digest, observations and comparison scope stay intact.
                    related = {**source,
                               "results": [r for r in source["results"] if r["result_id"] in ids],
                               "bindings": [
                                   {**r, "assertions": [a for a in r["assertions"]
                                    if (source["source_url"], a["claim_id"]) in claim_keys]}
                                   for r in source["bindings"] if r["result_id"] in ids]}
                    collect_tables(related)
                    experiments.append(related)
            projected["experimental_result_proposals"] = experiments
        if "table_sources" in context:
            projected["table_sources"] = {
                key: table for key, table in context["table_sources"].items() if key in table_ids}
        return projected

    def source_affinity(self, context: dict) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
        """Group requests by explicit, source-scoped table and experiment dependencies."""
        projected = self.context_for_batch(context)
        return (tuple(sorted(projected.get("table_sources", {}))),
                tuple(sorted((item["source_url"], result["result_id"])
                             for item in projected.get("experimental_result_proposals", [])
                             for result in item["results"])))

    def _canonical_target(self, identity: str) -> dict:
        target = deepcopy(self.targets[identity])
        target.pop("claim_index", None)
        if set(target.get("direct_evidence", {})) != set(self.evidence_bindings.get(identity, {})):
            raise ReviewContractError("review_invalid_receipt_bindings")
        target["direct_evidence"] = {
            self.evidence_bindings[identity][reference]: value
            for reference, value in target.get("direct_evidence", {}).items()
        }
        if "comparison_units" in target:
            target["comparison_units"] = [self.evidence_bindings[identity][ref]
                                           for ref in target["comparison_units"]]
        encoded = json.dumps(target, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if "t" + hashlib.sha256(encoded.encode()).hexdigest() != identity:
            raise ReviewContractError("review_invalid_receipt_identity")
        return target

    @staticmethod
    def _read_receipt(receipt: dict, *, fresh: bool = False) -> tuple[ReviewTargets, dict]:
        try:
            saved = receipt["structured_review"]
            prior = ReviewTargets(saved["targets"], saved["evidence_bindings"])
            if not fresh and saved["schema_id"] not in {REVIEW_SCHEMA_ID, COMPARISON_SCHEMA_ID}:
                raise ReviewContractError("review_receipt_schema_unsupported")
            raw = saved["raw_response"]
            if json.loads(prior.normalize(raw)) != receipt:
                raise ReviewContractError("review_receipt_changed")
            for identity in prior.targets:
                prior._canonical_target(identity)
            return prior, validate_review_response(raw, prior.schema)["decisions"]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ReviewContractError("review_invalid_receipt") from exc

    def reuse_supported(self, receipt: dict) -> dict[str, dict]:
        """Reuse only exact original approvals; callers must also pin original source bytes."""
        prior, decisions = self._read_receipt(receipt)
        reusable = {}
        for identity in self.targets.keys() & prior.targets.keys():
            if (decisions[identity]["status"] != "supported"
                    or self._canonical_target(identity) != prior._canonical_target(identity)):
                continue
            decision = deepcopy(decisions[identity])
            references = {proof: ref for ref, proof in self.evidence_bindings[identity].items()}
            decision["evidence_refs"] = [references[prior.evidence_bindings[identity][ref]]
                                         for ref in decision["evidence_refs"]]
            if "comparison_checks" in decision:
                decision["comparison_checks"] = {
                    references[prior.evidence_bindings[identity][ref]]: checked
                    for ref, checked in decision["comparison_checks"].items()}
            reusable[identity] = decision
        return reusable

    def assemble(self, previous: dict, fresh: dict | None) -> dict:
        """Derive complete decisions with separate original receipts, not a synthetic reply."""
        if not (self.targets.keys() - self.reuse_supported(previous).keys()) and fresh is not None:
            raise ReviewContractError("review_unexpected_fresh_receipt")
        return self.assemble_batches([fresh] if fresh is not None else [], previous=previous)

    def assemble_batches(self, fresh: list[dict], *, previous: dict | None = None) -> dict:
        """Merge only a complete, disjoint partition of the exact pending targets."""
        decisions = self.reuse_supported(previous) if previous is not None else {}
        reused_ids = sorted(decisions)
        for receipt in fresh:
            received, answers = self._read_receipt(receipt, fresh=True)
            if not answers or answers.keys() & decisions.keys():
                raise ReviewContractError("review_fresh_receipt_target_mismatch")
            expected = self.select(set(answers))
            if (received.targets != expected.targets
                    or received.evidence_bindings != expected.evidence_bindings):
                raise ReviewContractError("review_fresh_receipt_target_mismatch")
            decisions.update(answers)
        payload = self.validate(json.dumps({"decisions": decisions}))
        receipts = [previous, *fresh] if previous is not None else fresh
        result = self._normalized_payload(payload)
        result["structured_review"].update(kind="assembled_receipts", receipts=deepcopy(receipts),
            reused_target_ids=reused_ids)
        return result

    def _normalized_payload(self, payload: dict) -> dict:
        result = {
            key: []
            for key in (
                "decisions",
                "explanation_decisions",
                "method_operation_decisions",
                "method_link_decisions",
                "method_flow_decisions",
            )
        }
        for identity, target in self.targets.items():
            # Keep source citations in the exact raw envelope; existing consumers stay strict.
            decision = {k: v for k, v in payload["decisions"][identity].items()
                        if k not in ("evidence_ids", "evidence_selection", "evidence_refs",
                                     "comparison_checks")}
            kind = target["kind"]
            if kind == "fact":
                result["decisions"].append({"claim_index": target["claim_index"], **decision})
            elif kind == "paragraph":
                result["explanation_decisions"].append(
                    {"paragraph_id": target["paragraph_id"], **decision}
                )
            else:
                keys = {
                    "operation": ("operation_claim_id",),
                    "link": ("from_claim_id", "to_claim_id"),
                    "flow": (),
                }[kind]
                name = {
                    "operation": "method_operation_decisions",
                    "link": "method_link_decisions",
                    "flow": "method_flow_decisions",
                }[kind]
                result[name].append(
                    {
                        "source_url": target["source_url"],
                        **{key: target[key] for key in keys},
                        **decision,
                    }
                )
        result["structured_review"] = {
            "schema_id": self.schema["$id"],
            "targets": self.targets,
            "schema_sha256": hashlib.sha256(
                json.dumps(self.schema, sort_keys=True).encode()
            ).hexdigest(),
        }
        if self.evidence_bindings:
            selected_evidence = {}
            for key, bindings in self.evidence_bindings.items():
                decision = payload["decisions"][key]
                references = [*decision["evidence_refs"],
                    *(ref for ref, checked in decision.get("comparison_checks", {}).items()
                      if checked)]
                selected_evidence[key] = [bindings[ref] for ref in references]
            result["structured_review"].update(
                evidence_bindings=self.evidence_bindings,
                selected_evidence=selected_evidence,
            )
        return result


def build_review_targets(
    claims: list[Claim],
    reading_context: str,
    *,
    method_sources: set[str] | None = None,
    source_claims: list[Claim] | None = None,
) -> ReviewTargets:
    """Generate identities from exact supplied content, never from model reasons or ID suffixes."""
    targets: dict[str, dict] = {}
    fact_evidence: dict[tuple[str, str], tuple[dict, list[str]]] = {}

    catalog = claims if source_claims is None else source_claims

    def source_claim(identity: str, source: str, *, method: bool = False) -> Claim:
        found = [c for c in (catalog if method else claims)
                 if c.metadata.get("paper_reading", {}).get("claim_id") == identity
                 and {a.source_url for a in c.evidence} == {source}]
        if len(found) != 1:
            raise ReviewContractError("review_unavailable_direct_fact", claim_id=identity)
        return found[0]

    def assertion(claim: Claim) -> dict:
        return {"claim_id": claim.metadata.get("paper_reading", {}).get("claim_id"),
                "text": claim.text, "evidence": [dataclass_to_dict(a) for a in claim.evidence],
                "source_bindings": claim_source_bindings(claim), "status": claim.status.value}

    def method_support(identities: set[str], source: str) -> dict:
        records = [source_claim(identity, source, method=True) for identity in sorted(identities)]
        blocked = [c.metadata["paper_reading"]["claim_id"] for c in records
                   if not c.is_publishable()]
        return {"supporting_claims": [assertion(c) for c in records],
                **({"blocked_claim_ids": blocked} if blocked else {})}

    def add(kind: str, value: dict) -> None:
        content = {"kind": kind, **value}
        if kind != "flow" and "direct_evidence" in content and not content["direct_evidence"]:
            raise ReviewContractError("review_missing_direct_evidence", kind=kind)
        # Positions route normalized decisions but do not define the reviewed fact identity.
        binding = {key: item for key, item in content.items() if key != "claim_index"}
        encoded = json.dumps(binding, sort_keys=True, ensure_ascii=False, allow_nan=False)
        identity = "t" + hashlib.sha256(encoded.encode()).hexdigest()
        if identity in targets:
            raise ReviewContractError("review_duplicate_target")
        targets[identity] = content

    context = json.loads(reading_context) if reading_context else {}
    for index, claim in enumerate(claims, 1):
        experiments = []
        proofs = _direct_evidence(claim)
        comparisons = []
        grouped_tables = set()
        for source in context.get("experimental_result_proposals", []):
            if {a.source_url for a in claim.evidence} != {source["source_url"]}:
                continue
            for record in source.get("bindings", []):
                for binding in record["assertions"]:
                    identity = claim.metadata.get("paper_reading", {}).get("claim_id")
                    if binding["claim_id"] != identity:
                        continue
                    if binding.get("assertion_sha256") != experimental_assertion_identity(claim):
                        raise AnalysisError(
                            "Experimental review assertion changed or is ambiguous.")
                    experiments.append({"result_id": record["result_id"],
                        "binding_sha256": record["binding_sha256"], "assertion": binding})
                    proposals = [p for p in source.get("results", [])
                                 if p["result_id"] == record["result_id"]]
                    if (len(proposals) == 1 and proposals[0]["source_kind"] == "table"
                            and not binding.get("cells")
                            and any(value.get("table_id") for value in proofs.values())):
                        unit = table_comparison_unit(claim, proposals[0],
                                                     record["source_evidence"]["cells"])
                        encoded = json.dumps({"assertion": binding["assertion_sha256"],
                            "unit": unit}, sort_keys=True, ensure_ascii=False).encode()
                        reference = "e" + hashlib.sha256(encoded).hexdigest()
                        proofs[reference] = unit
                        comparisons.append(reference)
                        grouped_tables.update(t["table_id"] for t in unit["tables"])
                    for cell in binding.get("cells", []):
                        encoded = json.dumps({"assertion": binding["assertion_sha256"],
                            "cell": cell}, sort_keys=True, ensure_ascii=False).encode()
                        proofs["e" + hashlib.sha256(encoded).hexdigest()] = cell
        proofs = {ref: value for ref, value in proofs.items()
                  if value.get("table_id") not in grouped_tables}
        proofs = _without_bundled_evidence(proofs, comparisons)
        for proof in proofs.values():
            attached = [record["context"] for record in context.get("text_evidence_contexts", [])
                if record["claim_id"] == claim.metadata.get("paper_reading", {}).get("claim_id")
                and record["claim_text"] == claim.text
                and record["source_url"] == proof.get("source_url")
                and record["quote"] == proof.get("quote")
                and record["anchor_location"] == proof.get("location")]
            if attached:
                proof["source_contexts"] = attached
        identity = claim.metadata.get("paper_reading", {}).get("claim_id")
        for url in {e.source_url for e in claim.evidence}:
            fact_evidence[(url, identity)] = (proofs, comparisons)
        add(
            "fact",
            {
                "claim_index": index,
                "claim_id": claim.metadata.get("paper_reading", {}).get("claim_id"),
                "source_urls": sorted({a.source_url for a in claim.evidence}),
                "text": claim.text,
                "evidence": [dataclass_to_dict(a) for a in claim.evidence],
                "original_text": claim.metadata.get("localization", {}).get("original_text"),
                "direct_evidence": proofs,
                **({"experimental_results": experiments} if experiments else {}),
                **({"comparison_units": comparisons} if comparisons else {}),
            },
        )
    for paragraph in context.get("paragraphs", []):
        if not paragraph["supporting_claim_ids"]:
            raise ReviewContractError("review_paragraph_has_no_support")
        proofs = {}
        comparisons = []
        for identity in paragraph["supporting_claim_ids"]:
            source_claim(identity, paragraph["source_url"])
            fact_proofs, units = fact_evidence[(paragraph["source_url"], identity)]
            proofs.update(fact_proofs)
            comparisons.extend(ref for ref in units if ref not in comparisons)
        add("paragraph", {**paragraph,
                           "direct_evidence": _without_bundled_evidence(proofs, comparisons),
                           **({"comparison_units": comparisons} if comparisons else {})})
    for flow in context.get("method_flow_proposals", []):
        source = flow["source_url"]
        if method_sources is not None and source not in method_sources:
            continue
        if "operations" in flow:
            for operation in flow["operations"]:
                own = source_claim(operation["operation_claim_id"], source, method=True)
                ids = {operation["operation_claim_id"]} | {
                    identity for role in ("inputs", "outputs", "conditions")
                    for value in operation[role] for identity in value["supporting_claim_ids"]}
                add("operation", {"source_url": source, **operation,
                    "assertion": assertion(own), **method_support(ids, source),
                    "direct_evidence": _direct_evidence(own)})
        elif any(
            flow.get(key) for key in ("input_claim_ids", "step_claim_ids", "output_claim_ids")
        ):
            proofs = {}
            ids = {identity for role in ("input_claim_ids", "step_claim_ids", "output_claim_ids")
                   for identity in flow[role]}
            for identity in sorted(ids):
                proofs.update(_direct_evidence(source_claim(identity, source, method=True)))
            add("flow", {**flow, **method_support(ids, source), "direct_evidence": proofs})
        for link in flow["links"]:
            if "relation_claim_id" not in link:
                ids = {link["from_claim_id"], link["to_claim_id"], *link["supporting_claim_ids"]}
                add("link", {"source_url": source, **link, **method_support(ids, source)})
                continue
            own = source_claim(link["relation_claim_id"], source, method=True)
            ids = {link["from_claim_id"], link["to_claim_id"], link["relation_claim_id"]}
            add("link", {"source_url": source, **link, "assertion": assertion(own),
                         **method_support(ids, source), "direct_evidence": _direct_evidence(own)})
    # Short request-local choices never replace the content-bound identities used for audit.
    references = {identity: f"e{index}" for index, identity in enumerate(sorted({
        identity for target in targets.values() for identity in target.get("direct_evidence", {})
    }), 1)}
    bindings = {}
    for key, target in targets.items():
        if "direct_evidence" in target:
            proofs = target["direct_evidence"]
            bindings[key] = {references[identity]: identity for identity in proofs}
            target["direct_evidence"] = {references[identity]: value
                                         for identity, value in proofs.items()}
            if "comparison_units" in target:
                target["comparison_units"] = [references[identity]
                                               for identity in target["comparison_units"]]
    return ReviewTargets(targets, bindings)
