from pathlib import Path

import pytest

from research_radar import cli
from research_radar.compose.archive import export_archive_run, render_archive_feed
from research_radar.compose.archive_figures import (
    figure_source,
    is_pdf_page_fallback_figure,
)
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.wechat import render_wechat_html, render_wechat_publish_html
from research_radar.models import (
    ArticleDraft,
    ArticleSection,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
)
from research_radar.storage.files import read_json, write_json


def test_archive_figure_source_prefers_relative_path() -> None:
    assert figure_source(
        {
            "relative_path": "figures/paper/architecture.png",
            "asset_path": "fallback.png",
        }
    ) == "figures/paper/architecture.png"


def test_archive_pdf_page_fallback_recognizes_legacy_page_assets() -> None:
    assert is_pdf_page_fallback_figure({"original_path": "page 3"})
    assert is_pdf_page_fallback_figure(
        {"relative_path": "figures/paper/02-page-3.png"}
    )
    assert not is_pdf_page_fallback_figure(
        {"relative_path": "figures/paper/figure-2-page-3.png"}
    )


def test_archive_export_writes_article_index_feed_and_metadata(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, with_figure=True)
    output_dir = tmp_path / "archive"

    result = export_archive_run(run_dir, output_dir, base_url="https://example.com/research")

    article_html = result.article_path.read_text(encoding="utf-8")
    index_html = result.index_path.read_text(encoding="utf-8")
    feed_xml = result.feed_path.read_text(encoding="utf-8")
    metadata = result.metadata_path.read_text(encoding="utf-8")

    assert result.article_path == output_dir / "articles" / "2026-06-28-agent-memory" / "index.html"
    assert "Verified archive claim." in article_html
    assert "Unsupported archive claim." not in article_html
    assert "role=" not in article_html
    assert "status=" not in article_html
    assert "score=" not in article_html
    assert "reuse_status" not in article_html
    assert "/private/" not in article_html
    assert "../../assets/2026-06-28-agent-memory/figures/paper/architecture.png" in article_html
    assert (output_dir / "assets/2026-06-28-agent-memory/figures/paper/architecture.png").exists()
    assert "ResearchRadar Daily: agent-memory" in index_html
    assert "https://example.com/research/articles/2026-06-28-agent-memory/" in feed_xml
    assert '"claim_count": 1' in metadata


def test_archive_export_omits_missing_figure_images(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, with_figure=False, with_missing_figure=True)

    export_archive_run(run_dir, tmp_path / "archive", base_url="https://example.com/research")

    article_html = (
        tmp_path / "archive/articles/2026-06-28-agent-memory/index.html"
    ).read_text(encoding="utf-8")
    assert "missing.png" not in article_html
    assert "<img" not in article_html


def test_archive_export_is_idempotent_for_same_run(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path)
    output_dir = tmp_path / "archive"

    export_archive_run(run_dir, output_dir, base_url="https://example.com/research")
    export_archive_run(run_dir, output_dir, base_url="https://example.com/research")

    feed_xml = (output_dir / "feed.xml").read_text(encoding="utf-8")
    assert feed_xml.count("<item>") == 1


def test_archive_export_rejects_asset_symlink_outside_run(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, with_missing_figure=True)
    outside_asset = tmp_path / "private.png"
    outside_asset.write_bytes(b"private image bytes")
    symlink = run_dir / "figures/paper/missing.png"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(outside_asset)
    output_dir = tmp_path / "archive"

    result = export_archive_run(run_dir, output_dir, base_url="https://example.com/research")

    copied = output_dir / f"assets/{run_dir.name}/figures/paper/missing.png"
    assert not copied.exists()
    assert "<img" not in result.article_path.read_text(encoding="utf-8")


