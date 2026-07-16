"""Tests for private SMTP email publication."""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from research_radar.compose.archive_html import render_archive_article
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.wechat import render_wechat_html, render_wechat_publish_html
from research_radar.config import EmailPublishConfig
from research_radar.exceptions import PublishError
from research_radar.models import (
    ArticleDraft,
    ArticleSection,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
)
from research_radar.publishers.email import client as email_client
from research_radar.publishers.email.client import publish_email_run
from research_radar.security.secrets import InMemorySecretBackend, SecretManager
from research_radar.storage.files import read_json, write_json


def test_email_dry_run_writes_preview_without_connecting_smtp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_email_run(tmp_path, with_figure=True)
    manager = _secret_manager()

    def unexpected_smtp(*args, **kwargs):
        raise AssertionError("dry-run must not connect to SMTP")

    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", unexpected_smtp)

    result = publish_email_run(run_dir, _settings(), manager, dry_run=True)

    html = (run_dir / "email.html").read_text(encoding="utf-8")
    text = (run_dir / "email.txt").read_text(encoding="utf-8")
    assert result.status == "dry_run"
    assert "email-assets/architecture.png" in html
    assert str(run_dir) not in html
    assert "架构图" in html
    assert "Mandol 使用分层记忆结构" in text
    assert "Unsupported private claim" not in html
    assert (run_dir / "email-assets/architecture.png").is_file()


