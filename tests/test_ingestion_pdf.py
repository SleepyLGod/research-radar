from pathlib import Path

from research_radar.ingestion import router
from research_radar.ingestion.pdf import _pdf_url, has_pdf_signal
from research_radar.models import Artifact, SourceCandidate, SourceType


def test_pdf_url_prefers_metadata_pdf_url() -> None:
    source = SourceCandidate(
        title="Paper",
        url="https://www.semanticscholar.org/paper/example",
        source_type=SourceType.PAPER,
        source_name="semantic_scholar",
        metadata={"pdf_url": "https://example.com/paper.pdf"},
    )

    assert _pdf_url(source) == "https://example.com/paper.pdf"
    assert has_pdf_signal(source) is True


def test_pdf_url_uses_arxiv_external_id_from_semantic_scholar() -> None:
    source = SourceCandidate(
        title="QE-RAG",
        url="https://www.semanticscholar.org/paper/example",
        canonical_id="DOI:10.48550/arXiv.2504.04062",
        source_type=SourceType.PAPER,
        source_name="semantic_scholar",
        metadata={"external_ids": {"ArXiv": "2504.04062"}},
    )

    assert _pdf_url(source) == "https://arxiv.org/pdf/2504.04062.pdf"
    assert has_pdf_signal(source) is True


def test_router_sends_semantic_scholar_pdf_metadata_to_pdf_ingestion(monkeypatch) -> None:
    source = SourceCandidate(
        title="Paper",
        url="https://www.semanticscholar.org/paper/example",
        source_type=SourceType.PAPER,
        source_name="semantic_scholar",
        metadata={"pdf_url": "https://example.com/paper.pdf"},
    )
    calls = []

    def fake_ingest_pdf(candidate: SourceCandidate, artifact_dir: Path) -> Artifact:
        calls.append(("pdf", candidate.url))
        return Artifact(source=candidate, text="pdf")

    def fake_ingest_html(candidate: SourceCandidate) -> Artifact:
        calls.append(("html", candidate.url))
        return Artifact(source=candidate, text="html")

    monkeypatch.setattr(router, "ingest_pdf", fake_ingest_pdf)
    monkeypatch.setattr(router, "ingest_html", fake_ingest_html)

    artifact = router.ingest_source(source, Path("/tmp/artifacts"))

    assert artifact.text == "pdf"
    assert calls == [("pdf", source.url)]


def test_router_sends_semantic_scholar_page_without_pdf_to_html_ingestion(monkeypatch) -> None:
    source = SourceCandidate(
        title="Paper",
        url="https://www.semanticscholar.org/paper/example",
        source_type=SourceType.PAPER,
        source_name="semantic_scholar",
    )
    calls = []

    def fake_ingest_pdf(candidate: SourceCandidate, artifact_dir: Path) -> Artifact:
        calls.append(("pdf", candidate.url))
        return Artifact(source=candidate, text="pdf")

    def fake_ingest_html(candidate: SourceCandidate) -> Artifact:
        calls.append(("html", candidate.url))
        return Artifact(source=candidate, text="html")

    monkeypatch.setattr(router, "ingest_pdf", fake_ingest_pdf)
    monkeypatch.setattr(router, "ingest_html", fake_ingest_html)

    artifact = router.ingest_source(source, Path("/tmp/artifacts"))

    assert artifact.text == "html"
    assert calls == [("html", source.url)]


def test_router_sends_arxiv_abs_url_to_pdf_ingestion(monkeypatch) -> None:
    source = SourceCandidate(
        title="Paper",
        url="https://arxiv.org/abs/2604.01707",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    calls = []

    def fake_ingest_pdf(candidate: SourceCandidate, artifact_dir: Path) -> Artifact:
        calls.append(("pdf", candidate.url))
        return Artifact(source=candidate, text="pdf")

    def fake_ingest_html(candidate: SourceCandidate) -> Artifact:
        calls.append(("html", candidate.url))
        return Artifact(source=candidate, text="html")

    monkeypatch.setattr(router, "ingest_pdf", fake_ingest_pdf)
    monkeypatch.setattr(router, "ingest_html", fake_ingest_html)

    artifact = router.ingest_source(source, Path("/tmp/artifacts"))

    assert artifact.text == "pdf"
    assert calls == [("pdf", source.url)]