def test_archive_export_allows_absolute_asset_path_inside_run(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    absolute_asset = str((run_dir / "figures/paper/architecture.png").resolve())
    data["sections"][0]["metadata"]["deep_reads"][0]["figures"][0]["relative_path"] = (
        absolute_asset
    )
    data["sections"][1]["metadata"]["figures"][0]["relative_path"] = absolute_asset
    write_json(draft_path, data)

    result = export_archive_run(
        run_dir,
        tmp_path / "archive",
        base_url="https://example.com/research",
    )

    article_html = result.article_path.read_text(encoding="utf-8")
    assert "../../assets/2026-06-28-agent-memory/figures/paper/architecture.png" in article_html


def test_archive_export_does_not_render_unsafe_public_links(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path)
    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    data["sections"][0]["metadata"]["deep_reads"][0]["source"]["url"] = (
        "javascript:alert(1)"
    )
    data["sections"][1]["metadata"]["sources"][0]["url"] = (
        "data:text/html,<script>alert(2)</script>"
    )
    data["sections"][1]["claims"][0]["evidence"][0]["source_url"] = (
        "file:///private/tmp/paper.pdf"
    )
    write_json(draft_path, data)

    result = export_archive_run(
        run_dir,
        tmp_path / "archive",
        base_url="https://example.com/research",
    )

    article_html = result.article_path.read_text(encoding="utf-8")
    assert "javascript:" not in article_html
    assert "data:text/html" not in article_html
    assert "file:///" not in article_html
    assert "Fixture Paper" in article_html
    assert "Verified archive claim." in article_html


@pytest.mark.parametrize(
    "base_url",
    [
        "example.com/research",
        "file:///tmp/archive",
        "https://user:password@example.com/research",
        "https://example.com/research?preview=1",
        "https://example.com/research#latest",
    ],
)
def test_archive_export_rejects_invalid_public_base_url(
    tmp_path: Path,
    base_url: str,
) -> None:
    run_dir = _write_archive_draft(tmp_path)

    with pytest.raises(ValueError, match="base_url"):
        export_archive_run(run_dir, tmp_path / "archive", base_url=base_url)


def test_archive_output_directory_is_bound_to_one_base_url(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path)
    output_dir = tmp_path / "archive"
    export_archive_run(run_dir, output_dir, base_url="https://old.example/research")

    with pytest.raises(ValueError, match="already bound"):
        export_archive_run(run_dir, output_dir, base_url="https://new.example/research")

    state = read_json(output_dir / "archive.json")
    assert state["schema_version"] == 1
    assert state["base_url"] == "https://old.example/research"


def test_archive_feed_rebuilds_links_from_bound_base_url(tmp_path: Path) -> None:
    first_run = _write_archive_draft(tmp_path / "first", run_id="2026-06-28-agent-memory")
    second_run = _write_archive_draft(tmp_path / "second", run_id="2026-06-29-agent-memory")
    output_dir = tmp_path / "archive"
    base_url = "https://example.com/research"
    first = export_archive_run(first_run, output_dir, base_url=base_url)
    first_metadata = read_json(first.metadata_path)
    first_metadata["link"] = "https://stale.example/articles/old/"
    write_json(first.metadata_path, first_metadata)

    export_archive_run(second_run, output_dir, base_url=base_url)

    feed_xml = (output_dir / "feed.xml").read_text(encoding="utf-8")
    assert "stale.example" not in feed_xml
    assert f"{base_url}/articles/{first_run.name}/" in feed_xml
    assert f"{base_url}/articles/{second_run.name}/" in feed_xml


def test_archive_reexport_retires_assets_no_longer_referenced(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, with_figure=True)
    output_dir = tmp_path / "archive"
    result = export_archive_run(run_dir, output_dir, base_url="https://example.com/research")
    public_asset = output_dir / f"assets/{run_dir.name}/figures/paper/architecture.png"
    assert public_asset.exists()
    metadata = read_json(result.metadata_path)
    assert metadata["assets"] == [
        f"assets/{run_dir.name}/figures/paper/architecture.png"
    ]

    draft_path = run_dir / "article_draft.json"
    data = read_json(draft_path)
    data["sections"][0]["metadata"]["deep_reads"][0]["figures"] = []
    data["sections"][1]["metadata"]["figures"] = []
    write_json(draft_path, data)
    export_archive_run(run_dir, output_dir, base_url="https://example.com/research")

    assert not public_asset.exists()
    retired_root = tmp_path / ".archive-retired-assets"
    assert list(retired_root.rglob("architecture.png"))


def test_archive_export_preserves_wechat_rendering_and_run_artifact(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    draft = load_article_draft(draft_path)
    draft_bytes = draft_path.read_bytes()
    preview_before = render_wechat_html(draft)
    publish_before = render_wechat_publish_html(draft)

    export_archive_run(run_dir, tmp_path / "archive", base_url="https://example.com/research")

    reloaded = load_article_draft(draft_path)
    assert draft_path.read_bytes() == draft_bytes
    assert render_wechat_html(reloaded) == preview_before
    assert render_wechat_publish_html(reloaded) == publish_before


def test_chinese_archive_uses_chinese_navigation_and_source_labels(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path, language="zh")

    result = export_archive_run(
        run_dir,
        tmp_path / "archive",
        base_url="https://example.com/research",
    )

    article_html = result.article_path.read_text(encoding="utf-8")
    assert ">目录<" in article_html
    assert ">原文链接<" in article_html
    assert ">Contents<" not in article_html
    assert ">Original source<" not in article_html


def test_archive_export_cli_writes_static_artifacts(tmp_path: Path) -> None:
    run_dir = _write_archive_draft(tmp_path)
    output_dir = tmp_path / "archive"

    cli.main(
        [
            "archive",
            "export",
            "--run",
            str(run_dir),
            "--output",
            str(output_dir),
            "--base-url",
            "https://example.com/research",
        ]
    )

    assert (output_dir / "articles/2026-06-28-agent-memory/index.html").exists()
    assert (output_dir / "index.html").exists()
    assert (output_dir / "feed.xml").exists()


def test_rss_escapes_xml_text() -> None:
    feed_xml = render_archive_feed(
        [
            {
                "run_id": "run-1",
                "title": "A < B & C",
                "digest": "Use <quoted> evidence & anchors.",
                "created_at": "2026-06-28T00:00:00+00:00",
                "link": "https://example.com/archive/articles/run-1/",
            }
        ],
        base_url="https://example.com/archive",
    )

    assert "A &lt; B &amp; C" in feed_xml
    assert "Use &lt;quoted&gt; evidence &amp; anchors." in feed_xml


def _write_archive_draft(
    tmp_path: Path,
    *,
    with_figure: bool = False,
    with_missing_figure: bool = False,
    run_id: str = "2026-06-28-agent-memory",
    language: str = "en",
) -> Path:
    run_dir = tmp_path / "runs" / run_id
    claim = Claim(
        text="Verified archive claim.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://example.com/paper",
                source_title="Fixture Paper",
                quote="Verified archive claim.",
            )
        ],
    )
    unsupported = Claim(text="Unsupported archive claim.", status=ClaimStatus.UNSUPPORTED)
    figure_path = "figures/paper/architecture.png"
    if with_figure:
        asset = run_dir / figure_path
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"fake-png")
    figure = {
        "relative_path": figure_path if with_figure else "figures/paper/missing.png",
        "caption": "Architecture overview.",
        "explanation": "The figure shows the verified system flow.",
        "reuse_status": "needs_manual_review",
    }
    draft = ArticleDraft(
        title="ResearchRadar Daily: agent-memory",
        topic_id="agent-memory",
        digest="A verified digest.",
        lede="Today deep-read one paper.",
        claims=[claim],
        sections=[
            ArticleSection(
                title="Today's Deep Reads",
                body="",
                claims=[claim, unsupported],
                metadata={
                    "kind": "deep_reads",
                    "deep_reads": [
                        {
                            "title": "Fixture Paper",
                            "source": {
                                "title": "Fixture Paper",
                                "url": "https://example.com/paper",
                                "role": "primary_paper",
                                "history_status": "new",
                                "score": 0.99,
                                "status": "new",
                            },
                            "reader_explanation": {
                                "opening_context": "The paper studies a concrete system.",
                                "solution_walkthrough": (
                                    "The method routes data through verified components."
                                ),
                            },
                            "figures": [figure] if with_figure or with_missing_figure else [],
                            "claims": [
                                {"text": "Verified archive claim."},
                            ],
                        }
                    ],
                },
            ),
            ArticleSection(
                title="References",
                body="",
                claims=[claim, unsupported],
                metadata={
                    "kind": "references",
                    "sources": [
                        {
                            "title": "Fixture Paper",
                            "url": "https://example.com/paper",
                            "role": "primary_paper",
                            "history_status": "new",
                            "score": 0.99,
                            "status": "new",
                        }
                    ],
                    "figures": [figure],
                },
            ),
        ],
        metadata={"language": language, "draft_type": "daily_long_form"},
    )
    write_json(run_dir / "article_draft.json", draft)
    return run_dir
