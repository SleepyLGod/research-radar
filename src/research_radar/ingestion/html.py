"""HTML ingestion and simple main-text extraction."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.request import Request, urlopen

from research_radar.exceptions import IngestionError
from research_radar.models import Artifact, SourceCandidate


class TextExtractingHTMLParser(HTMLParser):
    """Small HTML-to-text extractor that ignores scripts and styles."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track tags that should be ignored."""

        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Leave ignored tags."""

        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        """Collect visible text."""

        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        """Return normalized extracted text."""

        return "\n".join(line.strip() for line in " ".join(self.parts).splitlines() if line.strip())


def ingest_html(source: SourceCandidate) -> Artifact:
    """Download and extract a web page."""

    request = Request(source.url, headers={"User-Agent": "ResearchRadar/0.0.0"})
    try:
        with urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise IngestionError(f"Failed to download HTML source: {source.url}") from exc
    parser = TextExtractingHTMLParser()
    parser.feed(html)
    text = parser.text()
    if not text:
        raise IngestionError(f"No text extracted from HTML source: {source.url}")
    return Artifact(source=source, text=text, content_type="text/html")
