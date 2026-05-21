"""Build page-aware full-paper reading packets."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_radar.models import Artifact

DEFAULT_READING_PACKET_BUDGET = 24_000
_PAGE_MARKER = re.compile(r"(?m)^\[page (?P<page>\d+)\]\s*$")
_REFERENCE_HEADING = re.compile(r"(?im)^\s*(references|bibliography)\s*$")


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
    """The bounded full-paper packet sent to the reader."""

    chunks: list[PaperSectionChunk]
    warnings: list[str] = field(default_factory=list)
    char_budget: int = DEFAULT_READING_PACKET_BUDGET


def build_paper_sections(artifact: Artifact) -> list[PaperSectionChunk]:
    """Split extracted paper text into page-aware section chunks."""

    chunks: list[PaperSectionChunk] = []
    in_references = False
    for page_number, text in _pages_from_text(artifact.text):
        normalized = text.strip()
        if not normalized:
            continue
        if _is_references_start(normalized):
            role = "references"
            in_references = True
        elif in_references and not _is_appendix_start(normalized):
            role = "references"
        else:
            in_references = False
            role = _classify_role(page_number, normalized)
        chunks.append(
            PaperSectionChunk(
                role=role,
                page_start=page_number,
                page_end=page_number,
                text=normalized,
                metadata={
                    "priority_score": _priority_score(role, normalized),
                    "char_count": len(normalized),
                },
            )
        )
    return chunks


def build_reading_packet(
    artifact: Artifact,
    *,
    sections: list[PaperSectionChunk] | None = None,
    char_budget: int = DEFAULT_READING_PACKET_BUDGET,
) -> PaperReadingPacket:
    """Build a bounded packet that samples the whole paper conservatively."""

    chunks = sections if sections is not None else build_paper_sections(artifact)
    warnings = _coverage_warnings(chunks)
    selected = _select_chunks(chunks, char_budget=char_budget)
    return PaperReadingPacket(
        chunks=selected,
        warnings=warnings,
        char_budget=char_budget,
    )


def render_reading_packet(packet: PaperReadingPacket) -> str:
    """Render a reading packet for prompt and audit output."""

    lines = [
        "FULL PAPER READING PACKET",
        f"Character budget: {packet.char_budget}",
        "",
    ]
    if packet.warnings:
        lines.append("Coverage warnings:")
        lines.extend(f"- {warning}" for warning in packet.warnings)
        lines.append("")
    for index, chunk in enumerate(packet.chunks, start=1):
        pages = (
            f"page {chunk.page_start}"
            if chunk.page_start == chunk.page_end
            else f"pages {chunk.page_start}-{chunk.page_end}"
        )
        reason = chunk.metadata.get("selection_reason", "selected")
        lines.extend(
            [
                f"[chunk {index}] role={chunk.role} pages={pages} reason={reason}",
                chunk.text.strip(),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _pages_from_text(text: str) -> list[tuple[int, str]]:
    matches = list(_PAGE_MARKER.finditer(text))
    if not matches:
        return [(1, text)]
    pages: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        page_number = int(match.group("page"))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append((page_number, text[start:end]))
    return pages


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
        re.search(r"(?m)^\s*(APPENDIX|[A-Z]\s+[A-Z][A-Z\s,&-]{3,})\s*$", text[:2500])
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


def _priority_score(role: str, text: str) -> int:
    role_scores = {
        "abstract": 90,
        "introduction": 80,
        "method": 75,
        "experiments_results": 85,
        "limitations_conclusion": 82,
        "related_work": 70,
        "other": 30,
        "references": 0,
    }
    role_keywords = {
        "method": (
            "framework",
            "method",
            "approach",
            "architecture",
            "module",
            "information extraction",
            "memory management",
            "memory storage",
            "retrieval",
        ),
        "experiments_results": (
            "benchmark",
            "result",
            "table",
            "ablation",
            "cost",
            "locomo",
            "longmemeval",
            "robustness",
            "scalability",
        ),
        "limitations_conclusion": (
            "limitation",
            "future work",
            "conclusion",
            "lessons",
            "opportunities",
            "challenge",
        ),
        "related_work": ("related work", "related works", "prior work", "baseline"),
    }
    keyword_bonus = _keyword_count(
        text.casefold(),
        role_keywords.get(
            role,
            (
                "benchmark",
                "result",
                "limitation",
                "locomo",
                "longmemeval",
            ),
        ),
    )
    return role_scores.get(role, 30) + min(keyword_bonus, 20)


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
            warnings.append(f"missing section role: {label}")
    return warnings


def _select_chunks(
    chunks: list[PaperSectionChunk],
    *,
    char_budget: int,
) -> list[PaperSectionChunk]:
    selected: list[PaperSectionChunk] = []
    selected_ids: set[int] = set()
    remaining = char_budget

    def add(chunk: PaperSectionChunk, reason: str) -> None:
        nonlocal remaining
        if id(chunk) in selected_ids or chunk.role == "references" or remaining <= 0:
            return
        text = _bounded_text(
            chunk.text,
            min(remaining, _chunk_char_limit(chunk.role, char_budget)),
        )
        if not text:
            return
        if len(text) < 80 and len(chunk.text) > len(text):
            return
        selected_ids.add(id(chunk))
        remaining -= len(text)
        selected.append(
            PaperSectionChunk(
                role=chunk.role,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=text,
                selected=True,
                metadata={
                    **chunk.metadata,
                    "selection_reason": reason,
                    "selected_char_count": len(text),
                },
            )
        )

    role_groups = {
        role: sorted(
            [chunk for chunk in chunks if chunk.role == role],
            key=lambda chunk: (
                -int(chunk.metadata.get("priority_score", 0)),
                chunk.page_start,
            ),
        )
        for role in {
            "abstract",
            "introduction",
            "method",
            "experiments_results",
            "limitations_conclusion",
            "related_work",
        }
    }

    coverage_pass = [
        ("abstract", 1),
        ("introduction", 1),
        ("method", 1),
        ("experiments_results", 2),
        ("limitations_conclusion", 1),
        ("related_work", 1),
    ]
    extra_pass = [
        ("experiments_results", 2),
        ("limitations_conclusion", 1),
        ("method", 1),
        ("related_work", 1),
    ]

    for role, limit in [*coverage_pass, *extra_pass]:
        candidates = sorted(
            [
                chunk
                for chunk in role_groups.get(role, [])
                if id(chunk) not in selected_ids
            ],
            key=lambda chunk: (
                -int(chunk.metadata.get("priority_score", 0)),
                chunk.page_start,
            ),
        )
        for chunk in candidates[:limit]:
            add(chunk, f"role coverage: {role}")

    filler = sorted(
        [chunk for chunk in chunks if id(chunk) not in selected_ids],
        key=lambda chunk: (
            -int(chunk.metadata.get("priority_score", 0)),
            chunk.page_start,
        ),
    )
    for chunk in filler:
        add(chunk, "budget filler")

    return sorted(selected, key=lambda chunk: chunk.page_start)


def _chunk_char_limit(role: str, char_budget: int) -> int:
    role_limits = {
        "abstract": 2_500,
        "introduction": 3_000,
        "method": 4_500,
        "experiments_results": 4_500,
        "limitations_conclusion": 3_500,
        "related_work": 3_000,
        "other": 1_500,
    }
    return min(role_limits.get(role, 1_500), max(800, char_budget // 2))


def _bounded_text(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(normalized) <= budget:
        return normalized
    if budget < 50:
        return normalized[:budget].rstrip()
    return normalized[: max(0, budget - 20)].rstrip() + "\n[truncated]"
