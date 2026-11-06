"""Bounded literal table excerpts; no inferred cells or PDF table reconstruction."""

from __future__ import annotations

import re

_CELL = r"[+−-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?%?"
_CAPTION = re.compile(r"(?i)^table\s+\d+\b")


def numeric_row(line: str) -> tuple[str, list[str]] | None:
    """Return a literal row label and cells only for a regular numeric row."""

    if _CAPTION.match(line.strip()) or line.rstrip().endswith("."):
        return None
    boundary = re.search(r"\s+(?=" + _CELL + r"(?![\w.]))", line.strip())
    if boundary is None:
        return None
    label, cells = line.strip()[:boundary.start()], line.strip()[boundary.end():]
    if (not re.search(r"[A-Za-z]", label)
            or not re.fullmatch(_CELL + r"[\d\s.,%+−/()×±*eE-]*", cells)):
        return None
    return label, re.findall(_CELL, cells)


def table_source_context(
    text: str, start: int, end: int, *, limit: int = 1200,
) -> dict[str, object] | None:
    """Keep exact header/row/caption fragments within the quoted row's page and block."""

    lines = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        lines.append((offset, offset + len(line), line))
        offset += len(raw)
    touched = [i for i, (a, b, line) in enumerate(lines)
               if a < end and b > start and numeric_row(line)]
    if not touched:
        return None
    first, last = touched[0], touched[-1]
    crosses_blocks = any(line.strip() and not numeric_row(line)
                         for _, _, line in lines[first:last + 1])
    left, right = first, last + 1
    while left > 0 and numeric_row(lines[left - 1][2]):
        left -= 1
    while right < len(lines) and numeric_row(lines[right][2]):
        right += 1
    header_start = left
    for i in range(left - 1, -1, -1):
        line = lines[i][2].strip()
        if (not line or line.startswith("[page ") or numeric_row(line)
                or lines[left][0] - lines[i][0] > limit
                or re.match(r"(?:Figure|Fig\.)\s+\d+\b", line, re.IGNORECASE)):
            break
        if _CAPTION.match(line):
            # A caption immediately after rows belongs to the preceding table.
            if i == 0 or not numeric_row(lines[i - 1][2]):
                header_start = i
            break
        if re.match(r"\d+(?:\.\d+)*\s+[A-Z]", line) or line.endswith((".", ":", "?")):
            break
        header_start = i
    headers = [line for _, _, line in lines[header_start:left] if not _CAPTION.match(line)]
    caption_below = right < len(lines) and bool(_CAPTION.match(lines[right][2]))
    if not headers and header_start == left and not caption_below:
        return None
    ranges = []
    if header_start < left:
        ranges.append((lines[header_start][0], lines[left][0], "header"))
    row_start, row_end = lines[first][0], lines[last][1]
    overhead = sum(b - a for a, b, _ in ranges)
    if lines[right - 1][1] - lines[left][0] + overhead <= limit:
        row_start, row_end = lines[left][0], lines[right - 1][1]
    ranges.append((row_start, row_end, "rows"))
    if caption_below:
        ranges.append((lines[right][0], lines[right][1], "caption"))
    elif right < len(lines) and lines[right][2].endswith(".") and len(lines[right][2]) < 250:
        ranges.append((lines[right][0], lines[right][1], "adjacent_note"))
    # Do not silently truncate a header or row and then claim a complete binding.
    if sum(b - a for a, b, _ in ranges) > limit:
        return {"segments": [], "headers": [], "quoted_rows": [], "columns": [],
                "binding": "unresolved: table excerpts exceed context budget"}
    quoted = [line for a, b, line in lines[first:last + 1]
              if a < end and b > start and numeric_row(line)]
    counts = {len(row[1]) for line in quoted if (row := numeric_row(line))}
    columns: list[str] = []
    if len(counts) == 1 and not any(re.search(r"[/±]", line) for line in quoted):
        count = next(iter(counts))
        candidates = [line.split()[1:] for line in headers if len(line.split()) == count + 1]
        candidates = [c for c in candidates if len(set(c)) == len(c)]
        if len(candidates) == 1:
            columns = candidates[0]
    caption_above = header_start < left and bool(_CAPTION.match(lines[header_start][2]))
    if not columns and not caption_above and not caption_below:
        return None
    if crosses_blocks:
        return {"segments": [], "headers": [], "quoted_rows": [], "columns": [],
                "binding": "unresolved: quote spans source blocks",
                "error": "table quote spans multiple pages, headers or groups"}
    return {
        "segments": [{"start": a, "end": b, "text": text[a:b], "role": role}
                     for a, b, role in ranges],
        "headers": headers, "quoted_rows": quoted, "columns": columns,
        "binding": "literal single-header columns" if columns else "unresolved column layout",
    }
