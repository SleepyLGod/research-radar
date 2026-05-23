from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.source_groups import group_source_entries
from research_radar.compose.wechat import compose_wechat_html, render_wechat_html
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, SourceCandidate, SourceType


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
