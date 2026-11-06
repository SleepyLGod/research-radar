"""Deterministic evidence anchor resolution and quote-only repair."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace

from research_radar.analysis.providers import LLMProvider, Message
from research_radar.analysis.source_references import SourceReferenceError, selected_source_unit
from research_radar.evidence.pdf_tables import quoted_table_context
from research_radar.evidence.quotes import QuoteMatch, find_quote
from research_radar.evidence.tables import numeric_row, table_source_context
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    ReviewFinding,
    dataclass_to_dict,
)

_CONTEXT_BOUNDARY = re.compile(
    r"^(?:\[page \d+\]$|\d+(?:\.\d+)*[.)]?\s+[A-Z]|(?:Table|Figure)\s+\d+\s*[:.])"
)
_CONTEXT_LIMIT = 1200
_RETRIEVAL_SET = re.compile(
    r"\bK\s*(?:∈|=)\s*\{\s*([1-9]\d*(?:\s*,\s*[1-9]\d*)*)\s*\}", re.IGNORECASE,
)
_RETRIEVAL_SCALAR = re.compile(
    r"\b(?:top[-‑–— ]|K\s*=\s*)([1-9]\d*)(?!\d|\.\d)", re.IGNORECASE,
)
_METRIC_CUTOFF = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z][A-Za-z0-9_-]*)"
    r"(?P<separator>@|[ \t]+at[ \t]+)(?P<cutoff>\d+)(?!\w|\.\d)", re.IGNORECASE,
)


@dataclass(frozen=True)
class _AnchorIssue:
    reason: str
    reviewable: bool = False


def _candidate_binding(claim: Claim) -> str:
    return hashlib.sha256(json.dumps({"text": claim.text, "status": claim.status.value,
        "evidence": [dataclass_to_dict(e) for e in claim.evidence],
        "identity": claim.metadata.get("paper_reading"),
        "resolution": claim.metadata.get("anchor_resolution")},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def is_evidence_review_candidate(claim: Claim, artifact: Artifact) -> bool:
    """Admit only a fresh local ambiguity, bound to unchanged source and assertion bytes."""
    marker = claim.metadata.get("evidence_review_candidate", {})
    return (claim.status == ClaimStatus.NEEDS_REVIEW
        and not any(key in claim.metadata for key in ("model_review", "fact_review"))
        and marker.get("code") in {"table_semantics", "reader_proposal"}
        and marker.get("binding_sha256") == _candidate_binding(claim)
        and marker.get("source_url") == artifact.source.url
        and marker.get("source_text_sha256") == hashlib.sha256(artifact.text.encode()).hexdigest()
        and bool(claim.evidence)
        and all(e.source_url == artifact.source.url
                and find_quote(e.quote, artifact.text) is not None for e in claim.evidence))


@dataclass(frozen=True)
class AnchorResolution:
    """Resolution status for one claim evidence anchor."""

    claim_index: int
    claim_text: str
    status: str
    reason: str
    quote: str | None = None
    resolved_quote: str | None = None
    location: str | None = None
    page: int | None = None
    table: dict[str, object] | None = None


@dataclass(frozen=True)
class AnchorRepairAttempt:
    """Audit record for one quote-only repair attempt."""

    claim_index: int
    claim_text: str
    status: str
    reason: str
    quote: str | None = None
    location: str | None = None
    page: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


def resolve_quote(
    quote: str, artifact: Artifact, *, location: str | None = None,
) -> AnchorResolution:
    """Resolve a quote against an artifact without semantic fuzzy matching."""

    quote = quote.strip()
    try:
        unit = selected_source_unit(artifact, quote, location)
    except SourceReferenceError as exc:
        return AnchorResolution(0, "", "failed", f"invalid source selection: {exc}", quote=quote)
    if not quote:
        return AnchorResolution(0, "", "failed", "empty quote", quote=quote)
    if unit is None:
        match = find_quote(quote, artifact.text)
    else:
        original = artifact.text[unit.start : unit.end]
        start = unit.start + len(original) - len(original.lstrip())
        match = QuoteMatch(start, start + len(quote), "source_block")
    if match is not None:
        result = _quote_resolution(quote, artifact, (match.start, match.end), match.kind)
        if unit is not None:
            result = replace(result, location=f"page {unit.page}", page=unit.page)
        context = "\n".join([result.resolved_quote or quote,
                             *(s["text"] for s in result.table["segments"])]) \
            if result.table else result.resolved_quote or quote
        positioned = quoted_table_context(
            artifact, quote, context, result.page, location=location,
        )
        if positioned:
            table = result.table or {"segments": [], "headers": [], "quoted_rows": [],
                                     "columns": []}
            rows = _positioned_rows(positioned)
            table = {**table, "headers": [" ".join(c["column_headers"])
                                           for c in positioned["table"]["cells"]],
                     "quoted_rows": rows, "columns": [], "positioned": positioned,
                     "binding": "positioned literal cells"}
            result = replace(result, table=table)
        return result
    return AnchorResolution(0, "", "failed", "quote not found", quote=quote)


def resolve_claim_anchors(
    claims: list[Claim],
    artifact: Artifact,
) -> list[AnchorResolution]:
    """Resolve all claim anchors and enforce numeric-anchor checks."""

    resolutions: list[AnchorResolution] = []
    for index, claim in enumerate(claims, start=1):
        if not claim.evidence:
            resolutions.append(
                AnchorResolution(
                    index,
                    claim.text,
                    "failed",
                    "missing evidence",
                )
            )
            continue
        anchor_resolutions = [resolve_quote(anchor.quote, artifact, location=anchor.location)
                              for anchor in claim.evidence]
        failed = [resolution for resolution in anchor_resolutions if resolution.status == "failed"]
        matched = [resolution for resolution in anchor_resolutions if resolution.status != "failed"]
        invalid_selection = next((r for r in failed
                                  if r.reason.startswith("invalid source selection:")), None)
        if invalid_selection is not None:
            resolutions.append(replace(invalid_selection, claim_index=index, claim_text=claim.text))
            continue
        if any(e.source_url != artifact.source.url for e in claim.evidence):
            resolutions.append(AnchorResolution(index, claim.text, "failed",
                                                "anchor source identity mismatch"))
            continue
        if failed and not matched:
            resolutions.append(
                AnchorResolution(
                    index,
                    claim.text,
                    "failed",
                    "all anchors unmatched",
                    quote=claim.evidence[0].quote,
                )
            )
            continue
        if failed:
            first = matched[0]
            resolutions.append(
                AnchorResolution(
                    index,
                    claim.text,
                    "partial",
                    "some anchors unmatched",
                    quote=first.quote,
                    resolved_quote=first.resolved_quote,
                    location=first.location,
                    page=first.page,
                )
            )
            continue
        numeric_failure = _numeric_anchor_failure(claim, matched)
        if numeric_failure is not None:
            first = matched[0]
            resolutions.append(
                AnchorResolution(
                    index,
                    claim.text,
                    "failed",
                    numeric_failure,
                    quote=first.quote,
                    resolved_quote=first.resolved_quote,
                    location=first.location,
                    page=first.page,
                )
            )
            continue
        entity_failure = _key_entity_anchor_failure(claim, matched)
        if entity_failure is not None:
            first = matched[0]
            resolutions.append(
                AnchorResolution(
                    index,
                    claim.text,
                    "needs_review" if entity_failure.reviewable else "failed",
                    entity_failure.reason,
                    quote=first.quote,
                    resolved_quote=first.resolved_quote,
                    location=first.location,
                    page=first.page,
                )
            )
            continue
        first = matched[0]
        resolutions.append(
            AnchorResolution(
                index,
                claim.text,
                "matched",
                first.reason,
                quote=first.quote,
                resolved_quote=first.resolved_quote,
                location=first.location,
                page=first.page,
            )
        )
    return resolutions


def apply_anchor_resolution(
    claims: list[Claim],
    artifact: Artifact,
) -> tuple[list[Claim], list[AnchorResolution], list[ReviewFinding]]:
    """Downgrade claims whose anchors cannot be resolved in the artifact."""

    resolutions = resolve_claim_anchors(claims, artifact)
    checked: list[Claim] = []
    findings: list[ReviewFinding] = []
    for claim, resolution in zip(claims, resolutions, strict=True):
        if resolution.status in {"matched", "needs_review"}:
            contexts = []
            for anchor in claim.evidence:
                resolved = resolve_quote(anchor.quote, artifact, location=anchor.location)
                if (
                    resolved.resolved_quote
                    and (resolved.resolved_quote != anchor.quote or resolved.table)
                    and anchor.source_url == artifact.source.url
                ):
                    context = {
                        "source_url": anchor.source_url,
                        "quote": anchor.quote,
                        "text": resolved.resolved_quote[:_CONTEXT_LIMIT],
                        "location": resolved.location,
                    }
                    if resolved.table:
                        context.update(resolved.table)
                        context["text"] = "\n[separate source excerpt]\n".join(
                            segment["text"] for segment in resolved.table["segments"]
                        )
                    contexts.append(context)
            candidate = replace(
                claim,
                status=ClaimStatus.NEEDS_REVIEW
                    if resolution.status == "needs_review" and claim.is_publishable()
                    else claim.status,
                metadata={
                    **claim.metadata,
                    "anchor_resolution": {
                        "status": resolution.status,
                        "reason": resolution.reason,
                        "evidence_contexts": contexts,
                    },
                },
            )
            proposal = (resolution.status == "matched" and claim.status == ClaimStatus.NEEDS_REVIEW
                        and claim.metadata.get("paper_reading", {}).get("publishable_default")
                        is False)
            table_candidate = resolution.status == "needs_review" and claim.is_publishable()
            if ((table_candidate or proposal)
                    and claim.metadata.get("paper_reading", {}).get("claim_id")
                    and not any(key in claim.metadata for key in ("model_review", "fact_review"))):
                candidate = replace(candidate, metadata={**candidate.metadata,
                    "evidence_review_candidate": {
                        "code": "reader_proposal" if proposal else "table_semantics",
                        "source_url": artifact.source.url,
                        "source_text_sha256": hashlib.sha256(artifact.text.encode()).hexdigest(),
                        "binding_sha256": _candidate_binding(candidate)}})
            checked.append(candidate)
            if resolution.status == "needs_review":
                findings.append(_resolution_finding(resolution, "warning"))
            continue
        if resolution.status == "partial" and claim.is_publishable():
            checked.append(
                replace(
                    claim,
                    status=ClaimStatus.UNSUPPORTED,
                    metadata={
                        **claim.metadata,
                        "anchor_resolution": {
                            "status": resolution.status,
                            "reason": resolution.reason,
                        },
                    },
                )
            )
            findings.append(_resolution_finding(resolution, "error"))
            continue
        if resolution.status == "partial":
            checked.append(claim)
            findings.append(_resolution_finding(resolution, "warning"))
            continue
        if claim.is_publishable():
            checked.append(
                replace(
                    claim,
                    status=ClaimStatus.UNSUPPORTED,
                    metadata={
                        **claim.metadata,
                        "anchor_resolution": {
                            "status": resolution.status,
                            "reason": resolution.reason,
                        },
                    },
                )
            )
            findings.append(_resolution_finding(resolution, "error"))
        elif claim.status == ClaimStatus.NEEDS_REVIEW:
            checked.append(claim)
            findings.append(_resolution_finding(resolution, "warning"))
        else:
            checked.append(claim)
    return checked, resolutions, findings


def apply_anchor_repair(
    claims: list[Claim],
    artifact: Artifact,
    provider: LLMProvider | None,
    *,
    model: str | None,
) -> tuple[list[Claim], list[AnchorResolution], list[AnchorRepairAttempt], list[ReviewFinding]]:
    """Repair missing anchors by asking for exact quotes from the ingested artifact."""

    resolved_claims, resolutions, resolution_findings = apply_anchor_resolution(claims, artifact)
    if provider is None or model is None:
        return resolved_claims, resolutions, [], resolution_findings
    target_indexes: list[int] = []
    attempts: list[AnchorRepairAttempt] = []
    findings: list[ReviewFinding] = []
    for resolution in resolutions:
        if resolution.status not in {"failed", "partial"}:
            continue
        claim = resolved_claims[resolution.claim_index - 1]
        skip_reason = (
            resolution.reason if resolution.reason.startswith("invalid source selection:")
            else _skip_repair_reason(claim)
        )
        if skip_reason is not None:
            attempt = AnchorRepairAttempt(
                resolution.claim_index,
                claim.text,
                "skipped",
                skip_reason,
            )
            attempts.append(attempt)
            findings.append(_repair_finding(attempt, "info"))
            continue
        target_indexes.append(resolution.claim_index)
    if not target_indexes:
        return resolved_claims, resolutions, attempts, [*resolution_findings, *findings]

    payload = _repair_payload(provider, model, resolved_claims, artifact, target_indexes)
    repairs = _parse_repairs(payload)
    repaired = list(resolved_claims)
    seen_attempt_indexes: set[int] = set()
    for repair in repairs:
        index = _repair_index(repair)
        if index not in target_indexes:
            continue
        seen_attempt_indexes.add(index)
        claim = repaired[index - 1]
        quote = str(repair.get("quote") or "").strip()
        location = str(repair.get("location") or "").strip() or None
        if not quote:
            attempt = AnchorRepairAttempt(index, claim.text, "rejected", "empty quote")
            attempts.append(attempt)
            findings.append(_repair_finding(attempt, "warning"))
            continue
        quote_resolution = resolve_quote(quote, artifact, location=location)
        if quote_resolution.status == "failed":
            attempt = AnchorRepairAttempt(
                index,
                claim.text,
                "rejected",
                quote_resolution.reason,
                quote=quote,
                location=location,
            )
            attempts.append(attempt)
            findings.append(_repair_finding(attempt, "warning"))
            continue
        anchor = EvidenceAnchor(
            source_url=artifact.source.url,
            source_title=artifact.source.title,
            quote=(quote if selected_source_unit(artifact, quote, location) is not None
                   else quote_resolution.resolved_quote or quote),
            location=location or quote_resolution.location,
        )
        candidate = replace(
            claim,
            status=_repair_status(claim),
            evidence=[anchor],
            metadata={
                **claim.metadata,
                "anchor_repair": {
                    "status": "accepted",
                    "reason": str(repair.get("reason") or ""),
                },
            },
        )
        numeric_failure = _numeric_anchor_failure(candidate, [quote_resolution])
        if numeric_failure is not None:
            attempt = AnchorRepairAttempt(
                index,
                claim.text,
                "rejected",
                numeric_failure,
                quote=quote,
                location=location,
                page=quote_resolution.page,
            )
            attempts.append(attempt)
            findings.append(_repair_finding(attempt, "warning"))
            continue
        entity_failure = _key_entity_anchor_failure(candidate, [quote_resolution])
        if entity_failure is not None:
            attempt = AnchorRepairAttempt(
                index,
                claim.text,
                "rejected",
                entity_failure.reason,
                quote=quote,
                location=location,
                page=quote_resolution.page,
            )
            attempts.append(attempt)
            findings.append(_repair_finding(attempt, "warning"))
            continue
        repaired[index - 1] = candidate
        attempt = AnchorRepairAttempt(
            index,
            claim.text,
            "accepted",
            str(repair.get("reason") or "exact quote resolved"),
            quote=anchor.quote,
            location=anchor.location,
            page=quote_resolution.page,
        )
        attempts.append(attempt)
        findings.append(_repair_finding(attempt, "info"))
    for index in target_indexes:
        if index in seen_attempt_indexes:
            continue
        claim = repaired[index - 1]
        attempt = AnchorRepairAttempt(index, claim.text, "rejected", "no repair returned")
        attempts.append(attempt)
        findings.append(_repair_finding(attempt, "warning"))

    final_claims, final_resolutions, final_findings = apply_anchor_resolution(repaired, artifact)
    return final_claims, resolutions, attempts, [*findings, *final_findings]


def _repair_payload(
    provider: LLMProvider,
    model: str,
    claims: list[Claim],
    artifact: Artifact,
    target_indexes: list[int],
) -> str:
    prompt_claims = "\n".join(
        f"{index}. {claims[index - 1].text}" for index in target_indexes
    )
    repair_source = _repair_text(
        artifact.text,
        [claims[index - 1] for index in target_indexes],
    )
    messages = [
        Message(role="system", content="You return exact evidence quotes only."),
        Message(
            role="user",
            content=(
                "For each listed claim, find an exact quote from the supplied artifact text. "
                "Do not rewrite the claim. Do not add claims. Do not use outside sources. "
                "Return JSON only: {\"repairs\":[{\"claim_index\":1,\"quote\":\"...\","
                "\"location\":\"page or section\",\"reason\":\"...\"}]}.\n\n"
                f"CLAIMS:\n{prompt_claims}\n\n"
                f"ARTIFACT SOURCE URL: {artifact.source.url}\n\n"
                f"ARTIFACT TEXT:\n{repair_source}"
            ),
        ),
    ]
    return provider.complete(messages, model=model).content


def _parse_repairs(raw: str) -> list[dict[str, object]]:
    payload = _load_json(raw)
    if payload is None:
        return []
    if isinstance(payload, dict):
        repairs = payload.get("repairs", [])
    else:
        repairs = payload
    if not isinstance(repairs, list):
        return []
    return [repair for repair in repairs if isinstance(repair, dict)]


def _load_json(raw: str) -> object | None:
    stripped = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fence is not None:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _repair_index(repair: dict[str, object]) -> int | None:
    value = repair.get("claim_index", repair.get("index"))
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _skip_repair_reason(claim: Claim) -> str | None:
    source = claim.metadata.get("paper_reading", {}).get("source")
    if source == "unsupported_or_rejected_claims":
        return "unsupported or rejected by reader"
    reason = str(claim.metadata.get("paper_reading", {}).get("status_reason") or "")
    if reason.startswith("claim too broad"):
        return reason
    if reason in {
        "not publishable by default",
        "author-reported superlative needs attribution",
        "essence bundles multiple claims",
        "claim requires external verification",
    }:
        return reason
    if reason in {"missing evidence", "supported by supplied evidence"}:
        return None
    if claim.status in {ClaimStatus.NEEDS_REVIEW, ClaimStatus.SPECULATIVE}:
        return f"claim status is {claim.status.value}"
    if claim.status == ClaimStatus.UNSUPPORTED and not claim.evidence:
        return "unsupported claim lacks repairable reader metadata"
    return None


def _repair_status(claim: Claim) -> ClaimStatus:
    reason = str(claim.metadata.get("paper_reading", {}).get("status_reason") or "")
    if reason.startswith("claim too broad"):
        return ClaimStatus.NEEDS_REVIEW
    return ClaimStatus.SUPPORTED


def _resolution_finding(resolution: AnchorResolution, severity: str) -> ReviewFinding:
    return ReviewFinding(
        severity=severity,
        message=f"Anchor resolution {resolution.status}: {resolution.reason}",
        claim_text=resolution.claim_text,
        metadata={
            "kind": "anchor_resolution",
            "status": resolution.status,
            "reason": resolution.reason,
        },
    )


def _repair_finding(attempt: AnchorRepairAttempt, severity: str) -> ReviewFinding:
    return ReviewFinding(
        severity=severity,
        message=f"Anchor repair {attempt.status}: {attempt.reason}",
        claim_text=attempt.claim_text,
        metadata={
            "kind": "anchor_repair",
            "status": attempt.status,
            "reason": attempt.reason,
        },
    )


def _quote_resolution(
    quote: str,
    artifact: Artifact,
    span: tuple[int, int],
    reason: str,
) -> AnchorResolution:
    resolved, table_context = _evidence_window(artifact.text, span[0], span[1])
    table = table_source_context(artifact.text, span[0], span[1], limit=_CONTEXT_LIMIT)
    resolution_reason = f"table {reason}" if table_context else reason
    return AnchorResolution(
        0,
        "",
        "matched",
        resolution_reason,
        quote=quote,
        resolved_quote=resolved,
        location=_page_location(artifact.text, span[0]),
        page=_page_number(artifact.text, span[0]),
        table=table,
    )


def _line_window(
    text: str, start: int, end: int, *, lower: int = 0, upper: int | None = None,
) -> str:
    upper = len(text) if upper is None else upper
    window_start = text.rfind("\n", 0, start)
    window_start = 0 if window_start < 0 else window_start + 1
    if end - lower <= _CONTEXT_LIMIT:
        window_start = lower
    window_end = text.find("\n", end)
    window_end = upper if window_end < 0 else min(window_end, upper)
    while window_end - window_start < _CONTEXT_LIMIT:
        next_end = text.find("\n", window_end + 1)
        if next_end < 0:
            next_end = upper
        next_end = min(next_end, upper)
        if next_end <= window_end or next_end - window_start > _CONTEXT_LIMIT:
            break
        window_end = next_end
    return text[window_start:window_end].strip()


def _evidence_window(text: str, start: int, end: int) -> tuple[str, bool]:
    lines = _line_spans(text)
    line_index = _line_index_for_position(lines, start)
    if line_index is None:
        return _line_window(text, start, end), False
    end_index = _line_index_for_position(lines, end - 1) or line_index
    lower = 0
    for index in range(line_index + 1):
        if _CONTEXT_BOUNDARY.match(lines[index][2].strip()):
            lower = (
                index + 1
                if lines[index][2].startswith("[page ") and index < line_index
                else index
            )
    upper = next(
        (index for index in range(end_index + 1, len(lines))
         if _CONTEXT_BOUNDARY.match(lines[index][2].strip())),
        len(lines),
    )
    context_start = (
        lines[lower][0]
        if _CONTEXT_BOUNDARY.match(lines[lower][2].strip())
        else lines[line_index][0]
    )
    context_end = lines[upper][0] if upper < len(lines) else len(text)
    lines = lines[lower:upper]
    line_index -= lower
    end_index -= lower
    if _has_table_context(lines, line_index):
        return _table_window(lines, line_index, end_index), True
    return _line_window(text, start, end, lower=context_start, upper=context_end), False


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for line in text.splitlines():
        end = cursor + len(line)
        spans.append((cursor, end, line))
        cursor = end + 1
    return spans


def _line_index_for_position(
    lines: list[tuple[int, int, str]],
    position: int,
) -> int | None:
    for index, (start, end, _) in enumerate(lines):
        if start <= position <= end:
            return index
    return None


def _has_table_context(lines: list[tuple[int, int, str]], line_index: int) -> bool:
    current = lines[line_index][2]
    nearby = [
        line
        for _, _, line in lines[max(0, line_index - 4) : min(len(lines), line_index + 4)]
    ]
    if re.search(r"\btable\s+\d+", current.casefold()):
        return True
    return _is_table_data_line(current) and any(
        _is_table_signal_line(line) for line in nearby
    )


def _table_window(
    lines: list[tuple[int, int, str]], line_index: int, end_index: int,
) -> str:
    start = max(0, line_index - 4)
    if (
        _CONTEXT_BOUNDARY.match(lines[0][2].strip())
        and lines[end_index][1] - lines[0][0] <= _CONTEXT_LIMIT
    ):
        start = 0
    end = min(len(lines), max(end_index + 1, line_index + 4))
    while end < len(lines) and lines[end][1] - lines[start][0] <= _CONTEXT_LIMIT:
        end += 1
    while start < line_index and _is_unrelated_table_boundary(lines[start][2]):
        start += 1
    while end > end_index + 1 and _is_unrelated_table_boundary(lines[end - 1][2]):
        end -= 1
    selected = [line for _, _, line in lines[start:end]]
    while len("\n".join(selected).strip()) > _CONTEXT_LIMIT and len(selected) > 1:
        center = line_index - start
        if center > 1:
            selected.pop(0)
            start += 1
            continue
        if end > end_index + 1:
            selected.pop()
            end -= 1
            continue
        break
    return "\n".join(selected).strip()


def _is_unrelated_table_boundary(line: str) -> bool:
    stripped = line.strip()
    return not stripped or re.fullmatch(r"\[page \d+\]", stripped) is not None


def _is_table_signal_line(line: str) -> bool:
    normalized = line.casefold()
    if re.search(r"\btable\s+\d+", normalized):
        return True
    return sum(
        1
        for token in (
            "method",
            "overall",
            "benchmark",
            "dataset",
            "f1",
            "bleu",
            "score",
            "accuracy",
        )
        if token in normalized
    ) >= 2


def _is_table_data_line(line: str) -> bool:
    return len(_numbers(line)) >= 2 and bool(re.search(r"[A-Za-z]", line))


def _page_number(text: str, position: int) -> int | None:
    markers = list(re.finditer(r"(?m)^\[page (?P<page>\d+)\]\s*$", text[: position + 1]))
    if not markers:
        return None
    return int(markers[-1].group("page"))


def _page_location(text: str, position: int) -> str | None:
    page = _page_number(text, position)
    return f"page {page}" if page is not None else None


def _numeric_anchor_failure(
    claim: Claim,
    resolutions: list[AnchorResolution],
) -> str | None:
    for resolution in resolutions:
        if resolution.table and resolution.table.get("error"):
            return str(resolution.table["error"])
    claim_text = _retrieval_parameter_text(claim.text)
    anchor_text = _retrieval_parameter_text(" ".join(
        _source_context_text(resolution) for resolution in resolutions))
    metric_names = {match["name"].casefold() for text in (claim_text, anchor_text)
                    for match in _METRIC_CUTOFF.finditer(text) if match["separator"] == "@"}

    def tokens(text: str) -> set[str]:
        parameters: set[str] = set()

        def metric(match: re.Match[str]) -> str:
            name = match["name"].casefold()
            if name not in metric_names:
                return match[0]
            parameters.add(f"metric:{name}@{match['cutoff']}")
            return " "

        # An explicit repeated annotation identifies a coordinated cutoff without
        # inferring aliases or borrowing a cutoff as evidence for a measured score.
        text = re.sub(
            r"(?P<head>\(\s*(?P<name>[A-Za-z][A-Za-z0-9_-]*)@\d+\s*\))"
            r"(?P<join>[ \t]+and[ \t]+)at[ \t]+(?P<cutoff>\d+)[ \t]*"
            r"\(\s*(?P=name)@(?P=cutoff)\s*\)",
            lambda match: f"{match['head']}{match['join']}{match['name']}@{match['cutoff']}",
            text, flags=re.IGNORECASE,
        )
        # A metric's cutoff is an identity, never evidence for a measured score.
        text = _METRIC_CUTOFF.sub(metric, text)
        return parameters | set(_numbers(text))

    if not tokens(claim_text).issubset(tokens(anchor_text)):
        return "numeric anchor missing claim values"
    return None


def _key_entity_anchor_failure(
    claim: Claim,
    resolutions: list[AnchorResolution],
) -> _AnchorIssue | None:
    table_failure = _table_anchor_row_failure(claim, resolutions)
    if table_failure is not None and not table_failure.reviewable:
        return table_failure
    depths = _retrieval_depths(claim.text)
    quote = " ".join(r.quote or "" for r in resolutions)
    quoted_depths = _retrieval_depths(quote)
    # One literal assignment can stand alone even when its block also lists sensitivity sets.
    explicit = {m[1] for m in _RETRIEVAL_SCALAR.finditer(_retrieval_notation(quote))}
    single_assignment = len(depths) == 1 and bool(quoted_depths) and depths == explicit
    if depths and depths != quoted_depths and not single_assignment:
        return _AnchorIssue("anchor missing or ambiguous retrieval depth")
    entities = _key_entities(claim.text)
    if not entities:
        return table_failure
    anchor_text = " ".join(_source_context_text(resolution) for resolution in resolutions)
    normalized_anchor = _compact_key(anchor_text)
    missing = [
        entity for entity in entities if _compact_key(entity) not in normalized_anchor
        and not (re.fullmatch(r"top[-‑–—](\d+)", entity, re.IGNORECASE)
                 and re.search(r"\d+", entity)[0] in depths)
    ]
    if missing:
        return _AnchorIssue("anchor missing key entities: " + ", ".join(missing))
    return table_failure


def _retrieval_depths(text: str) -> set[str]:
    """Read explicit retrieval depths, not arbitrary equal numbers or model suffixes."""
    text = _retrieval_notation(text)
    if not re.search(r"\bretriev\w*\b|\bwhite[- ]box\b", text, re.IGNORECASE):
        return set()
    depths = {m[1] for m in _RETRIEVAL_SCALAR.finditer(text)}
    # Expand only explicit finite sets, never ranges, ellipses or nearby numbers.
    for match in _RETRIEVAL_SET.finditer(text):
        depths.update(value.strip() for value in match[1].split(","))
    return depths


def _retrieval_notation(text: str) -> str:
    # Restore the observed preposition/math boundary, never split identifiers such as rec𝐾.
    text = re.sub(
        r"\b(with)([^\x00-\x7f])(?=\s*[=∈])",
        lambda m: f"{m[1]} {m[2]}" if unicodedata.normalize("NFKC", m[2]) == "K" else m[0],
        text, flags=re.IGNORECASE,
    )
    return unicodedata.normalize("NFKC", text)


def _retrieval_parameter_text(text: str) -> str:
    if not _retrieval_depths(text):
        return text
    # Within a finite set a comma separates members, not thousands (e.g. {2,500}).
    text = _RETRIEVAL_SET.sub(lambda m: m[0].replace(",", " "), _retrieval_notation(text))
    return re.sub(r"\btop[-‑–—](?=\d)", "top ", text, flags=re.IGNORECASE)


def _table_anchor_row_failure(
    claim: Claim,
    resolutions: list[AnchorResolution],
) -> _AnchorIssue | None:
    positioned = [r for r in resolutions if r.table and r.table.get("positioned")]
    if positioned and len(positioned) == len([r for r in resolutions if _is_table_resolution(r)]):
        column_failure = _table_column_failure(claim, positioned)
        if column_failure:
            return column_failure
        # Model group + setting name are one row identity, not competing method entities.
        cells = [c for r in positioned for c in r.table["positioned"]["table"]["cells"]
                 if c["cell_id"] in r.table["positioned"]["selected_cell_ids"]]
        for clause in re.split(r";|\b(?:versus|vs\.?|whereas|while|and)\b", claim.text,
                               flags=re.IGNORECASE):
            values = set(_numbers(re.sub(r"\b(?:table|figure|page)\s+\d+\b", "", clause,
                                        flags=re.IGNORECASE)))
            rows = {tuple(c["row_headers"]) for c in cells
                    if all(_entity_in_text(part, clause) for part in c["row_headers"])}
            if not values:
                continue
            if not rows:
                return _AnchorIssue("table assertion has no positioned row identity", True)
            if len(rows) != 1:
                return _AnchorIssue("table comparison has ambiguous positioned row binding", True)
            available = {n for c in cells if tuple(c["row_headers"]) in rows
                         for n in _numbers(c["value"])}
            if not values <= available:
                return _AnchorIssue("table anchor positioned row mismatch")
        return None
    rows = [
        row
        for resolution in resolutions
        if _is_table_resolution(resolution)
        for row in _quoted_table_rows(resolution)
    ]
    if not rows:
        return None
    column_failure = _table_column_failure(claim, resolutions)
    if column_failure:
        return column_failure
    headers = " ".join(str(header) for r in resolutions if r.table
                       for header in r.table["headers"])
    method_entities = [entity for entity in _key_entities(claim.text)
                       if _is_method_like_entity(entity) and not _entity_in_text(entity, headers)]
    if not method_entities:
        return None
    # Table labels also identify lowercase names such as "cosine similarity".
    for row in rows:
        label = re.split(r"\s+(?=[+−-]?\d)", row.strip(), maxsplit=1)[0]
        label = re.sub(r"\([^)]*\)", "", label).strip()
        if (
            label and not _is_table_signal_line(row)
            and _entity_in_text(label, claim.text)
            and not any(_compact_key(label) == _compact_key(entity) for entity in method_entities)
        ):
            method_entities.append(label)
    method_rows = {
        entity: [row for row in rows if _entity_in_text(entity, row)]
        for entity in method_entities
    }
    # Only a mapped table can defer caption/header roles; missing columns stay unresolved.
    scope_text = "\n".join(
        segment["text"]
        for resolution in resolutions
        if resolution.table and resolution.table["columns"]
        for segment in resolution.table["segments"]
        if segment["role"] in {"header", "caption"}
    )
    known_rows = [
        parsed[0] for resolution in resolutions if resolution.table
        for segment in resolution.table["segments"] if segment["role"] == "rows"
        for line in segment["text"].splitlines() if (parsed := numeric_row(line))
    ]
    uncertain_roles = []
    for entity, matching in method_rows.items():
        if not matching:
            if (_entity_in_text(entity, scope_text)
                    and not any(_entity_in_text(entity, row) for row in known_rows)):
                uncertain_roles.append(entity)
                continue
            return _AnchorIssue(f"table anchor row missing method entity: {entity}")
    method_entities = [entity for entity in method_entities if entity not in uncertain_roles]

    # Compare each local assertion with its method's quoted row, not the whole table.
    clauses = re.split(
        r"(?<!\d),|,(?!\d)|;|\b(?:versus|vs\.?|whereas|while|and)\b",
        claim.text, flags=re.IGNORECASE,
    )
    active: list[str] = []
    for clause in clauses:
        mentioned = [entity for entity in method_entities if _entity_in_text(entity, clause)]
        if mentioned:
            active = mentioned
        values = set(_numbers(re.sub(
            r"\b(?:table|figure|page)\s+\d+\b", "", clause, flags=re.IGNORECASE,
        )))
        if not values or not active:
            continue
        if len(active) != 1:
            return _AnchorIssue("table comparison has ambiguous method-value binding", True)
        entity = active[0]
        if not any(values.issubset(set(_numbers(row))) for row in method_rows[entity]):
            return _AnchorIssue(f"table anchor row missing method values: {entity}")
    if uncertain_roles:
        return _AnchorIssue("table entity roles require semantic review", True)
    return None


def _table_column_failure(claim: Claim, resolutions: list[AnchorResolution]) -> _AnchorIssue | None:
    for resolution in resolutions:
        if resolution.table and (positioned := resolution.table.get("positioned")):
            cells = [c for c in positioned["table"]["cells"]
                     if c["cell_id"] in positioned["selected_cell_ids"]]
            paths = {tuple(c["column_headers"]) for c in cells}
            for clause in re.split(r";|\b(?:versus|vs\.?|whereas|while|and)\b", claim.text,
                                   flags=re.IGNORECASE):
                selected = [p for p in paths if all(_entity_in_text(part, clause) for part in p)]
                values = set(_numbers(re.sub(r"\b(?:table|figure|page)\s+\d+\b", "", clause,
                                            flags=re.IGNORECASE)))
                leaves = [p for p in paths if _entity_in_text(p[-1], clause)]
                if not selected and leaves and values:
                    parents = {part for p in paths for part in p[:-1]
                               if _entity_in_text(part, clause)}
                    if len(leaves) == 1 and not parents:
                        selected = leaves
                    else:
                        return _AnchorIssue(
                            "table assertion has ambiguous or mismatched column group")
                mentioned = {tuple(c["row_headers"]) for c in cells
                             if all(_entity_in_text(part, clause) for part in c["row_headers"])}
                if not values or not selected:
                    continue
                if len(selected) != 1 or len(mentioned) != 1:
                    return _AnchorIssue("table comparison has ambiguous positioned binding", True)
                available = {n for c in cells if tuple(c["column_headers"]) == selected[0]
                             and tuple(c["row_headers"]) in mentioned for n in _numbers(c["value"])}
                if not values <= available:
                    return _AnchorIssue("table anchor positioned column mismatch")
            continue
        if not resolution.table or not resolution.table["columns"]:
            continue
        columns = resolution.table["columns"]
        rows = [row for raw in resolution.table["quoted_rows"] if (row := numeric_row(raw))]
        active_rows = rows
        for clause in re.split(r";|\b(?:versus|vs\.?|whereas|while|and)\b", claim.text,
                               flags=re.IGNORECASE):
            mentioned = [row for row in rows if _entity_in_text(row[0], clause)]
            if mentioned:
                active_rows = mentioned
            metrics = [i for i, column in enumerate(columns) if _entity_in_text(column, clause)]
            if len(metrics) > 1:
                return _AnchorIssue(
                    "table column binding ambiguous: split independent metric assertions", True)
            values = set(_numbers(re.sub(
                r"\b(?:table|figure|page)\s+\d+\b", "", clause, flags=re.IGNORECASE,
            )))
            if not metrics or not values:
                continue
            metric = metrics[0]
            if not any(values.issubset(set(_numbers(row[1][metric]))) for row in active_rows):
                return _AnchorIssue(f"table anchor column mismatch: {columns[metric]}")
    return None


def _entity_in_text(entity: str, text: str) -> bool:
    key = _compact_key(entity)
    if not key:
        return False
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(key) + r"(?![a-z0-9])"
    return re.search(pattern, unicodedata.normalize("NFKC", text).casefold()) is not None


def _is_table_resolution(resolution: AnchorResolution) -> bool:
    return bool(
        resolution.resolved_quote
        and (
            resolution.table or resolution.reason.startswith("table ")
            or _looks_like_table_window(resolution.resolved_quote)
        )
    )


def _looks_like_table_window(text: str) -> bool:
    lines = text.splitlines()
    return any(_is_table_signal_line(line) for line in lines) and any(
        _is_table_data_line(line) for line in lines
    )


def _quoted_table_rows(resolution: AnchorResolution) -> list[str]:
    if resolution.table:
        return list(resolution.table["quoted_rows"])
    context = resolution.resolved_quote or ""
    match = find_quote(resolution.quote or "", context)
    if match is None:
        return []
    return [
        line for start, end, line in _line_spans(context)
        if start < match.end and end > match.start and numeric_row(line) is not None
    ]


def _source_context_text(resolution: AnchorResolution) -> str:
    if resolution.table:
        if positioned := resolution.table.get("positioned"):
            return "\n".join([
                *(s["text"] for s in resolution.table["segments"]),
                *resolution.table["headers"], *_positioned_rows(positioned),
            ])
        return " ".join(segment["text"] for segment in resolution.table["segments"])
    return resolution.resolved_quote or ""


def _positioned_rows(positioned: dict) -> list[str]:
    rows: dict[tuple[str, ...], list[str]] = {}
    for cell in positioned["table"]["cells"]:
        if cell["cell_id"] in positioned["selected_cell_ids"]:
            rows.setdefault(tuple(cell["row_headers"]), []).append(cell["value"])
    return [" ".join([*headers, *values]) for headers, values in rows.items()]


def _is_method_like_entity(entity: str) -> bool:
    key = _compact_key(entity)
    if not key:
        return False
    blocked = {
        "aime",
        "bleu",
        "bleu1",
        "f1",
        "gpqa",
        "locomo",
        "longmemeval",
        "math",
    }
    model_markers = (
        "bert",
        "embedding",
        "gpt",
        "instruct",
        "llama",
        "minilm",
        "qwen",
    )
    return key not in blocked and not any(marker in key for marker in model_markers)


def _key_entities(text: str) -> list[str]:
    """Recognize explicit identities, not arbitrary hyphenated prose or variables."""
    candidates: list[str] = []
    patterns = (
        # Prefer complete versioned identities before their acronym/name fragments.
        r"\b(?=[A-Za-z0-9.\-‑–—]*\d)[A-Za-z][A-Za-z0-9]*"
        r"(?:[.\-‑–—][A-Za-z0-9]+)+\b",
        r"\b[A-Z][A-Za-z]*(?:[.\-‑–—][A-Z][A-Za-z0-9]+)+\b",
        r"\b[A-Z]{3,}[A-Z0-9]*\b",
        r"\b[A-Z][A-Za-z]+(?:[A-Z][A-Za-z0-9]+)+\b",
        r"\bF1\b",
        r"\bBLEU[-‑–—]?1\b",
    )
    for pattern in patterns:
        candidates.extend(match.group(0) for match in re.finditer(pattern, text))
    blocked = {"LLM", "LLMS", "AI", "GPU", "GPUS", "PDF"}
    entities: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _compact_key(candidate)
        if (
            not key
            or (candidate == candidate.casefold() and not any(ch.isdigit() for ch in candidate))
            or candidate.upper() in blocked
            or key in seen
            or any(key in existing or existing in key for existing in seen)
        ):
            continue
        seen.add(key)
        entities.append(candidate)
    return entities


def _compact_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"[^a-z0-9]+", "", normalized.casefold())


def _numbers(text: str) -> list[str]:
    numbers = []
    # Consume whole decimals before checking boundaries: a unit must not turn 23.8pp into 23.
    number = r"\d+(?:,[ \t]*\d{3}(?!\d))*(?:[ \t]*\.[ \t]*\d+)?(?:[eE][+-]?\d+)?"
    # Only an explicit two-ended percentage range shares its final percent sign.
    text = re.sub(rf"(?<![\w@.])({number})[ \t]*(?:[-−–—]|to)[ \t]*({number})[ \t]*%",
                  r"\1% to \2%", text, flags=re.IGNORECASE)
    pattern = rf"{number}(?:[ \t]*%)?"
    for match in re.finditer(pattern, text):
        before = text[match.start() - 1] if match.start() else ""
        article = (
            before == "a" and match.start() >= 2
            and not text[match.start() - 2].isalnum()
        )
        if before and (before.isalnum() or before in "_@-‑–—") and not article:
            continue
        numbers.append(re.sub(r"[ \t,]", "", match.group()))
    return numbers


def _repair_text(text: str, claims: list[Claim]) -> str:
    """Return compact source windows likely to contain exact repair quotes."""

    if len(text) <= 60_000:
        return text
    lines = text.splitlines()
    query_numbers = {number for claim in claims for number in _numbers(claim.text)}
    query_terms = {
        token
        for claim in claims
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", claim.text.casefold())
        if token
        not in {
            "experiment",
            "solution",
            "problem",
            "claim",
            "table",
            "paper",
            "method",
            "overall",
        }
    }
    scored = []
    for index, line in enumerate(lines):
        line_lower = line.casefold()
        score = 0
        score += 10 * sum(1 for number in query_numbers if number in line)
        score += sum(1 for term in query_terms if term in line_lower)
        if score:
            scored.append((score, index))
    selected_lines: set[int] = set(range(min(120, len(lines))))
    for _, index in sorted(scored, reverse=True)[:40]:
        for window_index in range(max(0, index - 3), min(len(lines), index + 4)):
            selected_lines.add(window_index)
    chunks = []
    current: list[str] = []
    last = -2
    for index in sorted(selected_lines):
        if index != last + 1 and current:
            chunks.append("\n".join(current))
            current = []
        current.append(lines[index])
        last = index
    if current:
        chunks.append("\n".join(current))
    return "\n\n--- source window ---\n\n".join(chunks)[:60_000]
