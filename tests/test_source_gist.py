from research_radar.analysis.providers import StaticProvider
from research_radar.analysis.source_gist import attach_source_gists, deterministic_source_gist
from research_radar.models import SourceCandidate, SourceType


def test_deterministic_source_gist_is_not_raw_abstract_slice() -> None:
    source = _source(
        summary=(
            "This paper proposes a retrieval-centered memory architecture for LLM agents. "
            "It reports benchmark results."
        )
    )

    gist = deterministic_source_gist(source)

    assert gist != source.summary[:220]
    assert "retrieval-centered memory architecture" not in gist
    assert "treat the abstract's claims as leads" in gist


def test_model_source_gist_strips_generated_urls() -> None:
    provider = StaticProvider(
        '{"gists":[{"index":1,"gist":"A safe digest with https://fake.example/link removed."}]}'
    )

    [source] = attach_source_gists([_source()], provider=provider, model="fake")

    assert "https://fake.example" not in source.metadata["source_gist"]["text"]


def test_source_gist_can_use_chinese_language() -> None:
    gist = deterministic_source_gist(_source(), language="zh")

    assert "基于标题" in gist
    assert "摘要" in gist


def _source(summary: str = "A short abstract.") -> SourceCandidate:
    return SourceCandidate(
        title="Storage Is Not Memory: A Retrieval-Centered Architecture",
        url="https://arxiv.org/abs/2605.04897",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=summary,
        metadata={"source_role": {"role": "primary_paper"}},
    )
