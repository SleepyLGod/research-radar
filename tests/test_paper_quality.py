from research_radar.ingestion.paper_quality import paper_text_quality
from research_radar.models import Artifact, SourceCandidate, SourceType


def _source() -> SourceCandidate:
    return SourceCandidate(
        title="Paper",
        url="https://openreview.net/forum?id=test",
        source_type=SourceType.PAPER,
        source_name="web_search",
    )


def test_abstract_only_html_fails_full_paper_quality() -> None:
    artifact = Artifact(
        source=_source(),
        text=(
            "Abstract\n"
            "This short OpenReview landing page describes an LLM serving paper but does not "
            "include the method, evaluation, or full body."
        ),
        content_type="text/html",
    )

    quality = paper_text_quality(artifact)

    assert quality["status"] == "fail"
    assert quality["reason"] == "artifact text is too short for full-paper deep reading"


def test_full_pdf_text_passes_full_paper_quality() -> None:
    body = "\n".join(
        [
            "[page 1]",
            "Abstract\nThis paper studies LLM serving systems.",
            "[page 2]",
            "Introduction\nLLM inference serving has prefill and decode phases.",
            "[page 3]",
            "MARS Design\nThe scheduler handles requests and API calls.",
            "Figure 1: MARS architecture overview.",
            "[page 4]",
            "Evaluation\nWe compare latency, TTFT, and throughput against baselines.",
            "Table 1: Workload setup.",
        ]
    )
    artifact = Artifact(
        source=_source(),
        text=body + "\n" + ("Additional full-paper text.\n" * 500),
        content_type="application/pdf",
        metadata={"page_count": 4},
    )

    quality = paper_text_quality(artifact)

    assert quality["status"] == "pass"
    assert quality["section_hits"]["method"] is True
    assert quality["section_hits"]["experiments_results"] is True
    assert quality["figure_caption_count"] == 1
    assert quality["table_caption_count"] == 1


def test_unknown_fixture_artifact_is_not_gated() -> None:
    artifact = Artifact(
        source=_source(),
        text="Short fake test fixture.",
        content_type=None,
    )

    quality = paper_text_quality(artifact)

    assert quality["status"] == "pass"
    assert "not subject" in str(quality["reason"])
