from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    RelatedWorkAssessment,
)
from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.source_groups import group_source_entries
from research_radar.compose.wechat import compose_wechat_html, render_wechat_html
from research_radar.exceptions import PublishError
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, SourceCandidate, SourceType
from research_radar.storage.files import write_json


def test_wechat_html_uses_verified_claims_only() -> None:
    verified = Claim(
        text="Verified insight",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://example.com/paper",
                source_title="Paper",
                quote="Direct evidence",
                location="page 1",
            )
        ],
    )
    unsupported = Claim(text="Unsupported insight", status=ClaimStatus.UNSUPPORTED)

    html = compose_wechat_html("agent-memory", [verified, unsupported])

    assert "Verified insight" in html
    assert "Direct evidence" in html
    assert "Unsupported insight" not in html


def test_article_draft_loader_preserves_zero_confidence(tmp_path) -> None:
    draft = build_daily_draft(
        "agent-memory",
        [],
        [
            Claim(
                text="Zero-confidence audit fixture.",
                status=ClaimStatus.SUPPORTED,
                evidence=[
                    EvidenceAnchor(
                        source_url="https://example.com/paper",
                        quote="Zero-confidence audit fixture.",
                        confidence=0.0,
                    )
                ],
            )
        ],
    )
    path = tmp_path / "article_draft.json"
    write_json(path, draft)

    loaded = load_article_draft(path)

    assert loaded.claims[0].evidence[0].confidence == 0.0


def test_article_draft_loader_rejects_empty_required_fields(tmp_path) -> None:
    path = tmp_path / "article_draft.json"
    write_json(
        path,
        {
            "title": "",
            "topic_id": "agent-memory",
            "digest": "Digest",
            "lede": "Lede",
            "sections": [],
            "claims": [],
        },
    )

    try:
        load_article_draft(path)
    except PublishError as exc:
        assert "title" in str(exc)
    else:
        raise AssertionError("Expected PublishError")


def test_markdown_and_wechat_render_same_article_draft() -> None:
    claim = Claim(
        text="Same neutral draft",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Grounded")],
    )
    draft = build_weekly_draft("agent-memory", [claim])

    markdown = render_markdown(draft)
    html = render_wechat_html(draft)

    assert "Same neutral draft" in markdown
    assert "Same neutral draft" in html
    assert draft.topic_id == "agent-memory"


def test_daily_article_draft_excludes_downgraded_claims() -> None:
    source = SourceCandidate(
        title="Agent memory source",
        url="https://example.com/source",
        source_type=SourceType.PAPER,
        source_name="test",
    )
    supported = Claim(
        text="Supported daily claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/source", quote="Evidence")],
    )
    downgraded = Claim(
        text="Downgraded daily claim",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/source", quote="Evidence")],
    )

    draft = build_daily_draft("agent-memory", [source], [supported, downgraded])

    assert supported in draft.claims
    assert downgraded not in draft.claims


def test_daily_markdown_renders_source_links_with_colon_titles() -> None:
    source = SourceCandidate(
        title="Storage Is Not Memory: A Retrieval-Centered Architecture",
        url="https://arxiv.org/abs/2605.04897",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        published_at="2026-05-01",
        metadata={
            "source_role": {"role": "primary_paper"},
            "source_history": {"status": "new", "version": "v1"},
            "source_gist": {
                "text": "A conservative source-level digest with no raw abstract dump."
            },
        },
    )
    claim = Claim(
        text="Supported daily claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=source.url, quote="Evidence")],
    )

    markdown = render_markdown(build_daily_draft("agent-memory", [source], [claim]))

    assert (
        "- [Storage Is Not Memory: A Retrieval-Centered Architecture]"
        "(<https://arxiv.org/abs/2605.04897>)"
    ) in markdown
    assert "role=primary_paper, status=new, published=2026-05-01, version=v1" in markdown
    assert "raw abstract dump" in markdown


def test_daily_markdown_groups_sources_by_display_role() -> None:
    paper = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={"source_role": {"role": "primary_paper"}},
    )
    benchmark = SourceCandidate(
        title="Memory Benchmark",
        url="https://arxiv.org/abs/2605.00002",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={"source_role": {"role": "benchmark_paper"}},
    )
    repo = SourceCandidate(
        title="Memory Repo",
        url="https://github.com/example/memory-repo",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        metadata={"source_role": {"role": "implementation_repo"}},
    )
    web = SourceCandidate(
        title="Memory Blog",
        url="https://example.com/memory-blog",
        source_type=SourceType.WEB,
        source_name="tavily",
        metadata={"source_role": {"role": "blog_or_web"}},
    )

    markdown = render_markdown(
        build_daily_draft("agent-memory", [web, repo, benchmark, paper], [])
    )

    assert "### Research Papers" in markdown
    assert "### Benchmarks" in markdown
    assert "### Implementation / Repos" in markdown
    assert "### Web / Blog Context" in markdown
    assert markdown.index("### Research Papers") < markdown.index("Memory Paper")
    assert markdown.index("### Benchmarks") < markdown.index("Memory Benchmark")
    assert markdown.index("### Implementation / Repos") < markdown.index("Memory Repo")
    assert markdown.index("### Web / Blog Context") < markdown.index("Memory Blog")


