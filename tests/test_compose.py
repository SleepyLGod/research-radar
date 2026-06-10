from dataclasses import replace

from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    ReaderExplanation,
    RelatedWorkAssessment,
)
from research_radar.compose.draft import build_daily_draft, build_weekly_draft
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.source_groups import group_source_entries
from research_radar.compose.wechat import (
    compose_wechat_html,
    render_wechat_html,
    render_wechat_publish_html,
    wechat_publish_html_issues,
)
from research_radar.compose.zhihu import render_zhihu_markdown
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
    assert "Research paper · new source · 2026-05-01 · v1" in markdown
    assert "role=primary_paper" not in markdown
    assert "status=new" not in markdown
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
    assert "role=" not in html
    assert "status=" not in html


def test_wechat_preview_deep_read_source_metadata_is_human_readable() -> None:
    source = replace(
        _paper_source(),
        metadata={
            "source_role": {"role": "primary_paper"},
            "source_history": {"status": "new"},
            "source_gist": {"text": "This paper proposes a memory system for agents."},
        },
    )
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        language="zh",
    )

    html = render_wechat_html(draft)

    assert "研究论文 · 新来源" in html
    assert "role=" not in html
    assert "status=" not in html


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


def test_long_form_wechat_renders_toc_deep_reads_and_collapsed_references() -> None:
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
    assert 'class="rr-hero"' in html
    assert 'class="rr-section"' in html
    assert "Deep Reads" in html
    assert "Other New / Updated Sources" in html
    assert "Evidence Notes" not in html
    assert "References" in html
    assert "<summary>Open references</summary>" in html
    assert "Source links" in html
    assert "arXiv:2605.00001" in html
    assert "Problem and Motivation" in html
    assert "Solution Mechanism" in html
    assert "Experiments" in html
    assert "Related Work" in html
    assert "Explicit limitations" in html
    assert "Plain-language Example" in html
    assert "<summary>Key Evidence</summary>" in html
    assert "rr-diagram" in html
    assert "Supported paper claim" in html


def test_wechat_visual_polish_does_not_change_markdown_or_zhihu_fallback() -> None:
    source = _paper_source()
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [_supported_paper_claim(source)],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
    )

    html = render_wechat_html(draft)
    markdown = render_markdown(draft)
    zhihu = render_zhihu_markdown(draft)

    assert 'class="rr-summary"' in html
    assert 'class="rr-deep"' in html
    assert "Supported paper claim" in markdown
    assert "Supported paper claim" in zhihu
    assert "rr-summary" not in markdown
    assert "rr-summary" not in zhihu


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


def test_long_form_wechat_prefers_reader_explanation_prose() -> None:
    source = _paper_source()
    reading = replace(
        _paper_reading(source.title),
        reader_explanation=ReaderExplanation(
            opening_context="Start from the long-term memory problem.",
            core_thesis="The paper treats memory as a managed retrieval layer.",
            problem_walkthrough="The reader should first see why repeated tasks lose context.",
            solution_walkthrough="The mechanism retrieves and filters stored memories.",
            experiment_interpretation=(
                "The reported benchmark result should be read as scoped evidence."
            ),
            related_work_context="MemGPT and Zep frame the comparison.",
            limitations_discussion="The evidence remains narrow.",
            plain_language_story=(
                "Imagine an assistant carrying project preferences across sessions."
            ),
            reader_takeaway="The useful question is whether recall stays grounded.",
        ),
    )
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [_supported_paper_claim(source)],
        readings=[reading],
        deep_read_sources=[source],
    )

    html = render_wechat_html(draft)
    markdown = render_markdown(draft)

    assert "Start from the long-term memory problem." in html
    assert "The mechanism retrieves and filters stored memories." in html
    assert "Start from the long-term memory problem." in markdown
    assert "The mechanism retrieves and filters stored memories." in markdown


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
            readings=[
                replace(
                    _paper_reading(source.title),
                    reader_explanation=ReaderExplanation(
                        opening_context="这是一段背景知识。",
                        problem_walkthrough="这是一段问题与动机说明。",
                    ),
                )
            ],
            deep_read_sources=[source],
        )
    )

    assert "目录" in html
    assert "今日精读" in html
    assert "问题与动机" in html
    assert "<summary>关键证据</summary>" in html
    assert "参考资料" in html
    assert "<summary>展开参考证据</summary>" in html
    assert "long-term memory evidence" in html


