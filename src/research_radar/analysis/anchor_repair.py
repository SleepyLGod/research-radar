"""Deterministic evidence anchor resolution and quote-only repair."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, replace

from research_radar.analysis.providers import LLMProvider, Message
from research_radar.models import Artifact, Claim, ClaimStatus, EvidenceAnchor, ReviewFinding


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


def resolve_quote(quote: str, artifact: Artifact) -> AnchorResolution:
    """Resolve a quote against an artifact without semantic fuzzy matching."""

    quote = quote.strip()
    if not quote:
        return AnchorResolution(0, "", "failed", "empty quote", quote=quote)
    direct = _direct_match(quote, artifact.text)
    if direct is not None:
        return _quote_resolution(quote, artifact, direct, "exact")
    normalized = _normalized_match(quote, artifact.text)
    if normalized is not None:
        return _quote_resolution(quote, artifact, normalized, "normalized")
    compact = _compact_match(quote, artifact.text)
    if compact is not None:
        return _quote_resolution(quote, artifact, compact, "compact")
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
        anchor_resolutions = [resolve_quote(anchor.quote, artifact) for anchor in claim.evidence]
        failed = [resolution for resolution in anchor_resolutions if resolution.status == "failed"]
        matched = [resolution for resolution in anchor_resolutions if resolution.status != "failed"]
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
                    "failed",
                    entity_failure,
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
        if resolution.status == "matched":
            checked.append(claim)
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
    target_indexes = [
        resolution.claim_index
        for resolution in resolutions
        if resolution.status in {"failed", "partial"}
        and not _skip_repair(resolved_claims[resolution.claim_index - 1])
    ]
    if not target_indexes:
        return resolved_claims, resolutions, [], resolution_findings

    payload = _repair_payload(provider, model, resolved_claims, artifact, target_indexes)
    repairs = _parse_repairs(payload)
    repaired = list(resolved_claims)
    attempts: list[AnchorRepairAttempt] = []
    findings: list[ReviewFinding] = []
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
        quote_resolution = resolve_quote(quote, artifact)
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
            quote=quote_resolution.resolved_quote or quote,
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
                entity_failure,
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


def _skip_repair(claim: Claim) -> bool:
    source = claim.metadata.get("paper_reading", {}).get("source")
    return source == "unsupported_or_rejected_claims"


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
    resolved = _line_window(artifact.text, span[0], span[1])
    return AnchorResolution(
        0,
        "",
        "matched",
        reason,
        quote=quote,
        resolved_quote=resolved,
        location=_page_location(artifact.text, span[0]),
        page=_page_number(artifact.text, span[0]),
    )


def _direct_match(quote: str, text: str) -> tuple[int, int] | None:
    start = text.find(quote)
    if start < 0:
        return None
    return start, start + len(quote)


def _normalized_match(quote: str, text: str) -> tuple[int, int] | None:
    return _mapped_substring_match(_normalize_char, quote, text)


def _compact_match(quote: str, text: str) -> tuple[int, int] | None:
    compact_quote = "".join(ch for ch in quote.casefold() if ch.isalnum())
    if len(compact_quote) < 12:
        return None
    return _mapped_substring_match(
        lambda char: char.casefold() if char.isalnum() else "",
        quote,
        text,
    )


def _mapped_substring_match(
    normalize_char,
    quote: str,
    text: str,
) -> tuple[int, int] | None:
    normalized_quote = "".join(normalize_char(char) for char in _dehyphenate(quote))
    normalized_quote = re.sub(r"\s+", " ", normalized_quote).strip()
    if not normalized_quote:
        return None
    chars = []
    positions = []
    for char in _dehyphenate(text, keep_positions=True):
        raw_char, raw_index = char
        normalized = normalize_char(raw_char)
        if not normalized:
            continue
        if normalized.isspace():
            normalized = " "
        chars.append(normalized)
        positions.append(raw_index)
    normalized_text = re.sub(r"\s+", " ", "".join(chars)).strip()
    if not normalized_text:
        return None
    start = normalized_text.find(normalized_quote)
    if start < 0:
        return None
    raw_start = positions[min(start, len(positions) - 1)]
    raw_end_index = min(start + len(normalized_quote) - 1, len(positions) - 1)
    raw_end = positions[raw_end_index] + 1
    return raw_start, raw_end


def _normalize_char(char: str) -> str:
    if char in {"\xad", "\x00"}:
        return ""
    return char.casefold()


def _dehyphenate(
    text: str,
    *,
    keep_positions: bool = False,
) -> str | list[tuple[str, int]]:
    output: list[str] | list[tuple[str, int]] = []
    index = 0
    while index < len(text):
        if (
            text[index] == "-"
            and index + 1 < len(text)
            and text[index + 1].isspace()
            and index > 0
            and text[index - 1].isalpha()
        ):
            next_index = index + 1
            while next_index < len(text) and text[next_index].isspace():
                next_index += 1
            if next_index < len(text) and text[next_index].isalpha():
                index = next_index
                continue
        if keep_positions:
            output.append((text[index], index))  # type: ignore[arg-type]
        else:
            output.append(text[index])  # type: ignore[arg-type]
        index += 1
    return output if keep_positions else "".join(output)  # type: ignore[return-value]


def _line_window(text: str, start: int, end: int) -> str:
    window_start = text.rfind("\n", 0, start)
    window_start = 0 if window_start < 0 else window_start + 1
    window_end = text.find("\n", end)
    window_end = len(text) if window_end < 0 else window_end
    while window_end - window_start < 600:
        next_end = text.find("\n", window_end + 1)
        if next_end < 0 or next_end - window_start > 600:
            break
        window_end = next_end
    return text[window_start:window_end].strip()


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
    claim_numbers = set(_numbers(claim.text))
    if not claim_numbers:
        return None
    anchor_text = " ".join(resolution.resolved_quote or "" for resolution in resolutions)
    anchor_numbers = set(_numbers(anchor_text))
    if not claim_numbers.issubset(anchor_numbers):
        return "numeric anchor missing claim values"
    return None


def _key_entity_anchor_failure(
    claim: Claim,
    resolutions: list[AnchorResolution],
) -> str | None:
    entities = _key_entities(claim.text)
    if not entities:
        return None
    anchor_text = " ".join(resolution.resolved_quote or "" for resolution in resolutions)
    normalized_anchor = _compact_key(anchor_text)
    missing = [
        entity for entity in entities if _compact_key(entity) not in normalized_anchor
    ]
    if missing:
        return "anchor missing key entities: " + ", ".join(missing)
    return None


def _key_entities(text: str) -> list[str]:
    candidates: list[str] = []
    patterns = (
        r"\b[A-Z]{3,}[A-Z0-9]*\b",
        r"\b[A-Za-z]+(?:[.\-‑–—][A-Za-z0-9]+)+\b",
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
    return re.findall(
        r"(?<![A-Za-z0-9._\-‑–—])\d+(?:\.\d+)?%?(?![A-Za-z0-9])",
        text,
    )


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
