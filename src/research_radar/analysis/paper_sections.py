"""Build page-aware full-paper reading packets."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact

_PAGE_MARKER = re.compile(r"(?m)^\[page (?P<page>\d+)\]\s*$")
_REFERENCE_HEADING = re.compile(r"(?im)^\s*(references|bibliography)\s*$")
_NUMBERED_HEADING = re.compile(
    r"^(?:\d+(?:\.\d+)+[.)]?[ \t]*|\d+[.)]?[ \t]+|[A-Z](?:\.\d+)*[.)]?[ \t]+)"
    r"(?=[A-Z])[A-Za-z][^\n.!?;=]{1,90}$"
)
_NAMED_HEADING = re.compile(
    r"^(?:abstract|introduction|related work|background|method|approach|framework|architecture|"
    r"experiments?|evaluation|results?|analysis|limitations?|discussion|conclusions?|"
    r"future work|references|bibliography)$", re.IGNORECASE,
)
_TITLE_WORD = r"[A-Z][a-z]+(?:[A-Z][a-z]+|[-‑–][A-Z]?[a-z]+)*"
_TITLE_HEADING = re.compile(rf"{_TITLE_WORD}(?:[ \t]+{_TITLE_WORD}){{1,5}}")
_CAMEL_HEADING = re.compile(r"[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+")


@dataclass(frozen=True)
class PaperSectionChunk:
    """A page-aware paper chunk selected for deep reading."""

    role: str
    page_start: int
    page_end: int
    text: str
    selected: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperReadingPacket:
    """Complete extracted text with a page/section index, never selected excerpts."""

    chunks: list[PaperSectionChunk]
    warnings: list[str] = field(default_factory=list)
    source_text: str = ""
    coverage: list[dict[str, object]] = field(default_factory=list)


def build_paper_sections(artifact: Artifact) -> list[PaperSectionChunk]:
    """Split explicit sections while preserving page and exact source spans."""

    chunks: list[PaperSectionChunk] = []
    role, heading, section_id = "other", "", 0
    for page_number, page_start, page_end in _page_spans(artifact.text):
        text = artifact.text[page_start:page_end]
        headings = [match for match in re.finditer(r"(?m)^[^\n]+$", text)
                    if _is_heading(match.group().strip())]
        headings = [match for i, match in enumerate(headings)
                    if _NUMBERED_HEADING.fullmatch(match.group().strip())
                    or _NAMED_HEADING.fullmatch(match.group().strip())
                    or _is_appendix_start(match.group().strip())
                    or re.search(r"[.!?。](?=\s|$)", text[match.end():
                                 headings[i + 1].start() if i + 1 < len(headings) else len(text)])]
        boundaries = sorted({0, len(text), *(match.start() for match in headings)})
        heading_at = {match.start(): match.group().strip() for match in headings}
        for start, end in zip(boundaries, boundaries[1:], strict=False):
            raw = text[start:end]
            normalized = raw.strip()
            if not normalized:
                continue
            if start in heading_at:
                heading = heading_at[start]
                section_id += 1
                if _is_references_start(heading):
                    role = "references"
                elif role == "references" and not _is_appendix_start(heading):
                    role = "references"
                else:
                    classified = _classify_role(page_number, heading)
                    if classified == "other":
                        classified = _classify_role(page_number, normalized)
                    role = classified if classified != "other" else (
                        "other" if role == "references" else role
                    )
            elif not heading:
                role = _classify_role(page_number, normalized)
            source_start = page_start + start + len(raw) - len(raw.lstrip())
            chunks.append(PaperSectionChunk(
                role=role, page_start=page_number, page_end=page_number, text=normalized,
                metadata={
                    "char_count": len(normalized), "heading": heading,
                    "section_id": section_id, "source_start": source_start,
                    "source_end": source_start + len(normalized),
                },
            ))
    return chunks


def build_reading_packet(
    artifact: Artifact,
    *,
    sections: list[PaperSectionChunk] | None = None,
    char_budget: int | None = None,
) -> PaperReadingPacket:
    """Preserve all extracted text; an explicit character cap rejects, never clips."""

    chunks = sections if sections is not None else build_paper_sections(artifact)
    if char_budget is not None:
        if type(char_budget) is not int or char_budget <= 0:
            raise ValueError("Reading packet character budget must be positive.")
        if len(artifact.text) > char_budget:
            raise AnalysisError("Complete reading input exceeds the explicit character cap.")
    selected_chunks = [replace(chunk, selected=True) for chunk in chunks]
    coverage = []
    for index, chunk in enumerate(chunks):
        coverage.append({
            "chunk_id": index + 1, "role": chunk.role, "heading": chunk.metadata.get("heading", ""),
            "page_start": chunk.page_start, "page_end": chunk.page_end,
            "source_start": chunk.metadata.get("source_start"),
            "source_end": chunk.metadata.get("source_end"),
            "retained_chars": len(chunk.text), "source_chars": len(chunk.text),
            "status": "complete",
        })
    warnings = _coverage_warnings(selected_chunks)
    return PaperReadingPacket(
        chunks=selected_chunks,
        warnings=warnings,
        source_text=artifact.text,
        coverage=coverage,
    )


def reading_packet_index(
    packet: PaperReadingPacket,
) -> tuple[list[str], list[tuple[int, str, str, str, str, str]]]:
    """Build the section index shared by literal and compact packet presentations."""
    lines = [
        "FULL PAPER READING PACKET (complete extracted text; not visual PDF inspection)",
        f"Source characters: {len(packet.source_text)}",
        "",
    ]
    if packet.warnings:
        lines.append("Section-index warnings (no source text omitted):")
        lines.extend(f"- {warning}" for warning in packet.warnings)
        lines.append("")
    rows = []
    for index, chunk in enumerate(packet.chunks, start=1):
        pages = (
            f"page {chunk.page_start}"
            if chunk.page_start == chunk.page_end
            else f"pages {chunk.page_start}-{chunk.page_end}"
        )
        reason = chunk.metadata.get("selection_reason", "selected")
        source_end = chunk.metadata.get(
            "selected_source_end", chunk.metadata.get("source_end", "?"),
        )
        rows.append((index, chunk.role, pages, str(reason),
                     str(chunk.metadata.get("heading") or "unlabeled"),
                     f"{chunk.metadata.get('source_start', '?')}:{source_end}"))
    return lines, rows


def render_reading_packet(
    packet: PaperReadingPacket, *, rendered_source: str | None = None,
) -> str:
    """Render a reading packet for prompt and audit output."""
    lines, rows = reading_packet_index(packet)
    for index, role, pages, reason, heading, span in rows:
        lines.extend(
            [
                f"[chunk {index}] role={role} pages={pages} reason={reason}",
                f"Section: {heading}; source span: {span}",
                "",
            ]
        )
    source = packet.source_text if rendered_source is None else rendered_source
    return "\n".join(lines) + "\nSOURCE TEXT\n" + source + "\nEND SOURCE TEXT\n"


def _page_spans(text: str) -> list[tuple[int, int, int]]:
    matches = list(_PAGE_MARKER.finditer(text))
    if not matches:
        return [(1, 0, len(text))]
    pages: list[tuple[int, int, int]] = []
    for index, match in enumerate(matches):
        page_number = int(match.group("page"))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append((page_number, start, end))
    return pages


def _is_heading(line: str) -> bool:
    return bool(_NUMBERED_HEADING.fullmatch(line) or _NAMED_HEADING.fullmatch(line)
                or _TITLE_HEADING.fullmatch(line) or _CAMEL_HEADING.fullmatch(line)
                or re.fullmatch(r"(?i:appendix)(?:[ \t]+(?:[A-Za-z]|\d+))?", line))


def _classify_role(page_number: int, text: str) -> str:
    lower = text.casefold()
    heading = text[:7000].casefold()
    front_matter = text[:2500].casefold()
    if _is_references_start(text):
        return "references"
    if page_number <= 2 and "abstract" in front_matter:
        return "abstract"
    if _has_heading(heading, "introduction"):
        return "introduction"
    if _has_heading(
        heading,
        "limitation",
        "limitations",
        "discussion",
        "conclusion",
        "conclusions",
        "future work",
        "lessons and opportunities",
    ):
        return "limitations_conclusion"
    if _has_heading(heading, "related work", "related works", "background"):
        return "related_work"
    if _has_heading(
        heading,
        "experiment",
        "experiments",
        "experiment details",
        "evaluation",
        "evaluations",
        "result",
        "results",
        "analysis",
        "analyses",
    ):
        return "experiments_results"
    if _has_heading(heading, "method", "approach", "framework", "architecture"):
        return "method"
    scores = {
        "experiments_results": _keyword_count(
            lower,
            (
                "experiment",
                "evaluation",
                "benchmark",
                "result",
                "table",
                "ablation",
                "performance",
                "locomo",
                "longmemeval",
                "token cost",
                "scalability",
            ),
        ),
        "limitations_conclusion": _keyword_count(
            lower,
            ("limitation", "future work", "conclusion", "discussion", "weakness"),
        ),
        "method": _keyword_count(
            lower,
            ("framework", "method", "approach", "architecture", "module", "retrieval"),
        ),
        "related_work": _keyword_count(
            lower,
            ("related work", "representative", "prior work", "baseline"),
        ),
        "introduction": _keyword_count(lower, ("introduction", "motivation", "problem")),
    }
    role, score = max(scores.items(), key=lambda item: item[1])
    return role if score > 0 else "other"


def _is_references_start(text: str) -> bool:
    return bool(_REFERENCE_HEADING.search(text[:500]))


def _is_appendix_start(text: str) -> bool:
    return bool(
        re.search(
            r"(?m)^[ \t]*(?:(?i:appendix)(?:[ \t]+(?:[A-Za-z]|\d+))?"
            r"|[A-Z]\s+[A-Z][A-Z\s,&-]{3,})[ \t]*$",
            text[:2500],
        )
    )


def _has_heading(heading: str, *terms: str) -> bool:
    for term in terms:
        escaped = re.escape(term)
        anchored = rf"(?m)^\s*\d*(?:\.\d+)*\s*{escaped}\b"
        inline_numbered = rf"(?:^|\n|\.\s)\s*\d+(?:\.\d+)*\s+{escaped}\b"
        if re.search(anchored, heading) or re.search(inline_numbered, heading):
            return True
    return False


def _keyword_count(text: str, keywords: tuple[str, ...]) -> int:
    return sum(text.count(keyword) for keyword in keywords)


def _coverage_warnings(chunks: list[PaperSectionChunk]) -> list[str]:
    roles = {chunk.role for chunk in chunks if chunk.role != "references"}
    warnings = []
    required_groups = {
        "abstract_or_introduction": {"abstract", "introduction"},
        "method": {"method"},
        "experiments_results": {"experiments_results"},
        "limitations_conclusion": {"limitations_conclusion"},
    }
    for label, group in required_groups.items():
        if not roles.intersection(group):
            warnings.append(f"section heading not identified: {label}; no source text omitted")
    return warnings