def test_long_form_chinese_lede_does_not_append_first_claim() -> None:
    source = _paper_source()
    claim = Claim(
        text="Problem: 这篇论文讨论长期记忆。",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="long-term memory evidence",
            )
        ],
    )
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        language="zh",
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
    )
    legacy_suffix = (
        " method: FRQAD is a new metric on the Gaussian statistical manifold."
    )
    legacy_sections = [
        replace(
            draft.sections[0],
            body=f"{draft.lede}{legacy_suffix}\n已核验证据点：1 条。",
        ),
        *draft.sections[1:],
    ]
    legacy_draft = replace(draft, lede=f"{draft.lede}{legacy_suffix}", sections=legacy_sections)

    html = render_wechat_html(legacy_draft)

    assert draft.lede == "今天精读了 1 篇新论文，并保留其他新增来源供后续跟进。"
    assert "method: FRQAD" in legacy_draft.lede
    assert '<div class="rr-summary">' in html
    assert "<p>今日精读：1 篇论文。</p>" in html
    assert "<p>已核验证据点：1 条。</p>" in html
    assert "<p>其他新增来源：0 个，见下方折叠列表。</p>" not in html
    lede_html = html.split('<p class="lede">', 1)[1].split("</p>", 1)[0]
    assert "method: FRQAD" not in lede_html
    summary_html = html.split('<div class="rr-summary">', 1)[1].split("</div>", 1)[0]
    assert "method: FRQAD" not in summary_html
    assert "今天精读了 1 篇新论文，并保留其他新增来源供后续跟进。" not in summary_html


def test_long_form_wechat_renders_paper_figures_without_new_claims() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        figures_by_source_url={source.url: [_paper_figure(source, claim.text)]},
    )

    html = render_wechat_html(draft)

    assert "Key Figures" in html
    assert '<img src="figures/2605.00001/images/01-architecture.png"' in html
    assert "Architecture overview for the memory retrieval pipeline." in html
    assert "Reuse status: needs_manual_review" in html
    assert "Figure license and reuse" in html
    assert "license=unknown; reuse_status=needs_manual_review" in html
    assert "This figure is included because its caption aligns with a verified observation" in html
    assert "fabricated interpretation" not in html


def test_wechat_publish_mode_does_not_emit_local_figure_image_src() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        figures_by_source_url={source.url: [_paper_figure(source, claim.text)]},
    )

    html = render_wechat_html(draft, publish_mode=True)

    assert '<img src="figures/' not in html
    assert "Figure image requires WeChat media upload before publishing." in html
    assert "Architecture overview for the memory retrieval pipeline." in html


def test_wechat_publish_renderer_uses_conservative_html_with_uploaded_images() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        figures_by_source_url={source.url: [_paper_figure(source, claim.text)]},
    )

    html = render_wechat_publish_html(
        draft,
        media_url_map={
            "figures/2605.00001/images/01-architecture.png": (
                "https://mmbiz.qpic.cn/fixture/architecture.png"
            )
        },
    )

    assert wechat_publish_html_issues(html) == []
    assert "<style" not in html
    assert "<details" not in html
    assert "<summary" not in html
    assert "<figure" not in html
    assert "<figcaption" not in html
    assert "<blockquote" not in html
    assert "<a " not in html
    assert "figures/2605.00001" not in html
    assert "https://mmbiz.qpic.cn/fixture/architecture.png" in html
    assert "Architecture overview for the memory retrieval pipeline." in html
    assert "Supported paper claim" in html
    assert "Source: https://arxiv.org/abs/2605.00001" in html
    assert "reuse_status" not in html
    assert "reuse status" not in html
    assert "ResearchRadar" not in html
    assert "role=" not in html
    assert "status=" not in html
    assert "score=" not in html
    assert "<strong>fig:architecture</strong>" not in html
    assert "This figure is included because" not in html


def test_wechat_publish_renderer_does_not_emit_legacy_pdf_page_fallback() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    figure = _paper_figure(
        source,
        claim.text,
        path="figures/OpenReview-uNqTxj5brQ/01-page-3.png",
    )
    figure["original_path"] = "page 3"
    draft = build_daily_draft(
        "llm-inference",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        figures_by_source_url={source.url: [figure]},
    )

    html = render_wechat_publish_html(
        draft,
        media_url_map={
            "figures/OpenReview-uNqTxj5brQ/01-page-3.png": (
                "https://mmbiz.qpic.cn/fixture/page-3.png"
            )
        },
    )

    assert "https://mmbiz.qpic.cn/fixture/page-3.png" not in html
    assert "Architecture overview for the memory retrieval pipeline." not in html
    assert wechat_publish_html_issues(html) == []


