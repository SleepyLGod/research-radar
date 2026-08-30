"""Typed private-email delivery application service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from research_radar.config import EmailPublishConfig
from research_radar.publishers.email.client import EmailPublishResult, publish_email_run
from research_radar.security.secrets import SecretManager


@dataclass(frozen=True)
class EmailDeliveryOptions:
    """One private-email delivery request."""

    run_dir: Path
    dry_run: bool = False
    allow_resend: bool = False


def publish_email_application(
    options: EmailDeliveryOptions,
    settings: EmailPublishConfig,
    secret_manager: SecretManager,
) -> EmailPublishResult:
    """Prepare or send one report through the existing email publisher."""

    return publish_email_run(
        options.run_dir,
        settings,
        secret_manager,
        dry_run=options.dry_run,
        allow_resend=options.allow_resend,
    )
