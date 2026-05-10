"""PDF ingestion."""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

from research_radar.exceptions import IngestionError
from research_radar.models import Artifact, SourceCandidate
from research_radar.storage.files import ensure_dir


def ingest_pdf(source: SourceCandidate, artifact_dir: Path) -> Artifact:
    """Download and extract text from a PDF source."""

    ensure_dir(artifact_dir)
    pdf_url = _pdf_url(source.url)
    filename = (source.canonical_id or source.title).replace("/", "-").replace(" ", "_")[:120]
    path = artifact_dir / f"{filename}.pdf"
    request = Request(pdf_url, headers={"User-Agent": "ResearchRadar/0.0.0"})
    try:
        with urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    except OSError as exc:
        raise IngestionError(f"Failed to download PDF source: {source.url}") from exc
    return extract_pdf(source, path)


def extract_pdf(source: SourceCandidate, path: Path) -> Artifact:
    """Extract text from an existing PDF file."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestionError("Install pypdf to ingest PDF files.") from exc
    try:
        reader = PdfReader(str(path))
        page_text = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                page_text.append(f"[page {index}]\n{text.strip()}")
    except Exception as exc:  # pypdf raises several specific parser exceptions.
        raise IngestionError(f"Failed to parse PDF: {path}") from exc
    if not page_text:
        raise IngestionError(f"No text extracted from PDF: {path}")
    return Artifact(
        source=source,
        text="\n\n".join(page_text),
        artifact_path=str(path),
        content_type="application/pdf",
        metadata={"page_count": len(page_text)},
    )


def _pdf_url(url: str) -> str:
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/") + ".pdf"
    return url
