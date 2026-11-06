"""Lossless full-source presentation for scoped verification requests."""

from __future__ import annotations

import hashlib
from collections import Counter

from research_radar.analysis.paper_sections import (
    PaperReadingPacket,
    reading_packet_index,
    render_reading_packet,
)

SOURCE_PACKET_INSTRUCTIONS = (
    "Compact packets keep the full source in ordered source_parts. "
    "source_parts_ref gives packet ID and inclusive first/last part IDs; read their exact text. "
    "Read section_rows by section_fields; role, pages and reason index their named lists from 0. "
)


def pack_review_source_packets(payload: dict, packets: dict[str, PaperReadingPacket]) -> dict:
    """Replace only exact source copies; retain full text and the original proof bindings."""
    context = payload["source_context"]
    sources = context.get("full_sources", [])
    if not packets or not sources:
        return payload
    values = context.get("source_values", {})
    hashes = Counter(source.get("text_sha256") for source in sources)
    records = payload["source_records"].copy()

    def deref(value: object) -> object:
        if isinstance(value, dict) and set(value) == {"$"}:
            return values.get(value["$"], value)
        return value

    def pack(source: dict, packet_id: str) -> dict:
        url = source.get("source_url")
        packet = packets.get(url)
        if packet is None or render_reading_packet(packet) != source.get("reading_packet"):
            return source
        body = packet.source_text
        digest = hashlib.sha256(body.encode()).hexdigest()
        if source.get("text_sha256") != digest:
            return source
        spans: list[tuple[str, str, int, int]] = []
        for record_id, record in records.items():
            if {"literal", "start", "end", "source_text_sha256"} <= record.keys():
                field = "literal"
                literal = deref(record[field])
                start, end = record["start"], record["end"]
                if (deref(record["source_text_sha256"]) != digest
                        or ("source_url" in record and deref(record["source_url"]) != url)
                        or ("source_url" not in record and hashes[digest] != 1)
                        or type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= len(body) or body[start:end] != literal):
                    continue
            elif "quote" in record and deref(record.get("source_url")) == url:
                field = "quote"
                literal = deref(record[field])
                if (("source_text_sha256" in record
                     and deref(record["source_text_sha256"]) != digest)
                        or not isinstance(literal, str) or len(literal.encode()) < 150):
                    continue
                start = body.find(literal)
                if start < 0 or body.find(literal, start + 1) >= 0:
                    continue
                end = start + len(literal)
            else:
                continue
            if isinstance(literal, str) and len(literal.encode()) >= 150:
                spans.append((record_id, field, start, end))
        offsets = sorted({0, len(body), *(n for _, _, a, b in spans for n in (a, b))})
        ranges = zip(offsets[:-1], offsets[1:], strict=True)
        parts = [[f"r{i}", body[a:b]] for i, (a, b) in enumerate(ranges)]
        indexes = {offset: i for i, offset in enumerate(offsets)}
        for record, field, start, end in spans:
            first, last = indexes[start], indexes[end] - 1
            records[record] = {**records[record],
                field: {"source_parts_ref": [packet_id, parts[first][0], parts[last][0]]}}
        return {**source, "reading_packet": _packet_fields(packet, packet_id, parts)}

    packed_sources = [pack(source, f"p{i}") for i, source in enumerate(sources, 1)]
    if packed_sources == sources:
        return payload
    packed_context = {**context, "full_sources": packed_sources}
    result = {**payload, "source_context": packed_context, "source_records": records}
    if values:
        used = _used_values(result)
        packed_context["source_values"] = {key: v for key, v in values.items() if key in used}
    return result


def _packet_fields(packet: PaperReadingPacket, packet_id: str, parts: list[list[str]]) -> dict:
    prefix, rows = reading_packet_index(packet)
    roles: dict[str, int] = {}
    pages: dict[str, int] = {}
    reasons: dict[str, int] = {}
    return {"packet_id": packet_id, "section_prefix": "\n".join(prefix),
            "section_fields": ["chunk", "role", "pages", "reason", "section", "source_span"],
            "section_rows": [[i, roles.setdefault(role, len(roles)),
                              pages.setdefault(page, len(pages)),
                              reasons.setdefault(reason, len(reasons)), section, span]
                             for i, role, page, reason, section, span in rows],
            "roles": list(roles), "pages": list(pages), "reasons": list(reasons),
            "source_parts": parts}


def _used_values(value: object) -> set[str]:
    if isinstance(value, list):
        return {ref for item in value for ref in _used_values(item)}
    if not isinstance(value, dict):
        return set()
    if set(value) == {"$"} and isinstance(ref := value["$"], str) and ref.startswith("v"):
        return {ref}
    return {ref for key, item in value.items() if key != "source_values"
            for ref in _used_values(item)}