def test_daily_markdown_keeps_survey_papers_in_research_papers() -> None:
    survey_paper = SourceCandidate(
        title="Agent Memory Survey",
        url="https://arxiv.org/abs/2605.00003",
        source_type=SourceType.PAPER,
        source_name="tavily",
        metadata={"source_role": {"role": "survey_or_list"}},
    )
    web_survey = SourceCandidate(
        title="Agent Memory Resources",
        url="https://example.com/agent-memory-resources",
        source_type=SourceType.WEB,
        source_name="tavily",
        metadata={"source_role": {"role": "survey_or_list"}},
    )

    markdown = render_markdown(
        build_daily_draft("agent-memory", [web_survey, survey_paper], [])
    )

    assert markdown.index("### Research Papers") < markdown.index("Agent Memory Survey")
    assert markdown.index("### Web / Blog Context") < markdown.index(
        "Agent Memory Resources"
    )


def test_wechat_html_groups_daily_sources() -> None:
    paper = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={"source_role": {"role": "primary_paper"}},
    )
    repo = SourceCandidate(
        title="Memory Repo",
        url="https://github.com/example/memory-repo",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        metadata={"source_role": {"role": "implementation_repo"}},
    )

    html = render_wechat_html(build_daily_draft("agent-memory", [repo, paper], []))

    assert "<h3>Research Papers</h3>" in html
    assert "<h3>Implementation / Repos</h3>" in html
    assert html.index("<h3>Research Papers</h3>") < html.index("Memory Paper")
    assert html.index("<h3>Implementation / Repos</h3>") < html.index("Memory Repo")


def test_unknown_source_group_falls_back_to_other() -> None:
    groups = group_source_entries(
        [
            {
                "title": "Unclassified source",
                "url": "https://example.com/source",
                "source_group": "future_group",
            }
        ]
    )

    assert groups[-1] == (
        "other",
        [
            {
                "title": "Unclassified source",
                "url": "https://example.com/source",
                "source_group": "future_group",
            }
        ],
    )


def test_daily_draft_strips_url_like_text_from_source_gist() -> None:
    source = SourceCandidate(
        title="Agent Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={
            "source_gist": {"text": "Read fabricated detail at https://evil.example/path"}
        },
    )

    markdown = render_markdown(build_daily_draft("agent-memory", [source], []))

    assert "https://evil.example" not in markdown
    assert "https://arxiv.org/abs/2605.00001" in markdown


def test_daily_markdown_supports_chinese_language() -> None:
    source = SourceCandidate(
        title="Agent Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={"source_gist": {"text": "这是一句保守的来源摘要。"}},
    )
    claim = Claim(
        text="Problem: 这篇论文讨论长期记忆。",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="long-term memory",
            )
        ],
    )

    draft = build_daily_draft("agent-memory", [source], [claim], language="zh")
    markdown = render_markdown(draft)
    html = render_wechat_html(draft)

    assert "# ResearchRadar 日报：agent-memory" in markdown
    assert "\nProblem:" not in markdown
    assert "\n问题：" in markdown
    assert "## 新增 / 更新来源" in markdown
    assert "### 研究论文" in markdown
    assert "摘要: 这是一句保守的来源摘要。" in markdown
    assert "证据链" in markdown
    assert "long-term memory" in markdown
    assert "ResearchRadar 日报：agent-memory" in html


def test_long_form_wechat_renders_toc_deep_reads_and_evidence_notes() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
    )

    html = render_wechat_html(draft)

    assert "Contents" in html
    assert "Deep Reads" in html
    assert "Other New / Updated Sources" in html
    assert "Evidence Notes" in html
    assert "Problem and Motivation" in html
    assert "Solution Mechanism" in html
    assert "Experiments" in html
    assert "Related Work" in html
    assert "Explicit limitations" in html
    assert "Plain-language Example" in html
    assert "Key Evidence" in html
    assert "rr-diagram" in html
    assert "Supported paper claim" in html