def test_email_send_uses_tls_cid_images_and_blocks_duplicate_send(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_email_run(tmp_path, with_figure=True)
    manager = _secret_manager()
    transport = _FakeSMTP()
    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", lambda *args, **kwargs: transport)

    result = publish_email_run(run_dir, _settings(), manager)

    assert result.status == "sent"
    assert result.image_count == 1
    assert transport.login_args == ("reader@example.com", "smtp-app-password")
    assert len(transport.messages) == 1
    message = transport.messages[0]
    assert message["Subject"] == "ResearchRadar 日报：agent-memory"
    assert message["From"] == "reader@example.com"
    assert message["To"] == "reader@example.com"
    html_part = next(part for part in message.walk() if part.get_content_type() == "text/html")
    assert "cid:rr-figure-1" in html_part.get_content()
    related = [part for part in message.walk() if part.get("Content-ID")]
    assert len(related) == 1
    assert related[0]["Content-ID"] == "<rr-figure-1>"
    assert related[0].get_content_type() == "image/png"
    assert read_json(run_dir / "email_send_result.json")["status"] == "sent"

    preview = publish_email_run(run_dir, _settings(), manager, dry_run=True)
    assert preview.status == "dry_run"
    assert read_json(run_dir / "email_preview_result.json")["status"] == "dry_run"
    assert read_json(run_dir / "email_send_result.json")["status"] == "sent"

    with pytest.raises(PublishError, match="already sent"):
        publish_email_run(run_dir, _settings(), manager)
    assert len(transport.messages) == 1

    resent = publish_email_run(run_dir, _settings(), manager, allow_resend=True)
    assert resent.status == "sent"
    assert len(transport.messages) == 2


def test_email_send_supports_starttls(monkeypatch, tmp_path: Path) -> None:
    run_dir = _write_email_run(tmp_path)
    manager = _secret_manager()
    transport = _FakeSMTP()
    monkeypatch.setattr(email_client.smtplib, "SMTP", lambda *args, **kwargs: transport)

    publish_email_run(
        run_dir,
        EmailPublishConfig(
            smtp_host="smtp.example.com",
            smtp_port=587,
            security="starttls",
            username="reader@example.com",
            password_secret="email.smtp_password",
            from_address="reader@example.com",
            to_address="reader@example.com",
        ),
        manager,
    )

    assert transport.starttls_called is True
    assert len(transport.messages) == 1


def test_email_uncertain_delivery_requires_explicit_resend(monkeypatch, tmp_path: Path) -> None:
    run_dir = _write_email_run(tmp_path)
    manager = _secret_manager()
    uncertain_transport = _FakeSMTP(fail_send=True)
    monkeypatch.setattr(
        email_client.smtplib,
        "SMTP_SSL",
        lambda *args, **kwargs: uncertain_transport,
    )

    with pytest.raises(PublishError):
        publish_email_run(run_dir, _settings(), manager)

    attempt = read_json(run_dir / "email_send_attempt.json")
    assert attempt["status"] == "delivery_unknown"
    assert not (run_dir / "email_send_result.json").exists()

    working_transport = _FakeSMTP()
    monkeypatch.setattr(
        email_client.smtplib,
        "SMTP_SSL",
        lambda *args, **kwargs: working_transport,
    )
    with pytest.raises(PublishError, match="previous email delivery"):
        publish_email_run(run_dir, _settings(), manager)
    assert not working_transport.messages

    result = publish_email_run(run_dir, _settings(), manager, allow_resend=True)
    assert result.status == "sent"
    assert len(working_transport.messages) == 1


def test_email_missing_figure_is_omitted_without_broken_image(tmp_path: Path) -> None:
    run_dir = _write_email_run(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    payload = read_json(draft_path)
    payload["sections"][1]["metadata"]["deep_reads"][0]["figures"][0][
        "relative_path"
    ] = "figures/missing.png"
    write_json(draft_path, payload)

    publish_email_run(run_dir, _settings(), _secret_manager(), dry_run=True)

    html = (run_dir / "email.html").read_text(encoding="utf-8")
    assert "<img" not in html
    assert "architecture.png" not in html


def test_email_export_does_not_mutate_draft_wechat_or_archive(tmp_path: Path) -> None:
    run_dir = _write_email_run(tmp_path, with_figure=True)
    draft_path = run_dir / "article_draft.json"
    draft = load_article_draft(draft_path)
    draft_before = draft_path.read_bytes()
    wechat_before = render_wechat_html(draft)
    wechat_publish_before = render_wechat_publish_html(draft)
    archive_before = render_archive_article(
        draft,
        run_id=run_dir.name,
        base_url="https://example.com/archive",
        site_language="zh",
        asset_map={},
    )

    publish_email_run(run_dir, _settings(), _secret_manager(), dry_run=True)

    assert draft_path.read_bytes() == draft_before
    reloaded = load_article_draft(draft_path)
    assert render_wechat_html(reloaded) == wechat_before
    assert render_wechat_publish_html(reloaded) == wechat_publish_before
    assert (
        render_archive_article(
            reloaded,
            run_id=run_dir.name,
            base_url="https://example.com/archive",
            site_language="zh",
            asset_map={},
        )
        == archive_before
    )


class _FakeSMTP:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.login_args: tuple[str, str] | None = None
        self.messages: list[EmailMessage] = []
        self.starttls_called = False
        self.fail_send = fail_send

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def starttls(self, *, context) -> None:
        self.starttls_called = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.messages.append(message)
        if self.fail_send:
            raise smtplib.SMTPServerDisconnected("connection lost after DATA")


def _settings() -> EmailPublishConfig:
    return EmailPublishConfig(
        smtp_host="smtp.example.com",
        smtp_port=465,
        security="tls",
        username="reader@example.com",
        password_secret="email.smtp_password",
        from_address="reader@example.com",
        to_address="reader@example.com",
    )


def _secret_manager() -> SecretManager:
    backend = InMemorySecretBackend()
    backend.set_secret("email.smtp_password", "smtp-app-password")
    return SecretManager(backend)


def _write_email_run(tmp_path: Path, *, with_figure: bool = False) -> Path:
    run_dir = tmp_path / "runs/2026-07-17-agent-memory"
    supported = Claim(
        text="Mandol 使用分层记忆结构。",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote="Layered memory.")],
    )
    unsupported = Claim(
        text="Unsupported private claim",
        status=ClaimStatus.UNSUPPORTED,
    )
    figures = []
    if with_figure:
        figures = [
            {
                "relative_path": "figures/architecture.png",
                "localized_caption": "架构图",
                "explanation": "这张图展示请求如何经过不同记忆层。",
                "renderable": True,
            }
        ]
        asset = run_dir / "figures/architecture.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    draft = ArticleDraft(
        title="ResearchRadar 日报：agent-memory",
        topic_id="agent-memory",
        digest="今日精选 agent-memory 论文精读。",
        lede="今天精读了 1 篇新论文。",
        claims=[supported, unsupported],
        sections=[
            ArticleSection(
                title="今日摘要",
                body="已核验证据点：1 条。",
                metadata={"kind": "today_summary"},
            ),
            ArticleSection(
                title="今日精读",
                body="",
                metadata={
                    "kind": "deep_reads",
                    "deep_reads": [
                        {
                            "title": "Mandol",
                            "source": {
                                "title": "Mandol",
                                "url": "https://example.com/paper",
                                "gist": "面向长期对话的 agent memory 系统。",
                            },
                            "reader_explanation": {
                                "opening_context": "长期对话需要稳定地保存和检索记忆。",
                                "solution_walkthrough": "Mandol 使用分层记忆结构。",
                                "reader_takeaway": "重点是控制检索过程，而不是堆更多数据库。",
                            },
                            "figures": figures,
                        }
                    ],
                },
            ),
            ArticleSection(
                title="延伸阅读",
                body="",
                metadata={
                    "kind": "new_updated_sources",
                    "sources": [
                        {
                            "title": "Related paper",
                            "url": "https://example.com/related",
                            "gist": "另一篇相关论文。",
                        }
                    ],
                },
            ),
        ],
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        metadata={"language": "zh", "deep_read_count": 1, "source_count": 2},
    )
    write_json(run_dir / "article_draft.json", draft)
    return run_dir
