"""Shared figure rules for public archive export and rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping


def figure_source(figure: Mapping[str, object]) -> str:
    """Return the run-local source path recorded for an archive figure."""

    return str(figure.get("relative_path") or figure.get("asset_path") or "").strip()


def is_pdf_page_fallback_figure(figure: Mapping[str, object]) -> bool:
    """Return whether a legacy figure is a full PDF page rather than a crop."""

    original_path = str(figure.get("original_path") or "").strip()
    if re.fullmatch(r"page\s+\d+", original_path, flags=re.IGNORECASE):
        return True
    source_path = figure_source(figure)
    return bool(re.search(r"(?:^|/)\d{2}-page-\d+\.png$", source_path))
