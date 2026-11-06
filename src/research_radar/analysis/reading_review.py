"""Bind paragraph decisions to exact prose, source identity and verified support."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, replace
from pathlib import Path

from research_radar.analysis.experimental_results import bind_experimental_results
from research_radar.analysis.method_flow import (
    method_claim_ids,
    method_flow_payload,
    method_narrative_scope,
)
from research_radar.analysis.paper_reading import (
    EvaluationContext,
    PaperReading,
    ParagraphReview,
    ReaderExplanation,
    ReaderExplanationParagraph,
    evaluation_context_payload,
)
from research_radar.analysis.paper_sections import (
    PaperReadingPacket,
    build_reading_packet,
    render_reading_packet,
)
from research_radar.analysis.review_targets import claim_source_bindings
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, Claim, dataclass_to_dict

_CONTEXT_SECTIONS = {
    "problem_solution.mechanism": "solution_walkthrough",
    "evaluation_context.available_inputs": "experiment_interpretation",
    "evaluation_context.outcome_measurement": "experiment_interpretation",
}


def context_coverage_requirements(
    claims: list[Claim], *, source_url: str, evaluation_context: EvaluationContext | None = None,
    source_claims: list[Claim] | None = None,
) -> dict[str, list[str]]:
    """Select prose obligations from already fact-reviewed method and evaluation conditions."""
    required: dict[str, list[str]] = {}
    if evaluation_context is not None and evaluation_context.claim_references is not None:
        ids = list(dict.fromkeys(identity for references in
            evaluation_context_payload(evaluation_context).values() for identity in references))
        for identity in ids:
            matches = [c for c in claims if c.metadata.get("paper_reading", {}).get("claim_id")
                       == identity and {a.source_url for a in c.evidence} == {source_url}]
            if len(matches) != 1 or not matches[0].is_publishable():
                catalog = [c for c in source_claims or []
                           if c.metadata.get("paper_reading", {}).get("claim_id") == identity
                           and {a.source_url for a in c.evidence} == {source_url}]
                if (len(catalog) == 1 and not catalog[0].is_publishable()
                        and catalog[0].metadata.get("anchor_resolution", {}).get("status")
                        in {"failed", "needs_review"}
                        and not any(k in catalog[0].metadata
                                    for k in ("model_review", "fact_review"))):
                    continue  # A proposed condition is not an approved positive statement.
                raise AnalysisError(
                    "Evaluation context has unavailable or ambiguous factual support.")
        approved = {c.metadata.get("paper_reading", {}).get("claim_id") for c in claims
                    if c.is_publishable() and {a.source_url for a in c.evidence} == {source_url}}
        if any(references and not approved.intersection(references)
               for references in evaluation_context.claim_references.values()):
            raise AnalysisError("Evaluation context has no approved support for a declared role.")
        ids = [identity for identity in ids if identity in approved]
        return {"experiment_interpretation": ids} if ids else {}
    for claim in claims:
        identity = claim.metadata.get("paper_reading", {})
        section = _CONTEXT_SECTIONS.get(identity.get("context_field"))
        if (not section or identity.get("source") != "reading_context"
                or not claim.is_publishable()
                or {a.source_url for a in claim.evidence} != {source_url}):
            continue
        claim_id = identity.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise AnalysisError("Context coverage requires an explicit claim identity.")
        required.setdefault(section, []).append(claim_id)
    return required


def uncovered_context(
    required: dict[str, list[str]], paragraphs: dict[str, list[ReaderExplanationParagraph]],
) -> dict[str, list[str]]:
    """Compare explicit references in the relevant prose, not in its separate fact ledger."""
    missing = {}
    for section, ids in required.items():
        # Setup/measurement may be explained with the method; never force repeated prose.
        locations = (("solution_walkthrough", "experiment_interpretation")
                     if section == "experiment_interpretation" else (section,))
        present = {identity for location in locations for p in paragraphs.get(location, [])
                   for identity in p.supporting_claim_ids}
        if absent := [identity for identity in ids if identity not in present]:
            missing[section] = absent
    return missing


def publication_coverage_requirements(
    claims: list[Claim], reading: PaperReading, *, source_claims: list[Claim] | None = None,
) -> dict[str, list[str]]:
    """Index already reviewed method, setup and declared results once for writing and review."""
    required = context_coverage_requirements(claims, source_url=reading.source_url,
        evaluation_context=reading.evaluation_context, source_claims=source_claims)
    if method_ids := method_claim_ids(reading.method_flow):
        required.setdefault("solution_walkthrough", []).extend(method_ids)
    catalog = claims if source_claims is None else source_claims
    for result in reading.experimental_results:
        for identity in result.supporting_claim_ids:
            same_source = [c for c in catalog
                if c.metadata.get("paper_reading", {}).get("claim_id") == identity
                and {e.source_url for e in c.evidence} == {reading.source_url}]
            approved = [c for c in claims
                if c.metadata.get("paper_reading", {}).get("claim_id") == identity
                and {e.source_url for e in c.evidence} == {reading.source_url}
                and c.is_publishable()]
            if len(same_source) != 1 or len(approved) > 1:
                raise AnalysisError(
                    "Experimental result has unavailable or ambiguous factual support.")
            if approved:
                required.setdefault("experiment_interpretation", []).append(identity)
    return {section: list(dict.fromkeys(ids)) for section, ids in required.items()}


@dataclass(frozen=True)
class ReadingReviewInput:
    """Canonical review context plus the original packets for scoped presentation."""

    context: str
    packets: dict[str, PaperReadingPacket]


def build_reading_review_context(
    readings: list[PaperReading], claims: list[Claim], artifacts: list[Artifact],
    *, required_coverage: dict[str, dict[str, list[str]]] | None = None,
    source_claims: list[Claim] | None = None,
) -> tuple[str, set[str]]:
    """Return the canonical context and source identities for review."""
    inputs = build_reading_review_input(readings, claims, artifacts,
        required_coverage=required_coverage, source_claims=source_claims)
    return inputs.context, set(inputs.packets)


def build_reading_review_input(
    readings: list[PaperReading], claims: list[Claim], artifacts: list[Artifact],
    *, required_coverage: dict[str, dict[str, list[str]]] | None = None,
    source_claims: list[Claim] | None = None,
) -> ReadingReviewInput:
    """Supply complete source-addressed text, not another truncated evidence selection."""
    sources: dict[str, Artifact] = {}
    wanted = {r.source_url for r in readings} | {a.source_url for c in claims for a in c.evidence}
    for artifact in artifacts:
        url = artifact.source.url
        if url not in wanted or not artifact.text.strip():
            continue
        if url in sources and sources[url].text != artifact.text:
            raise AnalysisError("Conflicting full texts for one verifier source identity.")
        sources[url] = artifact
    packets = {url: build_reading_packet(artifact) for url, artifact in sources.items()}
    table_sources = {t["table_id"]: t for artifact in sources.values()
                     for t in artifact.metadata.get("table_evidence", [])}
    for claim in claims:
        for evidence_context in claim.metadata.get("anchor_resolution", {}).get(
            "evidence_contexts", []
        ):
            if not (positioned := evidence_context.get("positioned")):
                continue
            table = positioned["table"]
            identity = table["table_id"]
            if identity in table_sources and table_sources[identity] != table:
                raise AnalysisError("Conflicting positioned source for one table identity.")
            table_sources[identity] = table
    catalog = claims if source_claims is None else source_claims
    review_positions = {id(claim): i for i, claim in enumerate(claims, 1)}
    context = {
        "table_sources": table_sources,
        "text_evidence_contexts": _matched_text_contexts(claims, sources),
        "paragraphs": explanation_review_items(
            readings, claims, required_coverage=required_coverage),
        "required_coverage": required_coverage or {},
        "method_flow_proposals": [{"source_url": r.source_url,
            **method_flow_payload(r.method_flow),
            "narrative_scope": method_narrative_scope(r.method_flow),
            "supporting_claims": [{
                "claim_id": c.metadata["paper_reading"]["claim_id"],
                "claim_index": review_positions.get(id(c)), "text": c.text,
                "status": c.status.value,
            } for c in catalog
                if c.metadata.get("paper_reading", {}).get("claim_id")
                in method_claim_ids(r.method_flow)
                and {a.source_url for a in c.evidence} == {r.source_url}],
        } for r in readings],
        "evaluation_context_proposals": [{
            "source_url": r.source_url,
            "conditions": evaluation_context_payload(r.evaluation_context),
            "unavailable_claim_ids": [identity
                for ids in (r.evaluation_context.claim_references or {}).values()
                for identity in ids
                if any(c.metadata.get("paper_reading", {}).get("claim_id") == identity
                       and {e.source_url for e in c.evidence} == {r.source_url}
                       and not c.is_publishable() for c in catalog)],
        } for r in readings],
        "experimental_result_proposals": [{
            "source_url": r.source_url, "visual_input": "not_supplied",
            "results": [dataclass_to_dict(item) for item in r.experimental_results],
            "bindings": [{"result_id": record["proposal"]["result_id"],
                          **{key: value for key, value in record.items() if key != "proposal"}}
                         for record in bind_experimental_results(
                             r.experimental_results, sources[r.source_url], catalog)]
                        if r.source_url in sources else [],
        } for r in readings],
        "full_sources": [{"source_url": url,
                          "text_sha256": hashlib.sha256(a.text.encode()).hexdigest(),
                          "original_document": _document_provenance(a),
                          "reading_packet": render_reading_packet(packets[url])}
                         for url, a in sources.items()],
    }
    return ReadingReviewInput(json.dumps(context, ensure_ascii=False), packets)


def _matched_text_contexts(claims: list[Claim], sources: dict[str, Artifact]) -> list[dict]:
    """Keep existing literal context only, without retrieving evidence for missing premises."""
    result = []
    for claim in claims:
        resolution = claim.metadata.get("anchor_resolution", {})
        if resolution.get("status") != "matched":
            continue
        for anchor in claim.evidence:
            source = sources.get(anchor.source_url)
            if source is None:
                continue
            for context in resolution.get("evidence_contexts", []):
                text = context.get("text")
                if (context.get("source_url") != anchor.source_url
                        or context.get("quote") != anchor.quote or context.get("positioned")
                        or not isinstance(text, str) or not text.strip()
                        or not anchor.quote or anchor.quote not in text):
                    continue
                start = source.text.find(text)
                if start < 0 or source.text.find(text, start + 1) >= 0:
                    continue  # Unverified or ambiguous context cannot become selectable proof.
                record = {"claim_id": claim.metadata.get("paper_reading", {}).get("claim_id"),
                    "claim_text": claim.text, "source_url": anchor.source_url,
                    "quote": anchor.quote, "anchor_location": anchor.location,
                    "context": {"text": text,
                        "source_text_sha256": hashlib.sha256(source.text.encode()).hexdigest(),
                        "start": start, "end": start + len(text)}}
                if record not in result:
                    result.append(record)
    return result


def _document_provenance(artifact: Artifact) -> dict[str, object]:
    """Identify the saved original without disclosing its path or implying vision input."""
    record: dict[str, object] = {"visual_input": "not_supplied", "sha256": None}
    if artifact.content_type != "application/pdf" or not artifact.artifact_path:
        return record
    path = Path(artifact.artifact_path)
    if not path.is_file():
        return record
    try:
        with path.open("rb") as stream:
            record["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        record["status"] = "unreadable"
    return record


def paragraph_binding(
    paragraph: ReaderExplanationParagraph, claims: list[Claim], source_url: str,
) -> str | None:
    """Return a digest only for unique, same-paper support with explicit approval."""
    ids = paragraph.supporting_claim_ids
    if not source_url or not ids or len(set(ids)) != len(ids):
        return None
    supporting = []
    for claim_id in ids:
        matches = [claim for claim in claims
                   if claim.metadata.get("paper_reading", {}).get("claim_id") == claim_id
                   and {anchor.source_url for anchor in claim.evidence} == {source_url}]
        if len(matches) != 1:
            return None
        claim = matches[0]
        if (not claim.is_publishable()
                or claim.metadata.get("model_review", {}).get("status") != "supported"
                or claim.metadata.get("model_review", {}).get("requested_status") != "supported"):
            return None
        supporting.append(dataclass_to_dict(claim))
    encoded = json.dumps({"text": paragraph.text, "ids": ids, "source_url": source_url,
                          "claims": supporting}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def paragraph_is_public(
    paragraph: ReaderExplanationParagraph, claims: list[Claim], *, source_url: str,
) -> bool:
    """Recheck the binding at composition, including after translation or downgrades."""
    review = paragraph.review
    return bool(
        review and source_url and review.source_url == source_url
        and review.status == "supported" and review.binding_sha256
        and review.binding_sha256 == paragraph_binding(paragraph, claims, review.source_url)
    )


def _required_paragraph_coverage(
    required: dict[str, list[str]], section: str, supporting_ids: list[str],
) -> set[str]:
    expected = set(required.get(section, []))
    if section == "solution_walkthrough":
        expected.update(required.get("experiment_interpretation", []))
    return expected.intersection(supporting_ids)


def explanation_review_items(
    readings: list[PaperReading], claims: list[Claim], *,
    required_coverage: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict]:
    """Bind each exact paragraph to source-scoped IDs and request-local review positions."""
    result = []
    for paper_index, reading in enumerate(readings, 1):
        required = (required_coverage or {}).get(reading.source_url, {})
        for section in fields(ReaderExplanation):
            for index, paragraph in enumerate(getattr(reading.reader_explanation, section.name), 1):
                expected = _required_paragraph_coverage(
                    required, section.name, paragraph.supporting_claim_ids)
                result.append({
                    "paragraph_id": f"p{paper_index}.{section.name}.{index}",
                    "source_url": reading.source_url, "text": paragraph.text,
                    "supporting_claim_ids": paragraph.supporting_claim_ids,
                    **({"required_covered_claim_ids": sorted(expected)} if expected else {}),
                    "supporting_claims": [{
                        "claim_id": claim.metadata["paper_reading"]["claim_id"],
                        "claim_index": i, "source_url": reading.source_url, "text": claim.text,
                        "evidence": [dataclass_to_dict(a) for a in claim.evidence],
                        "source_bindings": claim_source_bindings(claim),
                    } for i, claim in enumerate(claims, 1)
                        if claim.metadata.get("paper_reading", {}).get("claim_id")
                        in paragraph.supporting_claim_ids
                        and {a.source_url for a in claim.evidence} == {reading.source_url}],
                })
    return result


def apply_explanation_decisions(
    readings: list[PaperReading], claims: list[Claim], payload: object,
    *, source_urls: set[str], required_coverage: dict[str, dict[str, list[str]]] | None = None,
) -> list[PaperReading]:
    """Retain every original paragraph; missing or ambiguous decisions cannot approve it."""
    items = explanation_review_items(readings, claims)
    known = {item["paragraph_id"] for item in items}
    decisions = payload.get("explanation_decisions", []) if isinstance(payload, dict) else []
    valid_envelope = isinstance(decisions, list) and all(
        isinstance(item, dict) and isinstance(item.get("paragraph_id"), str)
        and item["paragraph_id"] in known for item in decisions
    )
    by_id: dict[str, list[dict]] = {}
    if valid_envelope:
        for item in decisions:
            by_id.setdefault(item["paragraph_id"], []).append(item)
    reviewed = []
    for paper_index, reading in enumerate(readings, 1):
        sections = {}
        for section in fields(ReaderExplanation):
            paragraphs = []
            for index, paragraph in enumerate(getattr(reading.reader_explanation, section.name), 1):
                candidates = by_id.get(f"p{paper_index}.{section.name}.{index}", [])
                decision = candidates[0] if len(candidates) == 1 else {}
                status = decision.get("status")
                reason = decision.get("reason")
                valid = (status in ("supported", "unsupported", "needs_review", "speculative")
                         and isinstance(reason, str) and bool(reason.strip()))
                required = (required_coverage or {}).get(reading.source_url, {})
                expected = _required_paragraph_coverage(
                    required, section.name, paragraph.supporting_claim_ids)
                if valid and status == "supported" and expected:
                    covered = decision.get("covered_claim_ids")
                    if (not isinstance(covered, list)
                            or any(not isinstance(identity, str) for identity in covered)
                            or len(set(covered)) != len(covered)
                            or not expected.issubset(covered)
                            or not set(covered).issubset(paragraph.supporting_claim_ids)):
                        status = "needs_review"
                        reason = "Required context coverage was not explicitly confirmed."
                binding = (paragraph_binding(paragraph, claims, reading.source_url)
                           if valid and reading.source_url in source_urls else None)
                if valid and status == "supported" and binding is None:
                    status = "needs_review"
                    reason = (f"{reason} Publication blocked: supporting facts or the exact source "
                              "binding are not approved.")
                paragraphs.append(replace(paragraph, review=ParagraphReview(
                    status=status if valid else "needs_review",
                    reason=reason if valid else "Missing or invalid paragraph review decision.",
                    source_url=reading.source_url, binding_sha256=binding or "",
                )))
            sections[section.name] = paragraphs
        reviewed.append(replace(reading, reader_explanation=ReaderExplanation(**sections)))
    return reviewed
