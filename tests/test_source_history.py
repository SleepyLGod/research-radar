from pathlib import Path

from research_radar.models import SourceCandidate, SourceType
from research_radar.storage.files import read_jsonl
from research_radar.storage.source_history import (
    annotate_source_history,
    is_reportable_source,
    source_family_key,
)


def test_source_history_tracks_new_seen_and_version_update(tmp_path: Path) -> None:
    first = _paper("http://arxiv.org/abs/2604.01707v1", "2604.01707v1")
    annotated_first, first_report = annotate_source_history(
        tmp_path,
        "agent-memory",
        [first],
        run_id="run-1",
    )

    annotated_seen, seen_report = annotate_source_history(
        tmp_path,
        "agent-memory",
        [_paper("http://arxiv.org/abs/2604.01707v1", "2604.01707v1")],
        run_id="run-2",
    )

    annotated_update, update_report = annotate_source_history(
        tmp_path,
        "agent-memory",
        [_paper("http://arxiv.org/abs/2604.01707v2", "2604.01707v2")],
        run_id="run-3",
    )

    assert annotated_first[0].metadata["source_history"]["status"] == "new"
    assert annotated_seen[0].metadata["source_history"]["status"] == "seen"
    assert annotated_update[0].metadata["source_history"]["status"] == "version_update"
    assert not is_reportable_source(annotated_seen[0])
    assert is_reportable_source(annotated_update[0])
    assert seen_report["omitted_seen_sources"][0]["family_key"] == "arxiv:2604.01707"
    assert update_report["counts"]["version_update"] == 1
    history_rows = read_jsonl(tmp_path / "data" / "source_history" / "agent-memory.jsonl")
    assert [row["event"] for row in history_rows] == ["new", "version_update"]
    assert first_report["appended_count"] == 1


def test_source_family_key_normalizes_doi() -> None:
    source = _paper("https://doi.org/10.48550/arXiv.2504.04062", "DOI:10.48550/arXiv.2504.04062")

    assert source_family_key(source) == "arxiv:2504.04062"


def test_source_family_key_does_not_treat_plain_doi_suffix_as_arxiv() -> None:
    source = _paper("https://doi.org/10.1234/2504.04062", "DOI:10.1234/2504.04062")

    assert source_family_key(source) == "doi:10.1234/2504.04062"


def _paper(url: str, canonical_id: str) -> SourceCandidate:
    return SourceCandidate(
        title="Memory in the LLM Era",
        url=url,
        canonical_id=canonical_id,
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="An agent memory benchmark paper.",
        metadata={"relevance": {"status": "relevant"}},
    )
