import json
from pathlib import Path

from research_radar.models import SourceCandidate, SourceType
from research_radar.storage.files import read_jsonl
from research_radar.storage.source_history import (
    annotate_source_history,
    is_reportable_source,
    source_family_key,
    source_family_keys,
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
    assert history_rows[0]["family_keys"][0] == "arxiv:2604.01707"
    assert first_report["appended_count"] == 1


def test_source_history_marks_semantic_scholar_mirror_seen_after_arxiv(
    tmp_path: Path,
) -> None:
    title = "SuperLocalMemory V3.3: Biologically Inspired Agent Memory Systems"
    arxiv = _paper(
        "https://arxiv.org/abs/2604.04514v1",
        "2604.04514v1",
        title=title,
        source_name="arxiv",
    )
    semantic = _paper(
        "https://www.semanticscholar.org/paper/b8db259beccaeb20365a18a1a9373d966aa0fa46",
        "CorpusId:b8db259beccaeb20365a18a1a9373d966aa0fa46",
        title=title,
        source_name="semantic_scholar",
    )

    annotated_first, _ = annotate_source_history(
        tmp_path,
        "agent-memory",
        [arxiv],
        run_id="run-1",
    )
    annotated_second, report = annotate_source_history(
        tmp_path,
        "agent-memory",
        [semantic],
        run_id="run-2",
    )

    assert annotated_first[0].metadata["source_history"]["status"] == "new"
    assert annotated_second[0].metadata["source_history"]["status"] == "seen"
    assert not is_reportable_source(annotated_second[0])
    family_keys = annotated_second[0].metadata["source_history"]["family_keys"]
    assert family_keys[0].startswith("title:superlocalmemory-v3-3")
    assert "corpusid:b8db259beccaeb20365a18a1a9373d966aa0fa46" in family_keys
    assert report["omitted_seen_sources"][0]["family_keys"] == family_keys
    history_rows = read_jsonl(tmp_path / "data" / "source_history" / "agent-memory.jsonl")
    assert len(history_rows) == 1


def test_source_history_reads_legacy_single_family_key_rows(tmp_path: Path) -> None:
    history_path = tmp_path / "data" / "source_history" / "agent-memory.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        json.dumps(
            {
                "event": "new",
                "family_key": "arxiv:2604.01707",
                "latest_version": "v1",
                "run_id": "old-run",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    annotated, _ = annotate_source_history(
        tmp_path,
        "agent-memory",
        [_paper("http://arxiv.org/abs/2604.01707v1", "2604.01707v1")],
        run_id="run-2",
    )

    assert annotated[0].metadata["source_history"]["status"] == "seen"


def test_source_history_seeds_arxiv_version_after_mirror_first(
    tmp_path: Path,
) -> None:
    title = "SuperLocalMemory V3.3: Biologically Inspired Agent Memory Systems"
    semantic = _paper(
        "https://www.semanticscholar.org/paper/b8db259beccaeb20365a18a1a9373d966aa0fa46",
        "CorpusId:b8db259beccaeb20365a18a1a9373d966aa0fa46",
        title=title,
        source_name="semantic_scholar",
    )

    annotate_source_history(tmp_path, "agent-memory", [semantic], run_id="run-1")
    annotated_v1, _ = annotate_source_history(
        tmp_path,
        "agent-memory",
        [
            _paper(
                "https://arxiv.org/abs/2604.04514v1",
                "2604.04514v1",
                title=title,
                source_name="arxiv",
            )
        ],
        run_id="run-2",
    )
    annotated_v2, report_v2 = annotate_source_history(
        tmp_path,
        "agent-memory",
        [
            _paper(
                "https://arxiv.org/abs/2604.04514v2",
                "2604.04514v2",
                title=title,
                source_name="arxiv",
            )
        ],
        run_id="run-3",
    )

    assert annotated_v1[0].metadata["source_history"]["status"] == "seen"
    assert annotated_v2[0].metadata["source_history"]["status"] == "version_update"
    assert report_v2["counts"]["version_update"] == 1
    rows = read_jsonl(tmp_path / "data" / "source_history" / "agent-memory.jsonl")
    assert [row["event"] for row in rows] == ["new", "alias_refresh", "version_update"]
    assert rows[1]["latest_version"] == "v1"
    assert rows[1]["family_key"] == "arxiv:2604.04514"
    assert "title:superlocalmemory-v3-3-biologically-inspired-agent-memory-systems" in rows[1][
        "family_keys"
    ]


def test_source_family_key_normalizes_doi() -> None:
    source = _paper("https://doi.org/10.48550/arXiv.2504.04062", "DOI:10.48550/arXiv.2504.04062")

    assert source_family_key(source) == "arxiv:2504.04062"


def test_source_family_key_does_not_treat_plain_doi_suffix_as_arxiv() -> None:
    source = _paper("https://doi.org/10.1234/2504.04062", "DOI:10.1234/2504.04062")

    assert source_family_key(source) == "doi:10.1234/2504.04062"


def test_source_family_keys_include_paper_title_alias() -> None:
    source = _paper(
        "https://www.semanticscholar.org/paper/abc",
        "CorpusId:abc",
        title="Memory in the LLM Era",
        source_name="semantic_scholar",
    )

    assert source_family_keys(source) == [
        "title:memory-in-the-llm-era",
        "corpusid:abc",
    ]


def _paper(
    url: str,
    canonical_id: str,
    *,
    title: str = "Memory in the LLM Era",
    source_name: str = "arxiv",
) -> SourceCandidate:
    return SourceCandidate(
        title=title,
        url=url,
        canonical_id=canonical_id,
        source_type=SourceType.PAPER,
        source_name=source_name,
        summary="An agent memory benchmark paper.",
        metadata={"relevance": {"status": "relevant"}},
    )