def test_wechat_publish_renderer_keeps_preview_renderer_unchanged() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        figures_by_source_url={source.url: [_paper_figure(source, claim.text)]},
    )

    preview_html = render_wechat_html(draft)
    publish_html = render_wechat_publish_html(
        draft,
        media_url_map={
            "figures/2605.00001/images/01-architecture.png": (
                "https://mmbiz.qpic.cn/fixture/architecture.png"
            )
        },
    )

    assert "<details" in preview_html
    assert "<figure" in preview_html
    assert "figures/2605.00001/images/01-architecture.png" in preview_html
    assert "<details" not in publish_html
    assert "<figure" not in publish_html


def test_wechat_publish_renderer_cleans_public_article_body() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        language="zh",
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        seen_sources=[
            {
                "title": "Seen Memory Paper",
                "url": "https://arxiv.org/abs/2605.00000",
                "version": "v1",
            }
        ],
        figures_by_source_url={source.url: [_paper_figure(source, claim.text)]},
    )

    html = render_wechat_publish_html(
        draft,
        media_url_map={
            "figures/2605.00001/images/01-architecture.png": (
                "https://mmbiz.qpic.cn/fixture/architecture.png"
            )
        },
    )

    assert wechat_publish_html_issues(html) == []
    assert "ResearchRadar 日报：agent-memory" not in html
    assert "今日精读：1 篇论文。" in html
    assert "role=" not in html
    assert "status=" not in html
    assert "score=" not in html
    assert "论文链接: https://arxiv.org/abs/2605.00001" in html
    assert "<strong>fig:architecture</strong>" not in html
    assert "Architecture overview for the memory retrieval pipeline." in html
    assert "This figure is included because" not in html
    assert "历史相关来源" in html
    assert "1. Seen Memory Paper (v1) | https://arxiv.org/abs/2605.00000" in html


def test_wechat_publish_renderer_strips_legacy_formula_html_fragments() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    figure = {
        **_paper_figure(source, claim.text),
        "explanation": (
            'The figure explains <span class="rr-formula" style="x">R(t)=e^{-t/S(m)}</span>.'
        ),
    }
    draft = build_daily_draft(
        "agent-memory",
        [source],
        [claim],
        readings=[_paper_reading(source.title)],
        deep_read_sources=[source],
        figures_by_source_url={source.url: [figure]},
    )

    html = render_wechat_publish_html(
        draft,
        media_url_map={
            "figures/2605.00001/images/01-architecture.png": (
                "https://mmbiz.qpic.cn/fixture/architecture.png"
            )
        },
    )

    assert "&lt;span" not in html
    assert "class=&quot;rr-formula" not in html
    assert "R(t)=e^{-t/S(m)}" in html


def test_long_form_chinese_renders_figures_and_keeps_evidence_quote_english() -> None:
    source = _paper_source()
    claim = Claim(
        text="Solution: 这篇论文使用检索式记忆。",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="retrieval memory pipeline",
            )
        ],
    )

    html = render_wechat_html(
        build_daily_draft(
            "agent-memory",
            [source],
            [claim],
            language="zh",
            readings=[
                replace(
                    _paper_reading(source.title),
                    reader_explanation=ReaderExplanation(
                        opening_context="这是一段背景知识。",
                    ),
                )
            ],
            deep_read_sources=[source],
            figures_by_source_url={
                source.url: [
                    {
                        **_paper_figure(source, claim.text),
                        "caption": (
                            "SLM~V3.3 architecture with 32$$ cold-start speedup "
                            "and retention tier $R 0.35$."
                        ),
                        "localized_caption": (
                            "SLM~V3.3 架构图，展示 32$$ 冷启动加速和保留层级 $R 0.35$。"
                        ),
                        "explanation": "这张图说明检索式记忆 pipeline 的架构。",
                    }
                ]
            },
        )
    )

    assert "论文关键图" in html
    assert "背景知识速读" in html
    assert "SLM V3.3 架构图，展示 32 冷启动加速和保留层级" in html
    assert 'class="rr-formula"' in html
    assert "R 0.35" in html
    assert "原始图注" in html
    assert "SLM V3.3 architecture with 32 cold-start speedup" in html
    assert "SLM~V3.3" not in html
    assert "32$$" not in html
    assert "$R 0.35$" not in html
    assert "这张图说明检索式记忆 pipeline 的架构。" in html
    assert "来源:" in html
    assert "复用状态: needs_manual_review" in html
    assert "retrieval memory pipeline" in html


