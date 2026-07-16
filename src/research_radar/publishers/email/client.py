"""Send a verified ArticleDraft to one private recipient through SMTP."""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.email import (
    EmailAsset,
    prepare_email_assets,
    render_email_html,
    render_email_text,
)
from research_radar.config import EmailPublishConfig
from research_radar.exceptions import PublishError, ResearchRadarError
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import SecretManager
from research_radar.storage.files import read_json, write_json, write_text


@dataclass(frozen=True)
class EmailPublishResult:
    """Outcome of preparing or sending one private email."""

    status: str
    run_id: str
    recipient: str
    image_count: int
    sent_at: str | None = None


def publish_email_run(
    run_dir: Path,
    settings: EmailPublishConfig,
    secret_manager: SecretManager,
    *,
    dry_run: bool = False,
    allow_resend: bool = False,
) -> EmailPublishResult:
    """Prepare and optionally send one evidence-gated daily report by email."""

    try:
        _validate_settings(settings)
        draft = load_article_draft(run_dir / "article_draft.json")
        assets = prepare_email_assets(draft, run_dir)
        preview_sources = {asset.raw_source: asset.preview_source for asset in assets}
        cid_sources = {asset.raw_source: f"cid:{asset.content_id}" for asset in assets}
        preview_html = render_email_html(draft, image_sources=preview_sources)
        plain_text = render_email_text(draft)
        write_text(run_dir / "email.html", preview_html)
        write_text(run_dir / "email.txt", plain_text)

        if dry_run:
            result = EmailPublishResult(
                status="dry_run",
                run_id=run_dir.name,
                recipient=settings.to_address or "",
                image_count=len(assets),
            )
            write_json(run_dir / "email_preview_result.json", asdict(result))
            return result

        _assert_not_already_sent(run_dir, allow_resend=allow_resend)
        password = secret_manager.get_named_secret(settings.password_secret)
        message = _build_message(
            draft.title,
            plain_text,
            render_email_html(draft, image_sources=cid_sources),
            settings,
            assets,
        )
        attempt_path = run_dir / "email_send_attempt.json"
        try:
            _send_message(
                message,
                settings,
                password,
                before_send=lambda: _write_email_attempt(
                    attempt_path,
                    status="sending",
                    run_id=run_dir.name,
                    recipient=settings.to_address or "",
                ),
            )
            sent_at = datetime.now(UTC).isoformat()
            result = EmailPublishResult(
                status="sent",
                run_id=run_dir.name,
                recipient=settings.to_address or "",
                image_count=len(assets),
                sent_at=sent_at,
            )
            _write_email_attempt(
                attempt_path,
                status="sent",
                run_id=run_dir.name,
                recipient=settings.to_address or "",
                completed_at=sent_at,
            )
            write_json(run_dir / "email_send_result.json", asdict(result))
        except (ResearchRadarError, OSError, smtplib.SMTPException):
            if attempt_path.exists():
                _write_email_attempt(
                    attempt_path,
                    status="delivery_unknown",
                    run_id=run_dir.name,
                    recipient=settings.to_address or "",
                    completed_at=datetime.now(UTC).isoformat(),
                )
            raise
        return result
    except (ResearchRadarError, OSError, smtplib.SMTPException) as exc:
        error = exc if isinstance(exc, PublishError) else PublishError(str(exc))
        write_json(
            run_dir / "email_send_error.json",
            {
                "target": "private_email",
                "stage": "publish",
                "error_type": type(error).__name__,
                "message": redact_text(str(error))[:500],
            },
        )
        if isinstance(exc, PublishError):
            raise
        raise error from exc


def _validate_settings(settings: EmailPublishConfig) -> None:
    required = {
        "email.smtp_host": settings.smtp_host,
        "email.username": settings.username,
        "email.from_address": settings.from_address,
        "email.to_address": settings.to_address,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise PublishError(f"Missing email configuration: {missing[0]}")
    if settings.security not in {"tls", "starttls"}:
        raise PublishError("Email transport must use tls or starttls")
    for field, value in (
        ("email.from_address", settings.from_address),
        ("email.to_address", settings.to_address),
    ):
        address = parseaddr(value or "")[1]
        if not address or "@" not in address:
            raise PublishError(f"{field} must be a valid email address")


def _assert_not_already_sent(run_dir: Path, *, allow_resend: bool) -> None:
    if allow_resend:
        return
    result_path = run_dir / "email_send_result.json"
    if result_path.exists():
        existing = read_json(result_path)
        if isinstance(existing, dict) and existing.get("status") == "sent":
            raise PublishError(
                "This run was already sent by email; pass --allow-resend to send it again"
            )
    if (run_dir / "email_send_attempt.json").exists():
        raise PublishError(
            "A previous email delivery is unresolved; pass --allow-resend only after checking "
            "the recipient inbox"
        )


def _write_email_attempt(
    path: Path,
    *,
    status: str,
    run_id: str,
    recipient: str,
    completed_at: str | None = None,
) -> None:
    payload = {
        "status": status,
        "run_id": run_id,
        "recipient": recipient,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if completed_at:
        payload["completed_at"] = completed_at
    write_json(path, payload)


def _build_message(
    subject: str,
    plain_text: str,
    html: str,
    settings: EmailPublishConfig,
    assets: list[EmailAsset],
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.from_address
    message["To"] = settings.to_address
    message.set_content(plain_text)
    message.add_alternative(html, subtype="html")
    html_part = message.get_payload()[-1]
    if not isinstance(html_part, EmailMessage):
        raise PublishError("Unable to build the HTML email body")
    for asset in assets:
        html_part.add_related(
            asset.source_path.read_bytes(),
            maintype="image",
            subtype=asset.mime_subtype,
            cid=f"<{asset.content_id}>",
            filename=asset.source_path.name,
            disposition="inline",
        )
    return message


def _send_message(
    message: EmailMessage,
    settings: EmailPublishConfig,
    password: str,
    *,
    before_send: Callable[[], None],
) -> None:
    context = ssl.create_default_context()
    if settings.security == "tls":
        with smtplib.SMTP_SSL(
            settings.smtp_host or "",
            settings.smtp_port,
            timeout=settings.timeout_seconds,
            context=context,
        ) as client:
            client.login(settings.username or "", password)
            before_send()
            client.send_message(message)
        return
    with smtplib.SMTP(
        settings.smtp_host or "",
        settings.smtp_port,
        timeout=settings.timeout_seconds,
    ) as client:
        client.starttls(context=context)
        client.login(settings.username or "", password)
        before_send()
        client.send_message(message)
