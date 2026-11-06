"""Select prebounded source blocks without model-written quotes or range arithmetic."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from research_radar.analysis.paper_sections import build_paper_sections
from research_radar.evidence.tables import numeric_row
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact

MAX_EVIDENCE_CHARS = 1200
_PAGE = re.compile(r"^\[page (\d+)\]\s*$")
_SOURCE_LOCATION = re.compile(r"page ([1-9]\d*); source block (b[0-9a-f]{16}:[1-9]\d*)")


class SourceReferenceError(AnalysisError):
    """A Reader selected invalid evidence; another syntax-repair call cannot approve it."""


@dataclass(frozen=True)
class SourceUnit:
    """A bounded, same-page block with exact original offsets."""

    identity: str
    start: int
    end: int
    page: int


@dataclass(frozen=True)
class SourceIndex:
    """References are bound to the exact source URL and extracted text."""

    text: str
    units: tuple[SourceUnit, ...]

    @property
    def source_ids(self) -> list[str]:
        """Offer only nonempty blocks; whitespace still remains in the complete input."""
        return [u.identity for u in self.units if self.text[u.start : u.end].strip()]

    def render(self) -> str:
        """Use the literal protocol ID, not a decorated approximation of its spelling."""
        return "".join(
            (f"\nsource_id={u.identity}\n" if self.text[u.start : u.end].strip() else "")
            + self.text[u.start : u.end]
            for u in self.units
        )

    def resolve(self, reference: object) -> dict[str, str]:
        """Materialize exactly one offered block; never strip wrappers or repair old ranges."""
        if (
            not isinstance(reference, dict)
            or set(reference) != {"source_id"}
            or not isinstance(reference["source_id"], str)
        ):
            raise SourceReferenceError(
                "Evidence requires one source_id, not quotes or line ranges."
            )
        unit = next((u for u in self.units if u.identity == reference["source_id"]), None)
        if unit is None:
            raise SourceReferenceError("Unknown or foreign source reference.")
        quote = self.text[unit.start : unit.end]
        if not quote.strip():
            raise SourceReferenceError("Evidence range contains no source text.")
        return {"quote": quote, "location": f"page {unit.page}; source block {unit.identity}"}

    def reference_for_span(self, start: int, end: int) -> dict[str, str]:
        """Address a known span contained in one block, without evidence discovery."""
        references = self.references_for_span(start, end)
        if len(references) != 1:
            raise SourceReferenceError("Use separate source blocks for this original span.")
        return references[0]

    def references_for_span(self, start: int, end: int) -> list[dict[str, str]]:
        """Address known original offsets with separate blocks, never join their text."""
        if not 0 <= start < end <= len(self.text):
            raise SourceReferenceError("Source span is outside the original text.")
        references = [
            {"source_id": u.identity}
            for u in self.units
            if u.start < end and u.end > start and self.text[u.start : u.end].strip()
        ]
        if not references:
            raise SourceReferenceError("Evidence span contains no source text.")
        return references


def build_source_index(artifact: Artifact) -> SourceIndex:
    """Precompute bounded blocks using page, blank-line and existing line boundaries."""
    identity = hashlib.sha256((artifact.source.url + "\0" + artifact.text).encode()).hexdigest()[
        :16
    ]
    page, offset, start = 1, 0, 0
    units: list[SourceUnit] = []
    section_starts = {chunk.metadata["source_start"] for chunk in build_paper_sections(artifact)}
    previous_numeric = False

    def emit(end: int) -> None:
        nonlocal start
        if end > start:
            units.append(SourceUnit(f"b{identity}:{len(units) + 1}", start, end, page))
            start = end

    for line in artifact.text.splitlines(keepends=True):
        is_numeric = numeric_row(line.rstrip("\r\n")) is not None
        if is_numeric != previous_numeric or any(
            offset <= point < offset + len(line) for point in section_starts
        ):
            emit(offset)
        if match := _PAGE.fullmatch(line):
            emit(offset)
            page = int(match[1])
        if offset + len(line) - start > MAX_EVIDENCE_CHARS:
            emit(offset)
        end = offset + len(line)
        while end - start > MAX_EVIDENCE_CHARS:
            emit(start + MAX_EVIDENCE_CHARS)
        offset = end
        if not line.strip():
            emit(offset)
        previous_numeric = is_numeric
    emit(offset)
    return SourceIndex(artifact.text, tuple(units))


def selected_source_unit(
    artifact: Artifact, quote: str, location: str | None,
) -> SourceUnit | None:
    """Recover an exact selection; only anchors without a block marker may use quote search."""
    if location is None or not re.search(r"\bsource\s+block\b", location, re.IGNORECASE):
        return None
    match = _SOURCE_LOCATION.fullmatch(location)
    if match is None:
        raise SourceReferenceError("Malformed selected source block location.")
    unit = next((u for u in build_source_index(artifact).units if u.identity == match[2]), None)
    if unit is None or unit.page != int(match[1]):
        raise SourceReferenceError("Unknown, foreign or wrong-page source block.")
    # Reader parsing strips anchor edges, but may not rewrite the selected block's contents.
    if not quote.strip() or artifact.text[unit.start : unit.end].strip() != quote.strip():
        raise SourceReferenceError("Quote does not match the selected source block.")
    return unit


def resolve_reader_evidence(
    payload: object,
    artifact: Artifact,
    *,
    require_references: bool,
) -> object:
    """Adapt source selections to existing EvidenceAnchor inputs; old records remain readable."""
    index = build_source_index(artifact)

    def evidence(value: object) -> object:
        if not isinstance(value, list):
            if require_references:
                raise SourceReferenceError("Evidence must be an array of source selections.")
            return value
        result = []
        for item in value:
            if isinstance(item, dict) and any(key in item for key in ("source_id", "start", "end")):
                result.append(index.resolve(item))
            elif require_references:
                raise SourceReferenceError(
                    "Fresh Reader evidence must select source IDs, not quotes."
                )
            else:
                result.append(item)
        return result

    def visit(value: object) -> object:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {
                key: evidence(item)
                if key in ("evidence", "evidence_index", "experiment_evidence")
                else visit(item)
                for key, item in value.items()
            }
        return value

    return visit(payload)