def test_wechat_static_formula_formatting_keeps_raw_evidence_quote() -> None:
    source = _paper_source()
    claim = Claim(
        text="Solution: Retention follows R(t) = e^{-t/S(m)} with κ=2.0 and 32× speedup.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="Retention follows R(t) = e^{-t/S(m)} with κ=2.0 and 32× speedup.",
                location="page 3",
            )
        ],
    )

    html = render_wechat_html(build_weekly_draft("agent-memory", [claim]))

    assert html.count('class="rr-formula"') >= 3
    assert ">R(t) = e^{-t/S(m)}</span>" in html
    assert ">κ=2.0</span>" in html
    assert ">32×</span>" in html
    assert "R(t) = e^{-t/<span" not in html
    assert (
        "<p>Retention follows R(t) = e^{-t/S(m)} with κ=2.0 and 32× speedup.</p>"
        in html
    )


def test_wechat_formula_formatter_does_not_wrap_plain_english() -> None:
    source = _paper_source()
    claim = Claim(
        text="Solution: The system uses retrieval memory without a formula.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="The system uses retrieval memory without a formula.",
            )
        ],
    )

    html = render_wechat_html(build_weekly_draft("agent-memory", [claim]))

    assert 'class="rr-formula"' not in html


def test_wechat_formula_formatter_does_not_wrap_currency_prose() -> None:
    source = _paper_source()
    claim = Claim(
        text="Cost: The service costs $5 for input and $10 for output.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="The service costs $5 for input and $10 for output.",
            )
        ],
    )

    html = render_wechat_html(build_weekly_draft("agent-memory", [claim]))

    assert "costs $5 for input and $10 for output" in html
    assert 'class="rr-formula"' not in html


def test_chinese_figure_fallback_explanation_does_not_expose_english_boilerplate() -> None:
    source = _paper_source()
    claim = _supported_paper_claim(source)
    html = render_wechat_html(
        build_daily_draft(
            "agent-memory",
            [source],
            [claim],
            language="zh",
            readings=[_paper_reading(source.title)],
            deep_read_sources=[source],
            figures_by_source_url={
                source.url: [
                    _paper_figure(
                        source,
                        "Solution: The system uses a retrieval memory pipeline.",
                    )
                ]
            },
        )
    )

    assert "这张图用于辅助理解；它的图注与一条已核验判断相关" in html
    assert "This figure is included because" not in html
    assert "Solution: The system uses a retrieval memory pipeline" not in html


def test_long_form_wechat_renders_multiple_deep_reads_with_own_figures() -> None:
    first = _paper_source()
    second = SourceCandidate(
        title="Second Memory Paper",
        url="https://arxiv.org/abs/2605.00002",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        metadata={
            "source_role": {"role": "benchmark_paper"},
            "source_gist": {"text": "This paper evaluates memory benchmarks."},
        },
    )
    first_claim = _supported_paper_claim(first)
    second_claim = Claim(
        text="Experiment: Second paper claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=second.url,
                source_title=second.title,
                quote="Second paper claim",
            )
        ],
    )

    html = render_wechat_html(
        build_daily_draft(
            "agent-memory",
            [first, second],
            [first_claim, second_claim],
            readings=[_paper_reading(first.title), _paper_reading(second.title)],
            deep_read_sources=[first, second],
            figures_by_source_url={
                first.url: [_paper_figure(first, first_claim.text, path="figures/first.png")],
                second.url: [
                    _paper_figure(second, second_claim.text, path="figures/second.png")
                ],
            },
        )
    )

    assert html.count("Deep-read paper") == 2
    assert "figures/first.png" in html
    assert "figures/second.png" in html
    assert html.index("Memory Paper") < html.index("figures/first.png")
    assert html.index("Second Memory Paper") < html.index("figures/second.png")


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


def _paper_figure(
    source: SourceCandidate,
    matched_claim: str,
    *,
    path: str = "figures/2605.00001/images/01-architecture.png",
) -> dict[str, object]:
    return {
        "title": "fig:architecture",
        "source_url": source.url,
        "source_title": source.title,
        "asset_path": f"/tmp/{path}",
        "relative_path": path,
        "original_path": "figures/architecture",
        "caption": "Architecture overview for the memory retrieval pipeline.",
        "label": "fig:architecture",
        "explanation": (
            "This figure is included because its caption aligns with a verified observation: "
            f"{matched_claim}"
        ),
        "matched_claim": matched_claim,
        "license": "unknown",
        "reuse_status": "needs_manual_review",
        "attribution": f"{source.title}; {source.url}",
        "renderable": True,
        "score": 3.0,
    }


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
