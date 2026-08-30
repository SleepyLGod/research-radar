"""Production command handlers for the macOS engine bridge."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from research_radar import __version__
from research_radar.analysis.routing import resolve_task_route
from research_radar.app_bridge.configuration import LoadedAppConfigurationV1
from research_radar.app_bridge.events import EventWriter
from research_radar.app_bridge.pdf_helper import PDFHelperClient, app_figure_extractor
from research_radar.app_bridge.protocol import (
    BootstrapTopicPayloadV1,
    EngineRequestV1,
    PreflightPayloadV1,
    RetryDeliveryPayloadV1,
    RunDailyPayloadV1,
)
from research_radar.application.daily import DailyRunOptions, run_daily_application
from research_radar.application.email import EmailDeliveryOptions, publish_email_application
from research_radar.application.provider_probe import probe_provider
from research_radar.application.wechat import WeChatDraftOptions, publish_wechat_draft
from research_radar.compose.draft_io import load_article_draft
from research_radar.exceptions import ResearchRadarError
from research_radar.security.secrets import SecretBackend, SecretManager
from research_radar.storage.files import read_json
from research_radar.topic_bootstrap import bootstrap_topic_draft, lint_topic_draft


def handle_preflight(
    request: EngineRequestV1,
    *,
    config: LoadedAppConfigurationV1 | None,
    secrets: object,
    events: EventWriter,
    pdf_helper_path: Path | None,
) -> dict[str, object]:
    """Check the local engine and configured capabilities without exposing secrets."""

    from research_radar.app_bridge.runner import dependency_report

    payload = cast(PreflightPayloadV1, request.payload)
    checks = [
        {
            "id": "engine",
            "status": "ready",
            "message": (
                f"ResearchRadar {__version__} on Python "
                f"{sys.version_info.major}.{sys.version_info.minor}."
            ),
            "provider": None,
            "model": None,
        }
    ]
    dependencies = dependency_report()
    if not all(item.get("available") for item in dependencies.values()):
        checks[0]["status"] = "unavailable"
    if payload.live_probe and config is not None:
        checks.extend(_configured_route_checks(config, cast(SecretManager, secrets)))
    return {
        "ready": all(item["status"] in {"ready", "optional"} for item in checks),
        "checks": checks,
    }


def handle_bootstrap_topic(
    request: EngineRequestV1,
    *,
    config: LoadedAppConfigurationV1 | None,
    secrets: object,
    events: EventWriter,
    pdf_helper_path: Path | None,
) -> dict[str, object]:
    """Generate a reviewable topic profile without writing YAML."""

    payload = cast(BootstrapTopicPayloadV1, request.payload)
    events.write(
        "stage_changed",
        stage="topic_bootstrap",
        message="Drafting topic profile.",
    )
    topic = bootstrap_topic_draft(payload.description, language=payload.language)
    return {
        "id": topic.id,
        "display_name": topic.id.replace("-", " ").title(),
        "research_focus": payload.description,
        "queries": topic.queries,
        "paper_queries": topic.paper_queries,
        "web_queries": topic.web_queries,
        "exclusion_terms": topic.exclusion_terms,
        "required_phrases": topic.required_phrases,
        "concept_groups": topic.concept_groups,
        "negative_phrases": topic.negative_phrases,
        "priority_sources": topic.priority_sources,
        "source_intent": topic.source_intent,
        "report_language": topic.report_language,
        "warnings": lint_topic_draft(topic),
    }


def handle_run_daily(
    request: EngineRequestV1,
    *,
    config: LoadedAppConfigurationV1 | None,
    secrets: object,
    events: EventWriter,
    pdf_helper_path: Path | None,
) -> dict[str, object]:
    """Run the existing daily application service and summarize its public result."""

    if config is None:
        raise ValueError("run_daily requires App configuration.")
    payload = cast(RunDailyPayloadV1, request.payload)
    if (
        pdf_helper_path is None
        or not pdf_helper_path.is_file()
        or not pdf_helper_path.stat().st_mode & 0o111
    ):
        raise ValueError("run_daily requires an executable PDF helper.")
    run_dir = run_daily_application(
        DailyRunOptions(
            root=config.workspace_root,
            topic_id=payload.topic_id,
            limit=payload.limit,
            deep_limit=payload.deep_limit,
            language=payload.language,
            model_cache=payload.model_cache,
            model_cache_limit_bytes=payload.model_cache_limit_bytes,
        ),
        config.research,
        cast(SecretManager, secrets),
        progress_listener=_progress_listener(events),
        figure_extractor=app_figure_extractor(
            PDFHelperClient(pdf_helper_path),
            allowed_root=config.workspace_root,
        ),
    )
    draft = load_article_draft(run_dir / "article_draft.json")
    runtime = _optional_json(run_dir / "runtime_summary.json")
    return {
        "run_dir": str(run_dir),
        "report_date": payload.report_date,
        "article_draft_path": str(run_dir / "article_draft.json"),
        "report_html_path": str(run_dir / "wechat.html"),
        "title": draft.title,
        "summary": draft.lede,
        "source_count": _metadata_count(draft.metadata, "source_count"),
        "deep_read_count": _metadata_count(draft.metadata, "deep_read_count"),
        "publishable_claim_count": _metadata_count(runtime, "publishable_claim_count"),
    }


def handle_retry_delivery(
    request: EngineRequestV1,
    *,
    config: LoadedAppConfigurationV1 | None,
    secrets: object,
    events: EventWriter,
    pdf_helper_path: Path | None,
) -> dict[str, object]:
    """Retry exactly one configured delivery channel."""

    if config is None:
        raise ValueError("retry_delivery requires App configuration.")
    payload = cast(RetryDeliveryPayloadV1, request.payload)
    manager = cast(SecretManager, secrets)
    if payload.channel == "wechat":
        if not config.wechat.enabled:
            raise ValueError("WeChat delivery is not enabled.")
        draft = load_article_draft(payload.run_dir / "article_draft.json")
        publish_wechat_draft(
            WeChatDraftOptions(
                run_dir=payload.run_dir,
                title=draft.title,
                digest=draft.lede,
                thumb_media_id=config.wechat.thumb_media_id,
                author=config.wechat.author or "ResearchRadar",
            ),
            secret_manager=_wechat_secret_manager(manager, config),
        )
        status = "created"
    else:
        if not config.email_enabled:
            raise ValueError("Email delivery is not enabled.")
        publish_email_application(
            EmailDeliveryOptions(
                run_dir=payload.run_dir,
                allow_resend=payload.allow_resend,
            ),
            config.research.email,
            manager,
        )
        status = "sent"
    return {
        "run_dir": str(payload.run_dir),
        "channel": payload.channel,
        "status": status,
    }


class _AliasedSecretBackend:
    def __init__(self, backend: SecretBackend, aliases: dict[str, str]) -> None:
        self._backend = backend
        self._aliases = aliases

    def set_secret(self, name: str, value: str) -> None:
        self._backend.set_secret(self._aliases.get(name, name), value)

    def get_secret(self, name: str) -> str:
        return self._backend.get_secret(self._aliases.get(name, name))


def _wechat_secret_manager(
    manager: SecretManager,
    config: LoadedAppConfigurationV1,
) -> SecretManager:
    return SecretManager(
        _AliasedSecretBackend(
            manager.backend,
            {
                "wechat.app_id": config.wechat.app_id_secret,
                "wechat.app_secret": config.wechat.app_secret_secret,
            },
        )
    )


def _configured_route_checks(
    config: LoadedAppConfigurationV1,
    secrets: SecretManager,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    probe_status: dict[tuple[str, str], bool] = {}
    for task, route in sorted(config.research.models.task_routes.items()):
        key = (route.provider, route.model)
        if key not in probe_status:
            try:
                resolved = resolve_task_route(config.research, secrets, task)
                if resolved.provider is not None:
                    probe_provider(resolved, probe="small")
                probe_status[key] = True
            except ResearchRadarError:
                probe_status[key] = False
        ready = probe_status[key]
        checks.append(
            {
                "id": task,
                "status": "ready" if ready else "action_required",
                "message": (
                    "Provider route is ready."
                    if ready
                    else "Provider check failed. Review the provider and secret settings."
                ),
                "provider": route.provider,
                "model": route.model,
            }
        )
    return checks


def _progress_listener(events: EventWriter):
    stage_map = {
        "discovery": "discovery",
        "reader": "deep_reading",
        "verifier": "verifier",
        "localization": "localization",
        "artifacts": "compose",
    }

    def listener(event: dict[str, object]) -> None:
        stage = stage_map.get(str(event.get("stage", "")))
        if stage is None:
            return
        events.write(
            "progress",
            stage=stage,
            message=str(event.get("message") or "Research in progress."),
        )

    return listener


def _optional_json(path: Path) -> dict[str, object]:
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _metadata_count(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
