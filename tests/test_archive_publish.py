"""Tests for safe Git-backed archive publication."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_radar.config import ArchivePublishConfig
from research_radar.exceptions import PublishError
from research_radar.models import ArticleDraft, ArticleSection
from research_radar.publishers.archive import git as archive_git
from research_radar.publishers.archive.git import publish_archive_git
from research_radar.storage.files import read_json, write_json


def test_archive_publish_git_dry_run_leaves_checkout_unchanged(tmp_path: Path) -> None:
    checkout, _ = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)
    head_before = _git(checkout, "rev-parse", "HEAD")
    files_before = _checkout_files(checkout)

    result = publish_archive_git(run_dir, _settings(checkout), dry_run=True)

    assert result.status == "dry_run"
    assert _git(checkout, "rev-parse", "HEAD") == head_before
    assert _checkout_files(checkout) == files_before
    assert _git(checkout, "status", "--porcelain") == ""
    assert not (checkout / "archive").exists()


def test_archive_publish_git_dry_run_refuses_behind_checkout_without_updating_it(
    tmp_path: Path,
) -> None:
    checkout, remote = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)
    publisher = tmp_path / "publisher"
    _command(tmp_path, "git", "clone", "--branch", "gh-pages", str(remote), str(publisher))
    _git(publisher, "config", "user.name", "ResearchRadar Tests")
    _git(publisher, "config", "user.email", "tests@example.com")
    (publisher / "remote-change.txt").write_text("new remote state\n", encoding="utf-8")
    _git(publisher, "add", "remote-change.txt")
    _git(publisher, "commit", "-s", "-m", "advance pages")
    _git(publisher, "push", "origin", "HEAD:gh-pages")
    head_before = _git(checkout, "rev-parse", "HEAD")
    files_before = _checkout_files(checkout)

    with pytest.raises(PublishError, match="behind"):
        publish_archive_git(run_dir, _settings(checkout), dry_run=True)

    assert _git(checkout, "rev-parse", "HEAD") == head_before
    assert _checkout_files(checkout) == files_before
    assert _git(checkout, "status", "--porcelain") == ""


def test_archive_publish_git_commits_pushes_and_skips_empty_commit(tmp_path: Path) -> None:
    checkout, remote = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)

    first = publish_archive_git(run_dir, _settings(checkout))

    assert first.status == "published"
    assert first.commit
    report = checkout / "archive/reports/2026-07-17-agent-memory/index.html"
    assert report.exists()
    assert _git(checkout, "status", "--porcelain") == ""
    assert _git(checkout, "rev-parse", "HEAD") == _git(
        remote,
        "rev-parse",
        "refs/heads/gh-pages",
    )

    head_after_first_publish = _git(checkout, "rev-parse", "HEAD")
    second = publish_archive_git(run_dir, _settings(checkout))

    assert second.status == "unchanged"
    assert second.commit == head_after_first_publish
    assert _git(checkout, "rev-parse", "HEAD") == head_after_first_publish


def test_archive_publish_git_refuses_dirty_checkout(tmp_path: Path) -> None:
    checkout, _ = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)
    (checkout / "unrelated.txt").write_text("do not publish\n", encoding="utf-8")

    with pytest.raises(PublishError, match="clean"):
        publish_archive_git(run_dir, _settings(checkout))

    error = run_dir / "archive_publish_error.json"
    assert error.is_file()
    assert "clean" in error.read_text(encoding="utf-8")


def test_archive_publish_git_refuses_wrong_branch(tmp_path: Path) -> None:
    checkout, _ = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)
    _git(checkout, "switch", "-c", "other")

    with pytest.raises(PublishError, match="gh-pages"):
        publish_archive_git(run_dir, _settings(checkout))


def test_archive_validation_allows_public_query_parameters_named_status_or_score(
    tmp_path: Path,
) -> None:
    checkout, _ = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)
    publish_archive_git(run_dir, _settings(checkout))
    report = checkout / "archive/reports/2026-07-17-agent-memory/index.html"
    report.write_text(
        report.read_text(encoding="utf-8")
        + '<a href="https://example.com/paper?status=published&amp;score=10&amp;role=reader">'
        + "Public paper</a>",
        encoding="utf-8",
    )

    archive_git._validate_archive(
        checkout / "archive",
        run_dir.name,
        "https://example.com/research-radar/archive",
    )


def test_archive_validation_rejects_structured_private_metadata(tmp_path: Path) -> None:
    checkout, _ = _pages_checkout(tmp_path)
    run_dir = _write_run(tmp_path)
    publish_archive_git(run_dir, _settings(checkout))
    metadata_path = checkout / "archive/reports/2026-07-17-agent-memory/metadata.json"
    metadata = read_json(metadata_path)
    metadata["role"] = "primary_paper"
    write_json(metadata_path, metadata)

    with pytest.raises(PublishError, match="role"):
        archive_git._validate_archive(
            checkout / "archive",
            run_dir.name,
            "https://example.com/research-radar/archive",
        )


def test_archive_git_command_timeout_is_reported(monkeypatch, tmp_path: Path) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=120)

    monkeypatch.setattr(archive_git.subprocess, "run", timeout)

    with pytest.raises(PublishError, match="timed out"):
        archive_git._git(tmp_path, "fetch", "origin", "gh-pages")


def _settings(checkout: Path) -> ArchivePublishConfig:
    return ArchivePublishConfig(
        checkout=checkout,
        output_subdir="archive",
        base_url="https://example.com/research-radar/archive",
        site_language="zh",
        remote="origin",
        branch="gh-pages",
    )


def _write_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs/2026-07-17-agent-memory"
    draft = ArticleDraft(
        title="ResearchRadar 日报：agent-memory",
        topic_id="agent-memory",
        digest="一份经过证据核验的研究日报。",
        lede="今天精读了 1 篇论文。",
        sections=[ArticleSection(title="今日摘要", body="已核验证据点：1 条。")],
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        metadata={"language": "zh", "deep_read_count": 1, "source_count": 1},
    )
    write_json(run_dir / "article_draft.json", draft)
    return run_dir


def _pages_checkout(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "pages"
    _command(tmp_path, "git", "init", "--bare", str(remote))
    _command(tmp_path, "git", "init", "-b", "gh-pages", str(checkout))
    _git(checkout, "config", "user.name", "ResearchRadar Tests")
    _git(checkout, "config", "user.email", "tests@example.com")
    (checkout / ".nojekyll").write_text("", encoding="utf-8")
    (checkout / "index.html").write_text("<a href='./archive/'>Archive</a>\n", encoding="utf-8")
    _git(checkout, "add", ".nojekyll", "index.html")
    _git(checkout, "commit", "-s", "-m", "seed pages")
    _git(checkout, "remote", "add", "origin", str(remote))
    _git(checkout, "push", "-u", "origin", "gh-pages")
    return checkout, remote


def _checkout_files(checkout: Path) -> list[str]:
    return sorted(
        path.relative_to(checkout).as_posix()
        for path in checkout.rglob("*")
        if ".git" not in path.parts
    )


def _git(cwd: Path, *args: str) -> str:
    return _command(cwd, "git", *args).stdout.strip()


def _command(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
