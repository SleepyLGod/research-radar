from research_radar.ingestion.pdf import _pdf_url
from research_radar.models import SourceCandidate, SourceType


def test_pdf_url_prefers_metadata_pdf_url() -> None:
    source = SourceCandidate(
        title="Paper",
        url="https://www.semanticscholar.org/paper/example",
        source_type=SourceType.PAPER,
        source_name="semantic_scholar",
        metadata={"pdf_url": "https://example.com/paper.pdf"},
    )

    assert _pdf_url(source) == "https://example.com/paper.pdf"


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
