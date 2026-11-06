"""Positioned PDF table excerpts; geometry may bind cells, never approve their meaning."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import replace
from pathlib import Path
from statistics import median

from research_radar.analysis.figures import PdfPageBbox, PdfPageBboxReader, PdfTextWord
from research_radar.analysis.source_references import SourceReferenceError, selected_source_unit
from research_radar.evidence.quotes import QuoteMatch, find_quote
from research_radar.models import Artifact

_VALUE = re.compile(r"[+−-]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?%?\Z")
_CAPTION = re.compile(r"^Table\s+(\d+)[.:]\s", re.IGNORECASE)
_TABLE_EVIDENCE_VERSION = 3


def _box(words: list[PdfTextWord]) -> list[float]:
    return [min(w.x_min for w in words), min(w.y_min for w in words),
            max(w.x_max for w in words), max(w.y_max for w in words)]


def _lines(page: PdfPageBbox) -> list[list[PdfTextWord]]:
    lines: list[list[PdfTextWord]] = []
    for word in sorted(page.words, key=lambda w: ((w.y_min + w.y_max) / 2, w.x_min)):
        values = (word.x_min, word.y_min, word.x_max, word.y_max)
        if (not all(math.isfinite(v) for v in values)
                or not 0 <= word.x_min < word.x_max <= page.width
                or not 0 <= word.y_min < word.y_max <= page.height):
            return []
        middle = (word.y_min + word.y_max) / 2
        if lines and abs(middle - median((w.y_min + w.y_max) / 2 for w in lines[-1])) < (
            min(word.y_max - word.y_min, lines[-1][0].y_max - lines[-1][0].y_min) / 3
        ):
            lines[-1].append(word)
        else:
            lines.append([word])
    attached = set()
    for i, line in enumerate(lines):
        if not all(w.text in {"*", "∗", "†", "‡"} for w in line):
            continue
        neighbours = [j for j, row in enumerate(lines) if j != i and any(
            w.text[:1].isalnum() for w in row) and all(any(
                word.y_min < mark.y_max and mark.y_min < word.y_max
                and -(mark.x_max - mark.x_min) / 2 <= mark.x_min - word.x_max
                <= word.y_max - word.y_min
                and mark.y_max - mark.y_min < word.y_max - word.y_min
                for word in row) for mark in line)]
        if len(neighbours) == 1:
            lines[neighbours[0]].extend(line)
            attached.add(i)
    return [sorted(line, key=lambda w: w.x_min)
            for i, line in enumerate(lines) if i not in attached]


def _text(words: list[PdfTextWord]) -> str:
    return " ".join(w.text for w in words)


def _data(words: list[PdfTextWord]) -> tuple[list[PdfTextWord], list[PdfTextWord]] | None:
    # Recognize malformed numeric tokens too, without treating page labels (111:19) as cells.
    first = next((i for i, w in enumerate(words)
                  if re.fullmatch(r"[+−-]?\d[\d.,eE+−%-]*", w.text)), None)
    if first is None or first == 0:
        return None
    tail = words[first:]
    # Keep malformed numeric tails in the region so they cannot disappear from the grid.
    if not all(w.text[:1].isdigit() or w.text[:1] in "+−-" for w in tail):
        return None
    return words[:first], tail


def positioned_tables(page: PdfPageBbox, *, physical_page: int) -> list[dict]:
    """Resolve regular numeric grids with literal headers, or record an unresolved region."""
    lines = _lines(page)
    results = _page_tables(lines, physical_page=physical_page)
    # A line crossing the page gutter is not one table row or one caption.
    regions: dict[tuple[float, float], set[str]] = {}
    for line in lines:
        chunks: list[list[PdfTextWord]] = [[]]
        for word in line:
            if chunks[-1] and word.x_min - chunks[-1][-1].x_max > max(
                15, (word.y_max - word.y_min) * 1.5,
            ):
                chunks.append([])
            chunks[-1].append(word)
        for chunk in chunks:
            match = _CAPTION.match(_text(chunk))
            if not match:
                continue
            left, _, right, _ = _box(chunk)
            middle = page.width / 2
            bounds = ((0, middle) if right < middle else
                      (middle, page.width) if left > middle else None)
            if bounds:
                regions.setdefault(bounds, set()).add(f"Table {match[1]}")
    for (left, right), labels in regions.items():
        column = replace(page, words=[w for w in page.words
                                     if left <= w.x_min and w.x_max <= right])
        for candidate in _page_tables(_lines(column), physical_page=physical_page,
                                      caption_labels=labels):
            label = candidate["label"]
            if label not in labels or any(r["label"] == label and r["binding"] == "positioned"
                                         for r in results):
                continue
            results = [r for r in results if r["label"] != label]
            results.append({**candidate, "column_bounds": [left, right]})
    return results


def _page_tables(
    lines: list[list[PdfTextWord]], *, physical_page: int,
    caption_labels: set[str] | None = None,
) -> list[dict]:
    """Detect tables within one original-coordinate region; never join page columns."""
    # A cropped crossing caption must not consume a grid before output filtering.
    captions = [(i, f"Table {m[1]}") for i, line in enumerate(lines)
                if (m := _CAPTION.match(_text(line)))
                and (caption_labels is None or f"Table {m[1]}" in caption_labels)]
    blocks: list[list[int]] = []
    current: list[int] = []
    for i, line in enumerate(lines):
        data = _data(line)
        if data:
            if current and line[0].y_min - lines[current[-1]][0].y_max > 30:
                blocks.append(current)
                current = []
            current.append(i)
        elif current:
            label, _ = _data(lines[current[-1]])
            if max(w.x_max for w in line) < min(w.x_min for w in label):
                continue  # Vertically merged row-group labels, not a new table.
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    results = []
    assigned: set[int] = set()
    for caption_index, label in captions:
        caption = _box(lines[caption_index])
        distances = sorted((
            min(abs(caption[1] - _box(lines[b[-1]])[3]),
                abs(_box(lines[b[0]])[1] - caption[3])), j
        ) for j, b in enumerate(blocks))
        record = {"label": label, "physical_page": physical_page,
                  "caption": _text(lines[caption_index]), "binding": "unresolved",
                  "complete_grid": False, "cells": []}
        if (not distances or distances[0][0] > 80
                or distances[0][1] in assigned
                or (len(distances) > 1 and abs(distances[1][0] - distances[0][0]) < 1)):
            results.append(record)
            continue
        j = distances[0][1]
        assigned.add(j)
        results.append(_bind_grid(record, lines, blocks[j], caption_index))
    return results


def _bind_grid(
    record: dict, lines: list[list[PdfTextWord]], block: list[int], caption: int,
) -> dict:
    multi = [i for i in block if len(_data(lines[i])[1]) > 1]
    if multi:
        label_left = min(w.x_min for i in multi for w in _data(lines[i])[0])
        # A versioned dataset name can contain a number, but sits left of method rows.
        block = [i for i in block if max(w.x_max for w in lines[i]) >= label_left]
    rows = [_data(lines[i]) for i in block]
    counts = {len(values) for _, values in rows}
    if (len(counts) != 1 or len(rows) < 2
            or any(not _VALUE.fullmatch(w.text) and w.text != "-"
                   for _, values in rows for w in values)):
        return {**record, "reason": "incomplete or inseparable numeric cells"}
    count = next(iter(counts))
    centers = [median((values[c].x_min + values[c].x_max) / 2 for _, values in rows)
               for c in range(count)]
    if any(b <= a for a, b in zip(centers, centers[1:], strict=False)):
        return record
    if count == 1:
        label_right = max(w.x_max for labels, _ in rows for w in labels)
        value_left = min(values[0].x_min for _, values in rows)
        if value_left <= label_right:
            return {**record, "reason": "overlapping attribute and value columns"}
        cuts = [(label_right + value_left) / 2,
                max(values[0].x_max + values[0].y_max - values[0].y_min for _, values in rows)]
    else:
        cuts = [centers[0] - (centers[1] - centers[0]) / 2]
        cuts += [(a + b) / 2 for a, b in zip(centers, centers[1:], strict=False)]
        cuts += [centers[-1] + (centers[-1] - centers[-2]) / 2]
    if any(not cuts[c] < (w.x_min + w.x_max) / 2 < cuts[c + 1]
           for _, values in rows for c, w in enumerate(values)):
        return {**record, "reason": "ambiguous cell columns"}
    first = block[0]
    header_indices = []
    for i in range(first - 1, -1, -1):
        text = _text(lines[i])
        if (i == caption or _CAPTION.match(text) or re.match(r"(?:Figure|Fig\.)\s+\d", text)
                or _data(lines[i])
                or lines[first][0].y_min - lines[i][0].y_max > 100
                or lines[i + 1][0].y_min - lines[i][0].y_max > max(
                    20, 2 * (lines[i][0].y_max - lines[i][0].y_min))):
            break
        header_indices.insert(0, i)
    columns: list[list[str]] = [[] for _ in centers]
    header_boxes: list[list[dict]] = [[] for _ in centers]
    for i in header_indices:
        for c in range(count):
            words = [w for w in lines[i]
                     if min(w.x_max, cuts[c + 1]) - max(w.x_min, cuts[c])
                     >= (w.x_max - w.x_min) * 0.15]
            if words:
                columns[c].append(_text(words))
                header_boxes[c].append({"text": _text(words), "box": _box(words)})
    if any(not column for column in columns) or len({tuple(c) for c in columns}) != count:
        return {**record, "reason": "missing or ambiguous column headers"}
    label_left = min(w.x_min for label, _ in rows for w in label)
    groups = [lines[i] for i in range(block[0], block[-1] + 1)
              if i not in block and max(w.x_max for w in lines[i]) < label_left]
    group_centers = [(_box(g)[1] + _box(g)[3]) / 2 for g in groups]
    cells = []
    for row_index, (labels, values) in zip(block, rows, strict=True):
        row_headers = [_text(labels)]
        row_boxes = [{"text": _text(labels), "box": _box(labels)}]
        if groups:
            middle = (_box(lines[row_index])[1] + _box(lines[row_index])[3]) / 2
            nearest = min(range(len(groups)), key=lambda n: abs(middle - group_centers[n]))
            group = groups[nearest]
            row_headers.insert(0, _text(group))
            row_boxes.insert(0, {"text": _text(group), "box": _box(group)})
        for c, word in enumerate(values):
            cells.append({"row_headers": row_headers, "column_headers": columns[c],
                          "value": word.text, "box": _box([word]),
                          "row_header_boxes": row_boxes, "column_header_boxes": header_boxes[c]})
    return {**record, "binding": "positioned", "complete_grid": True, "cells": cells,
            "header_lines": [_text(lines[i]) for i in header_indices],
            "caption_above": caption < block[0],
            "footer_prefix": [w.text for w in lines[block[-1] + 1][:2]]
                if block[-1] + 1 < len(lines) else [],
            "box": _box([w for i in block + header_indices + [caption] for w in lines[i]])}


def attach_table_evidence(
    artifact: Artifact, *, page_reader: PdfPageBboxReader | None = None,
) -> Artifact:
    """Supplement unchanged PDF text with tables; unavailable layout stays unknown."""
    if artifact.content_type != "application/pdf" or not artifact.artifact_path:
        return artifact
    path = Path(artifact.artifact_path)
    if not path.is_file():
        return artifact
    if page_reader is None:
        from research_radar.analysis.figures import read_pdf_page_bbox
        page_reader = read_pdf_page_bbox
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    text_digest = hashlib.sha256(artifact.text.encode()).hexdigest()
    cache_identity = [digest, text_digest, _TABLE_EVIDENCE_VERSION]
    if artifact.metadata.get("table_evidence_identity") == cache_identity:
        return artifact
    pages = []
    current = 1
    for line in artifact.text.splitlines():
        if match := re.fullmatch(r"\[page (\d+)\]", line):
            current = int(match[1])
        if _CAPTION.match(line) and current not in pages:
            pages.append(current)
    tables = []
    for page_number in pages:
        page = page_reader(path, page_number)
        if page is None:
            continue
        for table in positioned_tables(page, physical_page=page_number):
            if table["binding"] == "positioned":
                original_rows = _original_grid_rows(table, artifact.text)
                if original_rows is None:
                    table = {**table, "binding": "unresolved", "complete_grid": False, "cells": [],
                             "reason": "positioned grid and original text rows disagree"}
                else:
                    table = {**table, "source_rows": original_rows}
            provenance = {"source_url": artifact.source.url, "document_sha256": digest,
                          "source_text_sha256": text_digest, **table}
            identity = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
            tables.append({"table_id": "table-" + identity, **provenance,
                           "cells": [{"cell_id": f"c{i}", **cell}
                                     for i, cell in enumerate(table["cells"], 1)]})
    return replace(artifact, metadata={**artifact.metadata,
        "table_evidence_identity": cache_identity, "table_evidence": tables})


def _original_grid_rows(table: dict, text: str) -> list[dict] | None:
    """Account for every original body line, including lines no numeric parser can read."""
    markers = list(re.finditer(r"(?m)^\[page (\d+)\]\s*\n", text))
    pages = [i for i, marker in enumerate(markers)
             if int(marker[1]) == table["physical_page"]]
    if len(pages) != 1 or not table["header_lines"]:
        return None
    index = pages[0]
    page_start = markers[index].end()
    page_end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
    lines, spans, offset = [], [], page_start
    for raw in text[page_start:page_end].splitlines(keepends=True):
        lines.append(raw.rstrip("\r\n"))
        spans.append((offset, offset + len(raw.rstrip("\r\n"))))
        offset += len(raw)
    captions = [i for i, line in enumerate(lines)
                if (m := _CAPTION.match(line)) and f"Table {m[1]}" == table["label"]]
    if len(captions) != 1:
        return None
    caption = captions[0]
    previous = max((i for i in range(caption) if _CAPTION.match(lines[i])), default=-1)
    following = next((i for i in range(caption + 1, len(lines)) if _CAPTION.match(lines[i])),
                     len(lines))
    candidates = (range(caption + 1, following) if table["caption_above"]
                  else range(previous + 1, caption))
    header = "".join(table["header_lines"][-1].split())
    headers = [i for i in candidates if "".join(lines[i].split()) == header]
    if len(headers) != 1:
        return None
    first = headers[0] + 1
    end = caption if not table["caption_above"] else following
    footer = "".join(table["footer_prefix"])
    if table["caption_above"] and footer:
        end = next((i for i in range(first, end)
                    if "".join(lines[i].split()).startswith(footer)), end)
    rows: dict[tuple[str, ...], list[tuple[int, dict]]] = {}
    for i, cell in enumerate(table["cells"], 1):
        rows.setdefault(tuple(cell["row_headers"]), []).append((i, cell))
    groups = {"".join(group.split()) for row in rows for group in row[:-1]}
    original = [i for i in range(first, end)
                if lines[i].strip() and "".join(lines[i].split()) not in groups]
    if len(original) != len(rows):
        return None
    result = []
    for i, (row, cells) in zip(original, rows.items(), strict=True):
        values = [cell["value"] for _, cell in cells]
        expected = {"".join(" ".join([*parts, *values]).split()) for parts in (row, [row[-1]])}
        if "".join(lines[i].split()) not in expected:
            return None
        result.append({"start": spans[i][0], "end": spans[i][1], "text": lines[i],
                       "row_headers": list(row), "cell_ids": [f"c{n}" for n, _ in cells]})
    return result


def quoted_table_context(
    artifact: Artifact, quote: str, context: str, page: int | None,
    *, location: str | None = None,
) -> dict | None:
    """Select geometric rows only when their unchanged glyph sequence occurs in this quote."""
    try:
        unit = selected_source_unit(artifact, quote, location)
    except SourceReferenceError:
        return None
    if unit is not None:
        if page is not None and page != unit.page:
            return None
        page = unit.page
    labels = {f"Table {m[1]}" for m in re.finditer(r"\bTable\s+(\d+)[.:]", context)}
    candidates = [t for t in artifact.metadata.get("table_evidence", [])
                  if t["binding"] == "positioned" and t["physical_page"] == page
                  and t["label"] in labels and t["source_url"] == artifact.source.url
                  and t["source_text_sha256"] == hashlib.sha256(artifact.text.encode()).hexdigest()]
    match = (find_quote(quote, artifact.text) if unit is None
             else QuoteMatch(unit.start, unit.end, "source_block"))
    if match is None:
        return None
    matches = []
    for table in candidates:
        selected = [cell_id for row in table["source_rows"]
                    if match.start <= row["start"] and row["end"] <= match.end
                    for cell_id in row["cell_ids"]]
        if selected:
            matches.append({"table": table, "selected_cell_ids": selected})
    return matches[0] if len(matches) == 1 else None
