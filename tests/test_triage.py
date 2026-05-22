from research_radar.analysis.triage import heuristic_claims
from research_radar.models import Artifact, SourceCandidate, SourceType


def test_heuristic_claims_skip_web_search_snippets() -> None:
    web_source = SourceCandidate(
        title="Agent memory web result",
        url="https://example.com/agent-memory",
        source_type=SourceType.WEB,
        source_name="web_search",
    )
    paper_source = SourceCandidate(
        title="Agent memory paper",
        url="https://arxiv.org/abs/2604.01707",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )

    claims = heuristic_claims(
        [
            Artifact(
                source=web_source,
                text="A web-search snippet about agent memory.",
                content_type="discovery-summary",
            ),
            Artifact(
                source=paper_source,
                text="A paper abstract about agent memory.",
                content_type="discovery-summary",
            ),
        ]
    )

    assert len(claims) == 1
    assert claims[0].evidence[0].source_url == "https://arxiv.org/abs/2604.01707"
