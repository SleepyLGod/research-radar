from research_radar.discovery.dedupe import dedupe_candidates, priority_score
from research_radar.models import SourceCandidate, SourceType


def test_dedupe_prefers_highest_score() -> None:
    low = SourceCandidate(
        title="Low",
        url="https://example.com/a/",
        source_type=SourceType.WEB,
        source_name="test",
        score=0.1,
    )
    high = SourceCandidate(
        title="High",
        url="https://example.com/a",
        source_type=SourceType.WEB,
        source_name="test",
        score=0.9,
    )

    assert dedupe_candidates([low, high]) == [high]


def test_priority_score_matches_subdomain() -> None:
    assert priority_score("https://export.arxiv.org/abs/1", ["arxiv.org"]) > 0
