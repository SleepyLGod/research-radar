"""Literal quote matching with PDF-noise tolerance and original-text offsets."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class QuoteMatch:
    """An end-exclusive match in the original text, never in a normalized copy."""

    start: int
    end: int
    kind: str


def find_quote(quote: str, text: str) -> QuoteMatch | None:
    """Find a literal quote, allowing layout noise but preserving numeric punctuation."""

    quote = quote.strip()
    if not quote:
        return None
    start = text.find(quote)
    if start >= 0:
        return QuoteMatch(start, start + len(quote), "exact")
    normalized_quote, _ = _normalized_view(quote)
    if not normalized_quote:
        return None
    normalized_text, positions = _normalized_view(text)
    start = normalized_text.find(normalized_quote)
    if start >= 0:
        return QuoteMatch(
            positions[start], positions[start + len(normalized_quote) - 1] + 1, "normalized"
        )
    compact_quote, _ = _compact_view(normalized_quote, range(len(normalized_quote)))
    if sum(char.isalnum() for char in compact_quote) < 12:
        return None
    compact_text, positions = _compact_view(normalized_text, positions)
    start = compact_text.find(compact_quote)
    if start < 0:
        return None
    return QuoteMatch(positions[start], positions[start + len(compact_quote) - 1] + 1, "compact")


def _normalized_view(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for raw_char, raw_index in _characters(text):
        if raw_char == "\xad" or (
            not raw_char.isspace() and (ord(raw_char) < 32 or 127 <= ord(raw_char) <= 159)
        ):
            continue
        for char in raw_char.casefold():
            if char.isspace():
                if not chars or chars[-1] == " ":
                    continue
                char = " "
            chars.append(char)
            positions.append(raw_index)
    if chars and chars[-1] == " ":
        chars.pop()
        positions.pop()
    return "".join(chars), positions


def _compact_view(text: str, positions: Sequence[int]) -> tuple[str, list[int]]:
    # Keep numeric separators: removing a table-cell space must not create a new number.
    items = [
        (char, positions[index])
        for index, char in enumerate(text)
        if not char.isspace()
        or (
            index > 0
            and index + 1 < len(text)
            and text[index - 1].isdigit()
            and text[index + 1].isdigit()
        )
    ]
    chars: list[str] = []
    offsets: list[int] = []
    for index, (char, raw_index) in enumerate(items):
        before_digit = index > 0 and items[index - 1][0].isdigit()
        after_digit = index + 1 < len(items) and items[index + 1][0].isdigit()
        numeric_punctuation = (
            (char == "." and after_digit)
            or (char in ",:'’" and before_digit and after_digit)
            or (char in "-‐‑–—" and (before_digit or after_digit))
        )
        if char.isspace() or char.isalnum() or char in "%+−±=<>≤≥×*/^" or numeric_punctuation:
            chars.append(char)
            offsets.append(raw_index)
    return "".join(chars), offsets


def _characters(text: str) -> Iterator[tuple[str, int]]:
    """Skip PDF line-wrap hyphenation while retaining each surviving raw offset."""

    index = 0
    while index < len(text):
        if (
            text[index] == "-"
            and index > 0
            and text[index - 1].isalpha()
            and index + 1 < len(text)
            and text[index + 1].isspace()
        ):
            next_index = index + 1
            while next_index < len(text) and text[next_index].isspace():
                next_index += 1
            if next_index < len(text) and text[next_index].isalpha():
                index = next_index
                continue
        yield text[index], index
        index += 1