def test_long_form_wechat_keeps_unsupported_claims_out() -> None:
    source = _paper_source()
    supported = _supported_paper_claim(source)
    unsupported = Claim(
        text="Unsupported public claim",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[EvidenceAnchor(source_url=source.url, quote="Unsupported public claim")],
    )

    html = render_wechat_html(
        build_daily_draft(
            "agent-memory",
            [source],
            [supported, unsupported],
            readings=[_paper_reading(source.title)],
            deep_read_sources=[source],
        )
    )

    assert "Supported paper claim" in html
    assert "Unsupported public claim" not in html


def test_long_form_wechat_separates_deep_read_and_other_sources() -> None:
    deep_source = _paper_source()
    other_source = SourceCandidate(
        title="Follow-up benchmark",
        url="https://arxiv.org/abs/2605.00002",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={
            "source_role": {"role": "benchmark_paper"},
            "source_gist": {"text": "A benchmark to inspect later."},
        },
    )

    draft = build_daily_draft(
        "agent-memory",
        [deep_source, other_source],
        [_supported_paper_claim(deep_source)],
        readings=[_paper_reading(deep_source.title)],
        deep_read_sources=[deep_source],
    )

    deep_section = next(
        section for section in draft.sections if section.metadata["kind"] == "deep_reads"
    )
    other_section = next(
        section for section in draft.sections if section.metadata["kind"] == "new_updated_sources"
    )

    assert deep_section.metadata["deep_reads"][0]["source"]["title"] == deep_source.title
    assert all(source["title"] != deep_source.title for source in other_section.metadata["sources"])
    assert other_section.metadata["sources"][0]["title"] == other_source.title


def test_long_form_wechat_supports_no_new_papers_with_seen_sources() -> None:
    draft = build_daily_draft(
        "agent-memory",
        [],
        [],
        readings=[],
        deep_read_sources=[],
        seen_sources=[
            {
                "title": "Already read paper",
                "url": "https://arxiv.org/abs/2605.00003",
                "version": "v1",
            }
        ],
    )

    html = render_wechat_html(draft)
    markdown = render_markdown(draft)

    assert "No new paper or new version entered deep reading today" in html
    assert "Seen Before" in html
    assert "Already read paper" in html
    assert "Already read paper" in markdown


def test_long_form_chinese_uses_chinese_labels_and_preserves_quote() -> None:
    source = _paper_source()
    claim = Claim(
        text="Problem: 这篇论文讨论长期记忆。",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="long-term memory evidence",
                location="page 1",
            )
        ],
    )

    html = render_wechat_html(
        build_daily_draft(
            "agent-memory",
            [source],
            [claim],
            language="zh",
            readings=[_paper_reading(source.title)],
            deep_read_sources=[source],
        )
    )

    assert "目录" in html
    assert "今日精读" in html
    assert "问题与动机" in html
    assert "关键证据" in html
    assert "long-term memory evidence" in html


def _paper_source() -> SourceCandidate:
    return SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={
            "source_role": {"role": "primary_paper"},
            "source_gist": {"text": "This paper proposes a memory system for agents."},
        },
    )


def _supported_paper_claim(source: SourceCandidate) -> Claim:
    return Claim(
        text="Solution: Supported paper claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="Supported paper claim",
                location="page 2",
            )
        ],
    )


def _paper_reading(title: str) -> PaperReading:
    return PaperReading(
        title=title,
        area_context=AreaContext(
            background="Agent memory needs durable recall.",
            active_questions=["How should agents retrieve old facts?"],
            common_baselines=["Vector memory"],
        ),
        problem_solution=ProblemSolution(
            problem="Agents forget useful long-term context.",
            why_it_matters="Without durable memory, repeated tasks lose continuity.",
            hidden_assumptions=["The stored memory is trustworthy."],
            solution="The paper adds a structured memory layer.",
            mechanism="It retrieves, consolidates, and filters stored memories.",
            evidence=[],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=["MemGPT", "Zep"],
            novelty="It combines persistent recall with agent-specific retrieval.",
            repackaging_risk="Some pieces resemble existing vector-memory systems.",
            evidence=[],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=["The evaluation is narrow."],
            inferred_weaknesses=["Ablations may not isolate each component."],
            future_work=["Evaluate on longer deployments."],
            evidence=[],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk="The paper's strongest claims need broader benchmarks.",
            weak_evaluations=["Small benchmark coverage."],
            missing_ablations=["No isolated retrieval-channel ablation."],
            bottom_line="The idea is useful but needs stronger evaluation.",
            evidence=[],
        ),
        essence="The paper turns agent memory into a managed retrieval layer.",
        plain_language_example=(
            "An assistant can remember a project preference and reuse it in a later session."
        ),
        experiment_summary="The paper reports improved memory QA accuracy on a benchmark.",
    )
