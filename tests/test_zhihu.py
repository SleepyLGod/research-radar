from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_radar import cli
from research_radar.compose.archive_html import render_archive_article
from research_radar.compose.wechat import render_wechat_html, render_wechat_publish_html
from research_radar.compose.zhihu import export_zhihu_run
from research_radar.models import (
    ArticleDraft,
    ArticleSection,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
)
from research_radar.storage.files import read_json, write_json


def test_zhihu_export_writes_body_metadata_and_safe_assets(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    metadata = read_json(result.metadata_path)
    assert result.markdown_path == run_dir / "zhihu.md"
    assert result.metadata_path == run_dir / "zhihu_export.json"
    assert result.asset_dir == run_dir / "zhihu-assets"
    assert "# ResearchRadar 日报：agent-memory" not in markdown
    assert markdown.count("今天精读了 1 篇论文。") == 1
    assert "## 1. Fixture Paper" in markdown
    assert "[查看论文原文](https://example.com/paper)" in markdown
    assert "### 方法与机制" in markdown
    assert "####" not in markdown
    assert "方法通过分层检索处理长期记忆。" in markdown
    assert "Unsupported private claim" not in markdown
    assert "Nested unsupported claim" not in markdown
    assert "internal audit body" not in markdown
    assert "role=" not in markdown
    assert "status=" not in markdown
    assert "score=" not in markdown
    assert "reuse_status" not in markdown
    assert "![系统架构](zhihu-assets/figures/paper/architecture.png)" in markdown
    assert "*图 1｜系统架构*" in markdown
    assert "图中可以这样看：这张图展示分层检索的数据流。" in markdown
    assert "针对本验证点" not in markdown
    assert "Solution:" not in markdown
    assert "## 延伸阅读" in markdown
    assert (
        "- [Structured Agent Memory](https://example.com/structured-memory)："
        "四个逻辑网络组织长期记忆。"
    ) in markdown
    assert "[PDF]" not in markdown
    assert "](<" not in markdown
    assert "  - " not in markdown
    assert "Exact source quote." not in markdown
    assert (run_dir / "zhihu-assets/figures/paper/architecture.png").exists()
    assert metadata == {
        "schema_version": 2,
        "run_id": run_dir.name,
        "topic_id": "agent-memory",
        "title": "ResearchRadar 日报：agent-memory",
        "digest": "今日精选 agent-memory 相关论文精读。",
        "language": "zh",
        "body_path": "zhihu.md",
        "image_mode": "local",
        "assets": [
            {
                "path": "zhihu-assets/figures/paper/architecture.png",
                "public_url": None,
                "caption": "系统架构",
            }
        ],
    }


def test_zhihu_export_omits_assets_outside_run(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_missing_figure=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    source = run_dir / "figures/paper/missing.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.symlink_to(outside)

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    metadata = read_json(result.metadata_path)
    assert "missing.png" not in markdown
    assert "论文关键图" not in markdown
    assert metadata["assets"] == []


def test_zhihu_export_omits_non_renderable_assets(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    data["sections"][1]["metadata"]["deep_reads"][0]["figures"][0][
        "renderable"
    ] = False
    write_json(draft_path, data)

    result = export_zhihu_run(run_dir)

    assert "论文关键图" not in result.markdown_path.read_text(encoding="utf-8")
    assert read_json(result.metadata_path)["assets"] == []


def test_zhihu_export_uses_validated_remote_asset_base_url(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)

    result = export_zhihu_run(
        run_dir,
        asset_base_url="https://example.com/archive/assets/run/",
    )

    markdown = result.markdown_path.read_text(encoding="utf-8")
    metadata = read_json(result.metadata_path)
    public_url = (
        "https://example.com/archive/assets/run/figures/paper/architecture.png"
    )
    assert f"![系统架构]({public_url})" in markdown
    assert metadata["image_mode"] == "remote"
    assert metadata["assets"][0]["public_url"] == public_url


def test_zhihu_export_renders_unsafe_source_urls_as_plain_text(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    data["sections"][1]["metadata"]["deep_reads"][0]["source"]["url"] = (
        "javascript:alert(1)"
    )
    data["sections"][2]["metadata"]["sources"][0]["url"] = "file:///tmp/paper"
    write_json(draft_path, data)

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "javascript:" not in markdown
    assert "file:///" not in markdown
    assert "查看论文原文" not in markdown
    assert "Structured Agent Memory：四个逻辑网络组织长期记忆。" in markdown


def test_zhihu_export_deduplicates_figure_notes_without_dropping_short_captions(
    tmp_path: Path,
) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    first = data["sections"][1]["metadata"]["deep_reads"][0]["figures"][0]
    first["caption"] = first["localized_caption"] = "架构"
    second = dict(first)
    second["relative_path"] = "figures/paper/retrieval.png"
    second["caption"] = second["localized_caption"] = "检索流程"
    data["sections"][1]["metadata"]["deep_reads"][0]["figures"].append(second)
    write_json(draft_path, data)
    second_asset = run_dir / "figures/paper/retrieval.png"
    second_asset.write_bytes(b"png")

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "*图 1｜架构*" in markdown
    assert "*图 2｜检索流程*" in markdown
    assert markdown.count("图中可以这样看：这张图展示分层检索的数据流。") == 1


def test_zhihu_export_counts_only_valid_figures_toward_the_three_image_limit(
    tmp_path: Path,
) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    figures = data["sections"][1]["metadata"]["deep_reads"][0]["figures"]
    invalid = [
        {
            **figures[0],
            "relative_path": f"figures/paper/missing-{index}.png",
        }
        for index in range(3)
    ]
    figures[:0] = invalid
    write_json(draft_path, data)

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "![系统架构](zhihu-assets/figures/paper/architecture.png)" in markdown
    assert len(read_json(result.metadata_path)["assets"]) == 1


def test_zhihu_export_localizes_missing_figure_caption(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    figure = data["sections"][1]["metadata"]["deep_reads"][0]["figures"][0]
    figure["caption"] = ""
    figure["localized_caption"] = ""
    write_json(draft_path, data)

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "![论文图]" in markdown
    assert read_json(result.metadata_path)["assets"][0]["caption"] == "论文图"


def test_zhihu_export_percent_encodes_markdown_destinations(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    deep_read = data["sections"][1]["metadata"]["deep_reads"][0]
    deep_read["source"]["url"] = "https://example.com/paper (draft)"
    deep_read["figures"][0]["relative_path"] = "figures/paper/architecture (v2).png"
    write_json(draft_path, data)
    original_asset = run_dir / "figures/paper/architecture.png"
    spaced_asset = run_dir / "figures/paper/architecture (v2).png"
    original_asset.rename(spaced_asset)

    result = export_zhihu_run(run_dir)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "https://example.com/paper%20%28draft%29" in markdown
    assert "zhihu-assets/figures/paper/architecture%20%28v2%29.png" in markdown


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "file:///tmp/assets",
        "https://user:secret@example.com/assets",
        "https://example.com/assets?token=secret",
        "https://example.com/assets#fragment",
    ],
)
def test_zhihu_export_rejects_unsafe_asset_base_url(
    tmp_path: Path,
    value: str,
) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)

    with pytest.raises(ValueError, match="asset base URL"):
        export_zhihu_run(run_dir, asset_base_url=value)


def test_zhihu_export_does_not_mutate_draft_wechat_or_archive(tmp_path: Path) -> None:
    run_dir = _write_zhihu_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    draft = _zhihu_draft(with_figure=True)
    draft_before = draft_path.read_bytes()
    wechat_before = render_wechat_html(draft)
    publish_before = render_wechat_publish_html(draft)
    archive_before = render_archive_article(
        draft,
        run_id=run_dir.name,
        base_url="https://example.com/archive",
        site_language="zh",
    )

    export_zhihu_run(run_dir)

    loaded = read_json(draft_path)
    assert draft_path.read_bytes() == draft_before
    assert render_wechat_html(draft) == wechat_before
    assert render_wechat_publish_html(draft) == publish_before
    assert loaded["title"] == draft.title
    assert (
        render_archive_article(
            draft,
            run_id=run_dir.name,
            base_url="https://example.com/archive",
            site_language="zh",
        )
        == archive_before
    )


def test_compose_zhihu_cli_uses_run_directory() -> None:
    args = cli.build_parser().parse_args(
        [
            "compose",
            "zhihu",
            "--run",
            "/tmp/run",
            "--asset-base-url",
            "https://example.com/assets/run/",
        ]
    )

    assert args.run_dir == Path("/tmp/run")
    assert args.asset_base_url == "https://example.com/assets/run/"
    assert args.handler is cli.handle_compose_zhihu


def _write_zhihu_draft(
    tmp_path: Path,
    *,
    with_figure: bool = False,
    with_missing_figure: bool = False,
) -> Path:
    run_dir = tmp_path / "2026-07-14-agent-memory"
    run_dir.mkdir()
    draft = _zhihu_draft(
        with_figure=with_figure,
        with_missing_figure=with_missing_figure,
    )
    write_json(run_dir / "article_draft.json", draft)
    if with_figure:
        asset = run_dir / "figures/paper/architecture.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"png")
    return run_dir


def _zhihu_draft(
    *,
    with_figure: bool = False,
    with_missing_figure: bool = False,
) -> ArticleDraft:
    supported = Claim(
        text="方法：Supported public claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://example.com/paper",
                source_title="Fixture Paper",
                quote="Exact source quote.",
            )
        ],
    )
    unsupported = Claim(
        text="Unsupported private claim",
        status=ClaimStatus.UNSUPPORTED,
    )
    figures = []
    if with_figure or with_missing_figure:
        figures.append(
            {
                "relative_path": (
                    "figures/paper/architecture.png"
                    if with_figure
                    else "figures/paper/missing.png"
                ),
                "caption": "系统架构",
                "localized_caption": "系统架构",
                "explanation": (
                    "针对本验证点的可视化上下文：Solution: "
                    "这张图展示分层检索的数据流。"
                ),
                "reuse_status": "needs_manual_review",
                "role": "method",
                "score": 1.0,
            }
        )
    deep_read = {
        "title": "Fixture Paper",
        "source": {
            "title": "Fixture Paper",
            "url": "https://example.com/paper",
            "role": "primary_paper",
            "status": "new",
            "score": 0.9,
        },
        "reader_explanation": {
            "opening_context": "长期记忆系统需要兼顾召回和存储成本。",
            "core_thesis": "论文提出分层检索方法。",
            "problem_walkthrough": "现有方法在长时间跨度上容易丢失线索。",
            "solution_walkthrough": "方法通过分层检索处理长期记忆。",
            "experiment_interpretation": "实验比较了检索准确率和延迟。",
            "limitations_discussion": "目前只评估了有限工作负载。",
            "reader_takeaway": "它适合需要长期上下文的 agent。",
        },
        "figures": figures,
        "claims": [
            {"text": supported.text, "evidence": []},
            {"text": "Nested unsupported claim", "evidence": []},
        ],
    }
    return ArticleDraft(
        title="ResearchRadar 日报：agent-memory",
        topic_id="agent-memory",
        digest="今日精选 agent-memory 相关论文精读。",
        lede="今天精读了 1 篇论文。",
        sections=[
            ArticleSection(
                title="今日摘要",
                body="今天精读了 1 篇论文。\n已核验证据点：1 条。",
                metadata={"kind": "today_summary"},
            ),
            ArticleSection(
                title="今日精读",
                body="",
                claims=[supported, unsupported],
                metadata={"kind": "deep_reads", "deep_reads": [deep_read]},
            ),
            ArticleSection(
                title="其他新增 / 更新来源",
                body="",
                metadata={
                    "kind": "new_updated_sources",
                    "sources": [
                        {
                            "title": "[PDF] Structured Agent Memory",
                            "url": "https://example.com/structured-memory",
                            "source_type": "paper",
                            "source_group": "research_papers",
                            "gist": "四个逻辑网络组织长期记忆。",
                            "role": "primary_paper",
                            "status": "new",
                            "score": 0.8,
                        }
                    ],
                },
            ),
            ArticleSection(
                title="参考资料",
                body="internal audit body",
                claims=[supported, unsupported],
                metadata={"kind": "references", "figures": figures},
            ),
        ],
        claims=[supported, unsupported],
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        metadata={"language": "zh", "deep_read_count": 1, "source_count": 1},
    )
