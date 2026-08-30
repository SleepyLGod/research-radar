"""Command-line interface for ResearchRadar."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.providers import Message
from research_radar.analysis.routing import (
    TaskModelRoute,
    TaskRoutePreview,
    resolve_task_route,
    resolve_task_route_preview,
)
from research_radar.application.daily import (
    DailyRunOptions,
    ProviderOverrides,
    build_daily_connectors,
    run_daily_application,
)
from research_radar.application.email import EmailDeliveryOptions, publish_email_application
from research_radar.application.wechat import (
    WeChatDraftOptions,
    append_wechat_draft_source_history,
    publish_wechat_draft,
)
from research_radar.compose.archive import export_archive_run
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.wechat import (
    render_wechat_html,
)
from research_radar.compose.zhihu import export_zhihu_run
from research_radar.config import AppConfig, load_config, parse_config
from research_radar.evaluation.topic_smoke import run_topic_smoke, select_topic_specs
from research_radar.evidence.ledger import load_claims
from research_radar.exceptions import ConfigError, PublishError, ResearchRadarError, SecretError
from research_radar.pipeline.daily import run_daily
from research_radar.pipeline.paper import run_paper
from research_radar.publishers.archive.git import publish_archive_git
from research_radar.publishers.wechat.client import (
    WeChatDraftClient,
)
from research_radar.scheduler.local import (
    DailyDraftScheduleSpec,
    execute_daily_draft_schedule,
    install_daily_draft_schedule,
    parse_daily_time,
    run_daily_draft_schedule_now,
    status_daily_draft_schedule,
    uninstall_daily_draft_schedule,
    write_daily_draft_schedule,
)
from research_radar.security.crypto import EnvelopeEncryptor, SecretMasterKeyProvider
from research_radar.security.privacy_scan import assert_clean
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import EnvSecretBackend, KeychainSecretBackend, SecretManager
from research_radar.storage.encrypted_store import EncryptedJsonStore
from research_radar.storage.files import write_json, write_text
from research_radar.topic_bootstrap import (
    bootstrap_topic_draft,
    render_topic_draft_yaml,
    write_topic_draft,
)


def main(argv: list[str] | None = None) -> None:
    """Run the ResearchRadar CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except ResearchRadarError as exc:
        print(redact_text(str(exc)), file=sys.stderr)
        raise SystemExit(1) from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(prog="research-radar")
    parser.set_defaults(handler=lambda args: parser.print_help())
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create local config from example files.")
    init_parser.add_argument("--root", type=Path, default=Path.cwd())
    init_parser.set_defaults(handler=handle_init)

    secrets_parser = subparsers.add_parser("secrets", help="Manage local secrets.")
    secrets_subparsers = secrets_parser.add_subparsers(dest="secrets_command", required=True)
    secrets_set = secrets_subparsers.add_parser("set", help="Set a secret group.")
    secrets_set.add_argument(
        "name",
        choices=[
            "deepseek",
            "xiaomi",
            "openai",
            "anthropic",
            "wechat",
            "github",
            "semantic-scholar",
            "web-search",
        ],
    )
    secrets_set.set_defaults(handler=handle_secrets_set)
    secrets_set_named = secrets_subparsers.add_parser(
        "set-named",
        help="Set one named secret such as kimi.api_key.",
    )
    secrets_set_named.add_argument("name", help="Secret storage name.")
    secrets_set_named.set_defaults(handler=handle_secrets_set_named)
    secrets_status = secrets_subparsers.add_parser(
        "status",
        help="Show whether known secrets are present without printing values.",
    )
    secrets_status.add_argument(
        "--name",
        default=None,
        help="Check one named secret instead of all known secrets.",
    )
    secrets_status.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Check secrets in Keychain or the current process environment.",
    )
    secrets_status.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before checking env-backed secrets.",
    )
    secrets_status.set_defaults(handler=handle_secrets_status)

    provider_parser = subparsers.add_parser("provider", help="Model provider utilities.")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command", required=True)
    provider_list = provider_subparsers.add_parser(
        "list",
        help="List configured provider instances without printing secrets.",
    )
    provider_list.add_argument("--config", type=Path, default=Path("config.yaml"))
    provider_list.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Check provider secrets in Keychain or the current process environment.",
    )
    provider_list.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before checking env-backed secrets.",
    )
    provider_list.set_defaults(handler=handle_provider_list)
    provider_routes = provider_subparsers.add_parser(
        "routes",
        help="Show resolved task routes without calling model providers.",
    )
    provider_routes.add_argument("--config", type=Path, default=Path("config.yaml"))
    provider_routes.add_argument(
        "--mode",
        choices=["daily", "paper", "eval", "topic-bootstrap"],
        default="daily",
        help="Route set to inspect.",
    )
    _add_provider_route_override_arguments(provider_routes)
    provider_routes.set_defaults(handler=handle_provider_routes)
    provider_probe = provider_subparsers.add_parser(
        "probe",
        help="Run a provider-only API probe without creating research artifacts.",
    )
    provider_probe.add_argument(
        "--provider",
        required=True,
        help="Provider instance from config.yaml, such as deepseek or kimi.",
    )
    provider_probe.add_argument("--model", default=None, help="Model id to probe.")
    provider_probe.add_argument("--config", type=Path, default=Path("config.yaml"))
    provider_probe.add_argument(
        "--probe",
        choices=["small", "json", "long"],
        default="small",
        help="Probe workload to run against the selected provider.",
    )
    provider_probe.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Read provider secrets from Keychain or the current process environment.",
    )
    provider_probe.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before reading env-backed secrets.",
    )
    provider_probe.set_defaults(handler=handle_provider_probe)

    topic_parser = subparsers.add_parser("topic", help="Topic profile utilities.")
    topic_subparsers = topic_parser.add_subparsers(dest="topic_command", required=True)
    topic_bootstrap = topic_subparsers.add_parser(
        "bootstrap",
        help="Create an editable topic profile draft.",
    )
    topic_bootstrap.add_argument("--topic", required=True)
    topic_bootstrap.add_argument("--config", type=Path, default=Path("config.yaml"))
    topic_bootstrap.add_argument("--root", type=Path, default=Path.cwd())
    topic_bootstrap.add_argument("--output", type=Path, default=None)
    topic_bootstrap.add_argument("--language", choices=["en", "zh"], default="en")
    topic_bootstrap.add_argument(
        "--provider",
        default=None,
        help="Compatibility default provider for the bootstrap task.",
    )
    topic_bootstrap.add_argument(
        "--model",
        default=None,
        help="Compatibility default model for the bootstrap task.",
    )
    topic_bootstrap.add_argument(
        "--deepseek-provider",
        default=None,
        help="Provider instance to use for tasks configured on DeepSeek.",
    )
    topic_bootstrap.add_argument(
        "--bootstrap-provider",
        default=None,
        help="Provider instance for topic bootstrap.",
    )
    topic_bootstrap.add_argument(
        "--bootstrap-model",
        default=None,
        help="Model for topic bootstrap.",
    )
    topic_bootstrap.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Read provider secrets from Keychain or the current process environment.",
    )
    topic_bootstrap.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before reading env-backed secrets.",
    )
    topic_bootstrap.set_defaults(handler=handle_topic_bootstrap)

    run_parser = subparsers.add_parser("run", help="Run a pipeline.")
    run_subparsers = run_parser.add_subparsers(dest="mode", required=True)
    daily = run_subparsers.add_parser("daily", help="Run daily monitoring.")
    daily.add_argument("--topic", required=True)
    daily.add_argument("--config", type=Path, default=Path("config.yaml"))
    daily.add_argument("--root", type=Path, default=Path.cwd())
    daily.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum candidates requested per connector query.",
    )
    daily.add_argument(
        "--deep-limit",
        type=int,
        default=1,
        help="Maximum relevant sources to ingest and deep-read with the selected provider.",
    )
    daily.add_argument(
        "--provider",
        default=None,
        help="Compatibility default provider for all model-backed daily tasks.",
    )
    daily.add_argument(
        "--model",
        default=None,
        help="Compatibility default model for all model-backed daily tasks.",
    )
    daily.add_argument(
        "--deepseek-provider",
        default=None,
        help="Provider instance to use for tasks configured on DeepSeek.",
    )
    daily.add_argument("--gist-provider", default=None, help="Provider instance for source gists.")
    daily.add_argument("--gist-model", default=None, help="Model for source gists.")
    daily.add_argument(
        "--reader-provider",
        default=None,
        help="Provider instance for deep reading.",
    )
    daily.add_argument("--reader-model", default=None, help="Model for deep reading.")
    daily.add_argument(
        "--verifier-provider",
        default=None,
        help="Provider instance for verification.",
    )
    daily.add_argument(
        "--verifier-model",
        default=None,
        help="Model for claim verification.",
    )
    daily.add_argument(
        "--anchor-repair-provider",
        default=None,
        help="Provider instance for quote-only anchor repair.",
    )
    daily.add_argument(
        "--anchor-repair-model",
        default=None,
        help="Model for quote-only anchor repair.",
    )
    daily.add_argument(
        "--localization-provider",
        default=None,
        help="Provider instance for report localization.",
    )
    daily.add_argument(
        "--localization-model",
        default=None,
        help="Model for report localization.",
    )
    daily.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Read provider secrets from Keychain or the current process environment.",
    )
    daily.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before reading env-backed secrets.",
    )
    daily.add_argument(
        "--language",
        choices=["en", "zh"],
        default=None,
        help="Override the configured report language.",
    )
    daily.add_argument(
        "--model-cache",
        action="store_true",
        help="Cache model responses under <root>/cache/model_calls for repeat local runs.",
    )
    daily.add_argument("--run-dir-output", type=Path, default=None, help=argparse.SUPPRESS)
    daily.set_defaults(handler=handle_run_daily)
    paper = run_subparsers.add_parser("paper", help="Run a single-paper deep reading.")
    paper.add_argument("--topic", required=True)
    paper.add_argument("--url", required=True)
    paper.add_argument("--config", type=Path, default=Path("config.yaml"))
    paper.add_argument("--root", type=Path, default=Path.cwd())
    paper.add_argument(
        "--provider",
        default=None,
        help="Compatibility default provider for paper reading and verification.",
    )
    paper.add_argument(
        "--model",
        default=None,
        help="Compatibility default model for paper reading and verification.",
    )
    paper.add_argument(
        "--deepseek-provider",
        default=None,
        help="Provider instance to use for tasks configured on DeepSeek.",
    )
    paper.add_argument(
        "--reader-provider",
        default=None,
        help="Provider instance for paper reading.",
    )
    paper.add_argument("--reader-model", default=None, help="Model for paper reading.")
    paper.add_argument(
        "--verifier-provider",
        default=None,
        help="Provider instance for verification.",
    )
    paper.add_argument(
        "--verifier-model",
        default=None,
        help="Model for claim verification.",
    )
    paper.add_argument(
        "--anchor-repair-provider",
        default=None,
        help="Provider instance for quote-only anchor repair.",
    )
    paper.add_argument(
        "--anchor-repair-model",
        default=None,
        help="Model for quote-only anchor repair.",
    )
    paper.add_argument(
        "--localization-provider",
        default=None,
        help="Provider instance for report localization.",
    )
    paper.add_argument(
        "--localization-model",
        default=None,
        help="Model for report localization.",
    )
    paper.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Read provider secrets from Keychain or the current process environment.",
    )
    paper.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before reading env-backed secrets.",
    )
    paper.add_argument(
        "--language",
        choices=["en", "zh"],
        default=None,
        help="Override the configured report language.",
    )
    paper.add_argument(
        "--model-cache",
        action="store_true",
        help="Cache model responses under <root>/cache/model_calls for repeat local runs.",
    )
    paper.set_defaults(handler=handle_run_paper)

    eval_parser = subparsers.add_parser("eval", help="Run evaluation harnesses.")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_target", required=True)
    eval_topics = eval_subparsers.add_parser("topics", help="Run the real-topic smoke suite.")
    eval_topics.add_argument(
        "--topics",
        nargs="*",
        default=None,
        help="Topic ids to run. Defaults to the built-in topic smoke suite.",
    )
    eval_topics.add_argument("--config", type=Path, default=Path("config.yaml"))
    eval_topics.add_argument(
        "--root",
        type=Path,
        default=Path("/private/tmp/research-radar-topic-smoke"),
    )
    eval_topics.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum candidates requested per connector query.",
    )
    eval_topics.add_argument(
        "--deep-limit",
        type=int,
        default=1,
        help="Maximum relevant sources to deep-read per topic.",
    )
    eval_topics.add_argument(
        "--topic-budget-seconds",
        type=_non_negative_float,
        default=0.0,
        help=(
            "Soft per-topic runtime budget. A topic exceeding this value is marked "
            "with a fit warning; 0 disables the budget."
        ),
    )
    eval_topics.add_argument(
        "--provider",
        default=None,
        help="Compatibility default provider for all model-backed eval tasks.",
    )
    eval_topics.add_argument(
        "--model",
        default=None,
        help="Compatibility default model for all model-backed eval tasks.",
    )
    eval_topics.add_argument(
        "--deepseek-provider",
        default=None,
        help="Provider instance to use for tasks configured on DeepSeek.",
    )
    eval_topics.add_argument(
        "--gist-provider",
        default=None,
        help="Provider instance for source gists.",
    )
    eval_topics.add_argument("--gist-model", default=None, help="Model for source gists.")
    eval_topics.add_argument(
        "--reader-provider",
        default=None,
        help="Provider instance for deep reading.",
    )
    eval_topics.add_argument("--reader-model", default=None, help="Model for deep reading.")
    eval_topics.add_argument(
        "--verifier-provider",
        default=None,
        help="Provider instance for verification.",
    )
    eval_topics.add_argument(
        "--verifier-model",
        default=None,
        help="Model for claim verification.",
    )
    eval_topics.add_argument(
        "--anchor-repair-provider",
        default=None,
        help="Provider instance for quote-only anchor repair.",
    )
    eval_topics.add_argument(
        "--anchor-repair-model",
        default=None,
        help="Model for quote-only anchor repair.",
    )
    eval_topics.add_argument(
        "--localization-provider",
        default=None,
        help="Provider instance for report localization.",
    )
    eval_topics.add_argument(
        "--localization-model",
        default=None,
        help="Model for report localization.",
    )
    eval_topics.add_argument(
        "--secret-source",
        choices=["keychain", "env"],
        default="keychain",
        help="Read provider secrets from Keychain or the current process environment.",
    )
    eval_topics.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Explicitly load local environment variables before reading env-backed secrets.",
    )
    eval_topics.add_argument(
        "--language",
        choices=["en", "zh"],
        default=None,
        help="Override the configured report language.",
    )
    eval_topics.add_argument(
        "--model-cache",
        action="store_true",
        help="Cache model responses under <root>/cache/model_calls for repeat local eval runs.",
    )
    eval_topics.set_defaults(handler=handle_eval_topics)

    compose_parser = subparsers.add_parser("compose", help="Compose article artifacts.")
    compose_subparsers = compose_parser.add_subparsers(dest="compose_target", required=True)
    compose_wechat = compose_subparsers.add_parser("wechat", help="Compose WeChat HTML.")
    compose_wechat.add_argument("--run", dest="run_dir", type=Path, required=True)
    compose_wechat.add_argument("--topic", default=None)
    compose_wechat.set_defaults(handler=handle_compose_wechat)
    compose_zhihu = compose_subparsers.add_parser(
        "zhihu",
        help="Export a Zhihu-ready Markdown article and safe images.",
    )
    compose_zhihu.add_argument("--run", dest="run_dir", type=Path, required=True)
    compose_zhihu.add_argument(
        "--asset-base-url",
        default=None,
        help="Optional public HTTP(S) base URL for images already hosted online.",
    )
    compose_zhihu.set_defaults(handler=handle_compose_zhihu)

    archive_parser = subparsers.add_parser("archive", help="Export public archive artifacts.")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_target", required=True)
    archive_export = archive_subparsers.add_parser(
        "export",
        help="Export one run into static archive HTML and RSS artifacts.",
    )
    archive_export.add_argument("--run", dest="run_dir", type=Path, required=True)
    archive_export.add_argument("--output", type=Path, required=True)
    archive_export.add_argument(
        "--base-url",
        required=True,
        help="Public base URL used for canonical report links and RSS entries.",
    )
    archive_export.add_argument(
        "--site-language",
        choices=["en", "zh"],
        default=None,
        help="Archive navigation language; defaults to the first report or existing archive.",
    )
    archive_export.set_defaults(handler=handle_archive_export)
    archive_publish_git = archive_subparsers.add_parser(
        "publish-git",
        help="Export one run and publish it through a configured Git checkout.",
    )
    archive_publish_git.add_argument("--run", dest="run_dir", type=Path, required=True)
    archive_publish_git.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Local config containing the archive checkout and public base URL.",
    )
    archive_publish_git.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate a temporary export without changing, committing, or pushing the checkout.",
    )
    archive_publish_git.set_defaults(handler=handle_archive_publish_git)

    publish_parser = subparsers.add_parser("publish", help="Publish draft artifacts.")
    publish_subparsers = publish_parser.add_subparsers(dest="publish_target", required=True)
    publish_wechat = publish_subparsers.add_parser("wechat-draft", help="Create a WeChat draft.")
    publish_wechat.add_argument("--run", dest="run_dir", type=Path, required=True)
    publish_wechat.add_argument("--title", required=True)
    publish_wechat.add_argument("--digest", required=True)
    publish_wechat.add_argument("--thumb-media-id", required=True)
    publish_wechat.add_argument("--author", default="ResearchRadar")
    publish_wechat.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare the draft request artifact without calling the WeChat API.",
    )
    publish_wechat.set_defaults(handler=handle_publish_wechat)
    publish_email = publish_subparsers.add_parser(
        "email",
        help="Send one verified report to a private email address through SMTP.",
    )
    publish_email.add_argument("--run", dest="run_dir", type=Path, required=True)
    publish_email.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Local config containing SMTP and recipient settings.",
    )
    publish_email.add_argument(
        "--dry-run",
        action="store_true",
        help="Write email.html and email.txt without connecting to SMTP.",
    )
    publish_email.add_argument(
        "--allow-resend",
        action="store_true",
        help="Explicitly allow sending a run that already has a successful email result.",
    )
    publish_email.set_defaults(handler=handle_publish_email)
    upload_thumb = publish_subparsers.add_parser(
        "wechat-upload-thumb",
        help="Upload a WeChat draft thumbnail image and print its media id.",
    )
    upload_thumb.add_argument("--image", type=Path, required=True)
    upload_thumb.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON file for the returned thumb media id and URL.",
    )
    upload_thumb.set_defaults(handler=handle_publish_wechat_thumb)

    schedule_parser = subparsers.add_parser("schedule", help="Create local schedules.")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_target", required=True)
    daily_draft = schedule_subparsers.add_parser(
        "daily-draft",
        help="Generate a local launchd job for daily WeChat draft creation.",
    )
    daily_draft.add_argument("--topic", required=True)
    daily_draft.add_argument("--time", required=True, help="Daily wall-clock time in HH:MM.")
    daily_draft.add_argument("--config", type=Path, required=True)
    daily_draft.add_argument("--root", type=Path, required=True)
    daily_draft.add_argument("--thumb-media-id", required=True)
    daily_draft.add_argument(
        "--title",
        default=None,
        help="WeChat draft title. Defaults to a ResearchRadar daily title for the topic.",
    )
    daily_draft.add_argument(
        "--digest",
        default=None,
        help="WeChat draft digest. Defaults to a short topic digest.",
    )
    daily_draft.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the generated plist and runner script.",
    )
    daily_draft.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum candidates requested per connector query.",
    )
    daily_draft.add_argument(
        "--deep-limit",
        type=int,
        default=1,
        help="Maximum sources to deep-read in the scheduled daily run.",
    )
    daily_draft.add_argument(
        "--language",
        choices=["en", "zh"],
        default=None,
        help="Optional scheduled report language override.",
    )
    daily_draft.add_argument(
        "--model-cache",
        action="store_true",
        help="Use the local model-call cache for repeated scheduled runs.",
    )
    daily_draft.add_argument(
        "--deepseek-provider",
        default=None,
        help="Provider instance to use for tasks configured on DeepSeek.",
    )
    daily_draft.add_argument(
        "--gist-provider",
        default=None,
        help="Provider instance for source gists.",
    )
    daily_draft.add_argument("--gist-model", default=None, help="Model for source gists.")
    daily_draft.add_argument(
        "--reader-provider",
        default=None,
        help="Provider instance for deep reading.",
    )
    daily_draft.add_argument("--reader-model", default=None, help="Model for deep reading.")
    daily_draft.add_argument(
        "--verifier-provider",
        default="codex",
        help="Provider instance for verification.",
    )
    daily_draft.add_argument(
        "--verifier-model",
        default=None,
        help="Model for claim verification.",
    )
    daily_draft.add_argument(
        "--anchor-repair-provider",
        default=None,
        help="Provider instance for quote-only anchor repair.",
    )
    daily_draft.add_argument(
        "--anchor-repair-model",
        default=None,
        help="Model for quote-only anchor repair.",
    )
    daily_draft.add_argument(
        "--localization-provider",
        default=None,
        help="Provider instance for report localization.",
    )
    daily_draft.add_argument(
        "--localization-model",
        default=None,
        help="Model for report localization.",
    )
    daily_draft.add_argument(
        "--publish-dry-run",
        action="store_true",
        help="Generated runner prepares draft artifacts without calling WeChat.",
    )
    daily_draft.set_defaults(handler=handle_schedule_daily_draft)
    for command, help_text, handler in (
        ("install", "Install a generated schedule with launchd.", handle_schedule_install),
        ("status", "Show launchd and last-run schedule status.", handle_schedule_status),
        ("run-now", "Run a generated schedule immediately.", handle_schedule_run_now),
        ("uninstall", "Unload an installed launchd schedule.", handle_schedule_uninstall),
    ):
        lifecycle = schedule_subparsers.add_parser(command, help=help_text)
        lifecycle.add_argument("--topic", required=True)
        lifecycle.add_argument("--root", type=Path, required=True)
        lifecycle.set_defaults(handler=handler)
    schedule_execute = schedule_subparsers.add_parser(
        "execute",
        help=argparse.SUPPRESS,
    )
    schedule_execute.add_argument("--schedule", type=Path, required=True)
    schedule_execute.set_defaults(handler=handle_schedule_execute)

    privacy_parser = subparsers.add_parser("privacy", help="Privacy utilities.")
    privacy_subparsers = privacy_parser.add_subparsers(dest="privacy_command", required=True)
    privacy_scan = privacy_subparsers.add_parser(
        "scan",
        help="Scan committed files for private data.",
    )
    privacy_scan.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    privacy_scan.set_defaults(handler=handle_privacy_scan)

    return parser


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _add_provider_route_override_arguments(parser: argparse.ArgumentParser) -> None:
    """Add route override flags shared by provider route inspection."""

    parser.add_argument("--provider", default=None, help="Compatibility default provider.")
    parser.add_argument("--model", default=None, help="Compatibility default model.")
    parser.add_argument(
        "--deepseek-provider",
        default=None,
        help="Provider instance to use for tasks configured on DeepSeek.",
    )
    parser.add_argument("--gist-provider", default=None, help="Provider instance for source gists.")
    parser.add_argument("--gist-model", default=None, help="Model for source gists.")
    parser.add_argument("--reader-provider", default=None, help="Provider instance for reading.")
    parser.add_argument("--reader-model", default=None, help="Model for reading.")
    parser.add_argument(
        "--verifier-provider",
        default=None,
        help="Provider instance for verification.",
    )
    parser.add_argument("--verifier-model", default=None, help="Model for verification.")
    parser.add_argument(
        "--anchor-repair-provider",
        default=None,
        help="Provider instance for quote-only anchor repair.",
    )
    parser.add_argument(
        "--anchor-repair-model",
        default=None,
        help="Model for quote-only anchor repair.",
    )
    parser.add_argument(
        "--localization-provider",
        default=None,
        help="Provider instance for report localization.",
    )
    parser.add_argument("--localization-model", default=None, help="Model for localization.")
    parser.add_argument(
        "--bootstrap-provider",
        default=None,
        help="Provider instance for topic bootstrap.",
    )
    parser.add_argument("--bootstrap-model", default=None, help="Model for topic bootstrap.")


def handle_init(args: argparse.Namespace) -> None:
    """Create local configuration if it does not exist."""

    root = args.root
    example = root / "config.example.yaml"
    target = root / "config.yaml"
    if not example.exists():
        raise ResearchRadarError(f"Missing config example: {example}")
    if target.exists():
        print("config.yaml already exists; leaving it unchanged.")
        return
    shutil.copyfile(example, target)
    print("Created config.yaml from config.example.yaml.")


def handle_secrets_set(args: argparse.Namespace) -> None:
    """Set provider secrets."""

    manager = SecretManager(KeychainSecretBackend())
    if args.name == "deepseek":
        manager.set_deepseek_api_key(_prompt_secret("DeepSeek API key"))
    elif args.name == "xiaomi":
        manager.backend.set_secret("xiaomi.api_key", _prompt_secret("Xiaomi API key"))
    elif args.name == "openai":
        manager.set_openai_api_key(_prompt_secret("OpenAI API key"))
    elif args.name == "anthropic":
        manager.set_anthropic_api_key(_prompt_secret("Anthropic API key"))
    elif args.name == "wechat":
        app_id = input("WeChat App ID: ").strip()
        app_secret = _prompt_secret("WeChat App Secret")
        manager.set_wechat_credentials(app_id, app_secret)
    elif args.name == "github":
        manager.set_github_token(_prompt_secret("GitHub token"))
    elif args.name == "semantic-scholar":
        manager.set_semantic_scholar_api_key(_prompt_secret("Semantic Scholar API key"))
    elif args.name == "web-search":
        manager.backend.set_secret("web_search.api_key", _prompt_secret("Web search API key"))
    print(f"Stored {args.name} secrets in the configured secret backend.")


def handle_secrets_set_named(args: argparse.Namespace) -> None:
    """Set one named secret in Keychain."""

    manager = SecretManager(KeychainSecretBackend())
    manager.backend.set_secret(args.name, _prompt_secret(f"Secret value for {args.name}"))
    print(f"Stored {args.name} in the configured secret backend.")


def handle_secrets_status(args: argparse.Namespace) -> None:
    """Print present/missing status for known secrets without printing values."""

    if args.env_file is not None:
        _load_env_file(args.env_file)
    manager = _secret_manager(args.secret_source)
    requested_name = getattr(args, "name", None)
    names = [requested_name] if requested_name else _known_secret_names()
    for name in names:
        try:
            manager.get_named_secret(name)
        except SecretError:
            status = "missing"
        else:
            status = "present"
        print(f"{name}: {status}")


def handle_provider_list(args: argparse.Namespace) -> None:
    """List configured providers without printing secret values."""

    if args.env_file is not None:
        _load_env_file(args.env_file)
    config = _load_routing_config(args.config)
    manager = _secret_manager(args.secret_source)
    providers = []
    for name in sorted(config.model_providers):
        provider_config = config.model_providers[name]
        providers.append(
            {
                "name": name,
                "kind": provider_config.kind,
                "host": _provider_host(provider_config.base_url),
                "command": provider_config.command or "",
                "timeout_seconds": provider_config.timeout_seconds,
                "thinking": provider_config.thinking or "",
                "reasoning_effort": provider_config.reasoning_effort or "",
                "secret": _provider_secret_status(provider_config.api_key_secret, manager),
            }
        )
    print(json.dumps({"providers": providers}, ensure_ascii=False, indent=2))


def handle_provider_routes(args: argparse.Namespace) -> None:
    """Print resolved task routes without calling providers."""

    config = _load_routing_config(args.config)
    routes = []
    for task_name in _provider_route_tasks(args.mode):
        preview = _resolve_route_preview_for_task(args, config, task_name)
        provider_config = config.model_providers.get(preview.provider_name)
        routes.append(
            {
                "task": task_name,
                "provider": preview.provider_name,
                "model": preview.model or "",
                "kind": provider_config.kind if provider_config else "local",
                "thinking": (provider_config.thinking if provider_config else None) or "",
                "reasoning_effort": (
                    provider_config.reasoning_effort if provider_config else None
                )
                or "",
            }
        )
    print(json.dumps({"mode": args.mode, "routes": routes}, ensure_ascii=False, indent=2))


def handle_provider_probe(args: argparse.Namespace) -> None:
    """Run a provider-only diagnostic probe."""

    if args.env_file is not None:
        _load_env_file(args.env_file)
    config = _load_routing_config(args.config)
    manager = _secret_manager(args.secret_source)
    route = resolve_task_route(
        config,
        manager,
        "provider_probe",
        provider_override=args.provider,
        model_override=args.model,
        default_local=False,
    )
    if route.provider is None or route.model is None:
        raise ResearchRadarError("Provider probe requires a non-local model provider.")
    provider_config = config.model_providers[route.provider_name]
    started = time.perf_counter()
    try:
        response = route.provider.complete(
            [Message(role="user", content=_provider_probe_prompt(args.probe))],
            model=route.model,
        )
    except ResearchRadarError as exc:
        duration = time.perf_counter() - started
        _print_probe_result(
            {
                "status": "failed",
                "probe": args.probe,
                "provider": route.provider_name,
                "model": route.model,
                "host": _provider_host(provider_config.base_url),
                "timeout_seconds": provider_config.timeout_seconds,
                "thinking": provider_config.thinking or "",
                "reasoning_effort": provider_config.reasoning_effort or "",
                "duration_seconds": round(duration, 3),
                "error_type": type(exc).__name__,
                "message": redact_text(str(exc)),
                "diagnostics": _probe_diagnostics(exc),
            }
        )
        raise

    duration = time.perf_counter() - started
    result: dict[str, object] = {
        "status": "succeeded",
        "probe": args.probe,
        "provider": route.provider_name,
        "model": route.model,
        "host": _provider_host(provider_config.base_url),
        "timeout_seconds": provider_config.timeout_seconds,
        "thinking": provider_config.thinking or "",
        "reasoning_effort": provider_config.reasoning_effort or "",
        "duration_seconds": round(duration, 3),
        "response_char_count": len(response.content),
        "response_excerpt": _probe_excerpt(response.content),
    }
    if args.probe == "json":
        try:
            _load_probe_json(response.content)
        except json.JSONDecodeError as exc:
            result.update(
                {
                    "status": "failed",
                    "json_valid": False,
                    "error_type": type(exc).__name__,
                    "message": "Provider probe failed: JSON response was not parseable.",
                }
            )
            _print_probe_result(result)
            raise ResearchRadarError(
                "Provider probe failed: JSON response was not parseable."
            ) from exc
        result["json_valid"] = True
    _print_probe_result(result)


def handle_topic_bootstrap(args: argparse.Namespace) -> None:
    """Create an editable topic profile draft."""

    if args.env_file is not None:
        _load_env_file(args.env_file)
    config = _load_routing_config(getattr(args, "config", Path("config.yaml")))
    manager = _secret_manager(args.secret_source)
    global_provider = getattr(args, "provider", None)
    if (
        global_provider is None
        and getattr(args, "bootstrap_provider", None) is None
        and getattr(args, "bootstrap_model", None) is None
        and getattr(args, "deepseek_provider", None) is None
        and getattr(args, "model", None) is None
    ):
        global_provider = "local"
    route = resolve_task_route(
        config,
        manager,
        "topic_bootstrap",
        provider_override=getattr(args, "bootstrap_provider", None),
        model_override=getattr(args, "bootstrap_model", None),
        global_provider=global_provider,
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=True,
    )
    topic = bootstrap_topic_draft(
        args.topic,
        language=args.language,
        provider=route.provider,
        model=route.model,
    )
    output_path = write_topic_draft(args.root, topic, output=args.output)
    print(f"Wrote topic draft: {output_path}")
    print()
    print("```yaml")
    print(render_topic_draft_yaml(topic).rstrip())
    print("```")


def handle_run_daily(args: argparse.Namespace) -> None:
    """Run daily monitoring."""

    if args.limit < 1:
        raise ResearchRadarError("--limit must be at least 1.")
    if args.deep_limit < 0:
        raise ResearchRadarError("--deep-limit cannot be negative.")
    if args.env_file is not None:
        _load_env_file(args.env_file)
    config = load_config(args.config)
    manager = _secret_manager(args.secret_source)
    run_dir = run_daily_application(
        DailyRunOptions(
            root=args.root,
            topic_id=args.topic,
            limit=args.limit,
            deep_limit=args.deep_limit,
            language=getattr(args, "language", None),
            model_cache=bool(getattr(args, "model_cache", False)),
            routes=ProviderOverrides(
                provider=getattr(args, "provider", None),
                model=getattr(args, "model", None),
                deepseek_provider=getattr(args, "deepseek_provider", None),
                gist_provider=getattr(args, "gist_provider", None),
                gist_model=getattr(args, "gist_model", None),
                reader_provider=getattr(args, "reader_provider", None),
                reader_model=getattr(args, "reader_model", None),
                verifier_provider=getattr(args, "verifier_provider", None),
                verifier_model=getattr(args, "verifier_model", None),
                anchor_repair_provider=getattr(args, "anchor_repair_provider", None),
                anchor_repair_model=getattr(args, "anchor_repair_model", None),
                localization_provider=getattr(args, "localization_provider", None),
                localization_model=getattr(args, "localization_model", None),
            ),
        ),
        config,
        manager,
        warning_listener=lambda message: print(message, file=sys.stderr),
        pipeline_runner=run_daily,
    )
    if getattr(args, "run_dir_output", None) is not None:
        write_text(args.run_dir_output, str(run_dir))
    print(f"Created run: {run_dir}")


def handle_run_paper(args: argparse.Namespace) -> None:
    """Run single-paper deep reading."""

    if args.env_file is not None:
        _load_env_file(args.env_file)
    config = load_config(args.config)
    manager = _secret_manager(args.secret_source)
    report_language = _report_language_for_topic(args, config)
    reader_route = resolve_task_route(
        config,
        manager,
        "deep_reading",
        provider_override=getattr(args, "reader_provider", None),
        model_override=getattr(args, "reader_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=False,
    )
    verifier_route = _resolve_verifier_route(args, config, manager, fallback=reader_route)
    anchor_repair_route = _resolve_anchor_repair_route(args, config, manager)
    localization_route = _resolve_localization_route(
        args,
        config,
        manager,
        report_language=report_language,
    )
    reader_route = _maybe_cached_route(reader_route, args.root, "deep_reading", args)
    verifier_route = _maybe_cached_route(verifier_route, args.root, "verifier", args)
    anchor_repair_route = _maybe_cached_route(
        anchor_repair_route,
        args.root,
        "anchor_repair",
        args,
    )
    localization_route = _maybe_cached_route(
        localization_route,
        args.root,
        "report_localization",
        args,
    )
    if reader_route.provider is None or reader_route.model is None:
        raise ResearchRadarError("Single-paper reading requires a non-local reader provider.")
    run_dir = run_paper(
        args.root,
        config,
        args.topic,
        args.url,
        reader_route.provider,
        model=reader_route.model,
        verifier=verifier_route.provider,
        verifier_model=verifier_route.model,
        anchor_repair_provider=anchor_repair_route.provider,
        anchor_repair_model=anchor_repair_route.model,
        localizer=localization_route.provider,
        localization_model=localization_route.model,
        language=getattr(args, "language", None),
    )
    print(f"Created paper run: {run_dir}")


def handle_eval_topics(args: argparse.Namespace) -> None:
    """Run the real-topic smoke evaluation."""

    if args.env_file is not None:
        _load_env_file(args.env_file)
    config = load_config(args.config)
    manager = _secret_manager(args.secret_source)
    gist_route = resolve_task_route(
        config,
        manager,
        "source_gist",
        provider_override=getattr(args, "gist_provider", None),
        model_override=getattr(args, "gist_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=True,
    )
    reader_route = resolve_task_route(
        config,
        manager,
        "deep_reading",
        provider_override=getattr(args, "reader_provider", None),
        model_override=getattr(args, "reader_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=False,
    )
    verifier_route = _resolve_verifier_route(args, config, manager, fallback=reader_route)
    anchor_repair_route = _resolve_anchor_repair_route(args, config, manager)
    report_language = getattr(args, "language", None)
    localization_route = _resolve_localization_route(
        args,
        config,
        manager,
        report_language=report_language,
    )
    gist_route = _maybe_cached_route(gist_route, args.root, "source_gist", args)
    reader_route = _maybe_cached_route(reader_route, args.root, "deep_reading", args)
    verifier_route = _maybe_cached_route(verifier_route, args.root, "verifier", args)
    anchor_repair_route = _maybe_cached_route(
        anchor_repair_route,
        args.root,
        "anchor_repair",
        args,
    )
    localization_route = _maybe_cached_route(
        localization_route,
        args.root,
        "report_localization",
        args,
    )
    connectors = build_daily_connectors(
        config,
        manager,
        warning_listener=lambda message: print(message, file=sys.stderr),
    )
    report = run_topic_smoke(
        args.root,
        config,
        connectors,
        gist_provider=gist_route.provider,
        gist_model=gist_route.model,
        reader=reader_route.provider,
        reader_model=reader_route.model,
        verifier=verifier_route.provider,
        verifier_model=verifier_route.model,
        anchor_repair_provider=anchor_repair_route.provider,
        anchor_repair_model=anchor_repair_route.model,
        localizer=localization_route.provider,
        localization_model=localization_route.model,
        specs=select_topic_specs(args.topics),
        limit=args.limit,
        deep_limit=args.deep_limit,
        topic_budget_seconds=args.topic_budget_seconds,
        language=getattr(args, "language", None),
    )
    print(f"Wrote topic smoke summary: {report.markdown_path}")
    if not report.passed:
        raise ResearchRadarError(f"Topic smoke failed: {report.markdown_path}")


def handle_compose_wechat(args: argparse.Namespace) -> None:
    """Compose WeChat HTML from the run article draft when available."""

    draft_path = args.run_dir / "article_draft.json"
    if draft_path.exists():
        write_text(args.run_dir / "wechat.html", render_wechat_html(load_article_draft(draft_path)))
        print(f"Wrote {args.run_dir / 'wechat.html'}")
        return

    claims = load_claims(args.run_dir / "claims.jsonl")
    topic_id = args.topic or args.run_dir.name
    from research_radar.compose.wechat import compose_wechat_html
    write_text(args.run_dir / "wechat.html", compose_wechat_html(topic_id, claims))
    print(f"Wrote {args.run_dir / 'wechat.html'}")


def handle_compose_zhihu(args: argparse.Namespace) -> None:
    """Export a verified article draft for manual Zhihu publishing."""

    result = export_zhihu_run(
        args.run_dir,
        asset_base_url=args.asset_base_url,
    )
    print(f"Wrote Zhihu body: {result.markdown_path}")
    print(f"Wrote Zhihu metadata: {result.metadata_path}")
    print(f"Wrote Zhihu assets: {result.asset_dir}")


def handle_archive_export(args: argparse.Namespace) -> None:
    """Export one run into a static public archive."""

    try:
        result = export_archive_run(
            args.run_dir,
            args.output,
            base_url=args.base_url,
            site_language=args.site_language,
        )
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    print(f"Wrote archive report: {result.report_path}")
    print(f"Wrote archive index: {result.index_path}")
    print(f"Wrote archive RSS: {result.feed_path}")


def handle_archive_publish_git(args: argparse.Namespace) -> None:
    """Publish one run through the configured static-site Git checkout."""

    config = load_config(args.config)
    result = publish_archive_git(
        args.run_dir,
        config.archive,
        dry_run=bool(args.dry_run),
    )
    if result.status == "dry_run":
        print(f"Archive Git preflight passed: {result.report_url}")
    elif result.status == "unchanged":
        print(f"Archive already up to date: {result.report_url}")
    else:
        print(f"Published archive report: {result.report_url} ({result.commit[:12]})")


def handle_publish_wechat(args: argparse.Namespace) -> None:
    """Create a WeChat draft."""

    result = publish_wechat_draft(
        WeChatDraftOptions(
            run_dir=args.run_dir,
            title=args.title,
            digest=args.digest,
            thumb_media_id=args.thumb_media_id,
            author=args.author,
            dry_run=bool(args.dry_run),
        ),
        client_factory=WeChatDraftClient,
        history_recorder=_append_wechat_draft_source_history,
    )
    if result["status"] == "dry_run":
        print(f"Prepared WeChat draft dry run: {args.run_dir / 'publish_wechat_draft.json'}")
    else:
        print(f"Created WeChat draft: {result['response']}")


def handle_publish_email(args: argparse.Namespace) -> None:
    """Prepare or send one private SMTP email from a verified article draft."""

    config = load_config(args.config)
    manager = _secret_manager(config.security.secret_backend)
    result = publish_email_application(
        EmailDeliveryOptions(
            run_dir=args.run_dir,
            dry_run=bool(args.dry_run),
            allow_resend=bool(args.allow_resend),
        ),
        config.email,
        manager,
    )
    if result.status == "dry_run":
        print(f"Prepared email preview: {args.run_dir / 'email.html'}")
    else:
        print(f"Sent private email to {result.recipient}")


def handle_publish_wechat_thumb(args: argparse.Namespace) -> None:
    """Upload a WeChat draft thumbnail image and print its media id."""

    if not args.image.exists():
        raise PublishError(f"WeChat thumbnail image not found: {args.image}")
    manager = SecretManager(KeychainSecretBackend())
    encryptor = EnvelopeEncryptor(SecretMasterKeyProvider(manager.backend))
    token_store = EncryptedJsonStore(Path("cache") / "wechat_token.enc.json", encryptor)
    client = WeChatDraftClient(manager, token_store)
    result = client.upload_permanent_image_material(args.image)
    payload = {
        "thumb_media_id": result["media_id"],
        "url": result.get("url", ""),
        "image_path": str(args.image),
    }
    if args.output is not None:
        write_json(args.output, payload)
    print(f"thumb_media_id: {payload['thumb_media_id']}")
    if payload["url"]:
        print(f"url: {payload['url']}")


def handle_schedule_daily_draft(args: argparse.Namespace) -> None:
    """Generate local launchd artifacts for a daily WeChat draft job."""

    if args.limit < 1:
        raise ResearchRadarError("--limit must be at least 1.")
    if args.deep_limit < 0:
        raise ResearchRadarError("--deep-limit cannot be negative.")
    hour, minute = parse_daily_time(args.time)
    config = load_config(args.config)
    config.topic(args.topic)
    output_dir = args.output_dir or args.root / "schedules" / f"daily-draft-{args.topic}"
    title = args.title or f"ResearchRadar 日报：{args.topic}"
    digest = args.digest or f"今日精选 {args.topic} 相关论文精读。"
    artifacts = write_daily_draft_schedule(
        DailyDraftScheduleSpec(
            topic_id=args.topic,
            hour=hour,
            minute=minute,
            config_path=args.config,
            root=args.root,
            thumb_media_id=args.thumb_media_id,
            title=title,
            digest=digest,
            project_dir=Path.cwd(),
            output_dir=output_dir,
            uv_path=_resolve_uv_executable(),
            limit=args.limit,
            deep_limit=args.deep_limit,
            language=args.language,
            model_cache=bool(args.model_cache),
            publish_dry_run=bool(args.publish_dry_run),
            deepseek_provider=getattr(args, "deepseek_provider", None),
            gist_provider=getattr(args, "gist_provider", None),
            gist_model=getattr(args, "gist_model", None),
            reader_provider=getattr(args, "reader_provider", None),
            reader_model=getattr(args, "reader_model", None),
            verifier_provider=getattr(args, "verifier_provider", None) or "codex",
            verifier_model=_scheduled_verifier_model(
                getattr(args, "verifier_provider", None) or "codex",
                getattr(args, "verifier_model", None),
            ),
            anchor_repair_provider=getattr(args, "anchor_repair_provider", None),
            anchor_repair_model=getattr(args, "anchor_repair_model", None),
            localization_provider=getattr(args, "localization_provider", None),
            localization_model=getattr(args, "localization_model", None),
        )
    )
    print("Generated local daily draft schedule artifacts:")
    print(f"  label: {artifacts.label}")
    print(f"  runner: {artifacts.runner_path}")
    print(f"  plist: {artifacts.plist_path}")
    print(f"  metadata: {artifacts.schedule_path}")
    print(f"  state: {artifacts.state_path}")
    print(f"  logs: {artifacts.log_dir}")
    print()
    print("Install with:")
    print(
        "  uv run research-radar schedule install "
        f"--topic {args.topic} --root {args.root}"
    )


def handle_schedule_install(args: argparse.Namespace) -> None:
    """Install one generated launchd schedule."""

    path = install_daily_draft_schedule(args.root, args.topic)
    print(f"Installed schedule: {path}")


def handle_schedule_status(args: argparse.Namespace) -> None:
    """Print current launchd and last-run schedule status."""

    status = status_daily_draft_schedule(args.root, args.topic)
    print(json.dumps(status, ensure_ascii=False, indent=2))


def handle_schedule_run_now(args: argparse.Namespace) -> None:
    """Run one generated schedule immediately."""

    result = run_daily_draft_schedule_now(args.root, args.topic)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def handle_schedule_uninstall(args: argparse.Namespace) -> None:
    """Unload one generated launchd schedule."""

    uninstall_daily_draft_schedule(args.root, args.topic)
    print(f"Uninstalled schedule: {args.topic}")


def handle_schedule_execute(args: argparse.Namespace) -> None:
    """Execute a generated schedule from its metadata snapshot."""

    result = execute_daily_draft_schedule(args.schedule)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _resolve_uv_executable() -> Path:
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise ConfigError(
            "Could not find `uv` on PATH. Run schedule generation from an environment "
            "where `uv` is available."
        )
    return Path(uv_path).resolve()


def _scheduled_verifier_model(provider_name: str, model_name: str | None) -> str | None:
    if model_name is not None:
        return model_name
    if provider_name == "codex":
        return "gpt-5.6-terra"
    return None


def handle_privacy_scan(args: argparse.Namespace) -> None:
    """Run the privacy scanner."""

    assert_clean(args.path)
    print("Privacy scan passed.")


def _append_wechat_draft_source_history(
    run_dir: Path,
    draft: Any,
    *,
    title: str,
) -> dict[str, object] | None:
    return append_wechat_draft_source_history(
        run_dir,
        draft,
        title=title,
    )


def _prompt_secret(label: str) -> str:
    value = getpass.getpass(f"{label}: ")
    if not value.strip():
        raise ResearchRadarError(f"{label} cannot be empty.")
    return value.strip()


def _secret_manager(secret_source: str) -> SecretManager:
    if secret_source == "env":
        return SecretManager(EnvSecretBackend())
    if secret_source == "keychain":
        return SecretManager(KeychainSecretBackend())
    raise ResearchRadarError(f"Unsupported secret source: {secret_source}")


def _known_secret_names() -> list[str]:
    return [
        "deepseek.api_key",
        "xiaomi.api_key",
        "openai.api_key",
        "anthropic.api_key",
        "wechat.app_id",
        "wechat.app_secret",
        "github.token",
        "semantic_scholar.api_key",
        "web_search.api_key",
    ]


def _provider_probe_prompt(probe: str) -> str:
    if probe == "small":
        return "Reply with exactly this text: ResearchRadar provider probe ok."
    if probe == "json":
        return (
            "Return only valid JSON, with no Markdown fences and no extra text. "
            'Use exactly this shape: {"status":"ok","provider_test":true,'
            '"items":["alpha","beta"],"count":2}.'
        )
    if probe == "long":
        return (
            "Write a structured LLM API transport stress-test response of about 1800 "
            "English words. "
            "Use short paragraphs, include numbered sections, and do not use Markdown tables."
        )
    raise ResearchRadarError(f"Unsupported provider probe: {probe}")


def _provider_host(endpoint: str | None) -> str:
    if endpoint is None:
        return ""
    return urlparse(endpoint).netloc or endpoint


def _provider_secret_status(
    secret_name: str | None,
    manager: SecretManager,
) -> str:
    if secret_name is None:
        return "not_required"
    try:
        manager.get_named_secret(secret_name)
    except SecretError:
        return "missing"
    return "present"


def _provider_route_tasks(mode: str) -> list[str]:
    if mode == "daily":
        return [
            "source_gist",
            "deep_reading",
            "anchor_repair",
            "verifier",
            "report_localization",
        ]
    if mode == "paper":
        return ["deep_reading", "anchor_repair", "verifier", "report_localization"]
    if mode == "eval":
        return [
            "source_gist",
            "deep_reading",
            "anchor_repair",
            "verifier",
            "report_localization",
        ]
    if mode == "topic-bootstrap":
        return ["topic_bootstrap"]
    raise ResearchRadarError(f"Unsupported provider route mode: {mode}")


def _resolve_route_preview_for_task(
    args: argparse.Namespace,
    config: AppConfig,
    task_name: str,
) -> TaskRoutePreview:
    if task_name == "verifier" and args.mode == "paper":
        reader_preview = _resolve_route_preview_for_task(args, config, "deep_reading")
        try:
            return _resolve_route_preview(args, config, task_name, default_local=False)
        except ConfigError:
            if getattr(args, "verifier_provider", None) or getattr(args, "provider", None):
                raise
            return reader_preview
    return _resolve_route_preview(
        args,
        config,
        task_name,
        default_local=args.mode != "paper" or task_name != "deep_reading",
    )


def _resolve_route_preview(
    args: argparse.Namespace,
    config: AppConfig,
    task_name: str,
    *,
    default_local: bool,
) -> TaskRoutePreview:
    provider_attr, model_attr = _route_override_attrs(task_name)
    global_provider = getattr(args, "provider", None)
    if (
        task_name == "topic_bootstrap"
        and global_provider is None
        and getattr(args, provider_attr, None) is None
        and getattr(args, model_attr, None) is None
        and getattr(args, "deepseek_provider", None) is None
        and getattr(args, "model", None) is None
    ):
        global_provider = "local"
    return resolve_task_route_preview(
        config,
        task_name,
        provider_override=getattr(args, provider_attr, None),
        model_override=getattr(args, model_attr, None),
        global_provider=global_provider,
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=default_local,
    )


def _route_override_attrs(task_name: str) -> tuple[str, str]:
    attrs = {
        "source_gist": ("gist_provider", "gist_model"),
        "deep_reading": ("reader_provider", "reader_model"),
        "anchor_repair": ("anchor_repair_provider", "anchor_repair_model"),
        "verifier": ("verifier_provider", "verifier_model"),
        "report_localization": ("localization_provider", "localization_model"),
        "topic_bootstrap": ("bootstrap_provider", "bootstrap_model"),
    }
    try:
        return attrs[task_name]
    except KeyError as exc:
        raise ResearchRadarError(f"Unsupported routed task: {task_name}") from exc


def _probe_excerpt(value: str, *, limit: int = 500) -> str:
    text = redact_text(value).replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _probe_diagnostics(exc: ResearchRadarError) -> dict[str, object]:
    diagnostics = getattr(exc, "diagnostics", {})
    if not isinstance(diagnostics, dict):
        return {}
    safe: dict[str, object] = {}
    for key, value in diagnostics.items():
        if key == "response_excerpt" and isinstance(value, str):
            safe[key] = _probe_excerpt(value)
        elif isinstance(value, str):
            safe[key] = redact_text(value)
        else:
            safe[key] = value
    return safe


def _load_probe_json(value: str) -> dict[str, object]:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    payload = json.loads(_extract_json_object_text(text))
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("JSON payload must be an object", text, 0)
    return payload


def _extract_json_object_text(text: str) -> str:
    if text.startswith("{"):
        return text
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


def _print_probe_result(result: dict[str, object]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _load_routing_config(path: Path) -> AppConfig:
    if path.exists():
        return load_config(path)
    return parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "bootstrap", "queries": ["topic bootstrap"]}],
        }
    )


def _resolve_daily_reader_route(
    args: argparse.Namespace,
    config: AppConfig,
    manager: SecretManager,
) -> TaskModelRoute:
    if args.deep_limit <= 0:
        return TaskModelRoute(provider=None, model=None, provider_name="local")
    return resolve_task_route(
        config,
        manager,
        "deep_reading",
        provider_override=getattr(args, "reader_provider", None),
        model_override=getattr(args, "reader_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=True,
    )


def _resolve_verifier_route(
    args: argparse.Namespace,
    config: AppConfig,
    manager: SecretManager,
    *,
    fallback: TaskModelRoute,
) -> TaskModelRoute:
    try:
        return resolve_task_route(
            config,
            manager,
            "verifier",
            provider_override=getattr(args, "verifier_provider", None),
            model_override=getattr(args, "verifier_model", None),
            global_provider=getattr(args, "provider", None),
            global_model=getattr(args, "model", None),
            provider_replacements=_deepseek_provider_replacements(args),
            default_local=False,
        )
    except ConfigError:
        if getattr(args, "verifier_provider", None) or getattr(args, "provider", None):
            raise
        return fallback


def _resolve_anchor_repair_route(
    args: argparse.Namespace,
    config: AppConfig,
    manager: SecretManager,
) -> TaskModelRoute:
    try:
        return resolve_task_route(
            config,
            manager,
            "anchor_repair",
            provider_override=getattr(args, "anchor_repair_provider", None),
            model_override=getattr(args, "anchor_repair_model", None),
            global_provider=getattr(args, "provider", None),
            global_model=getattr(args, "model", None),
            provider_replacements=_deepseek_provider_replacements(args),
            default_local=True,
        )
    except ConfigError:
        if getattr(args, "anchor_repair_provider", None) or getattr(args, "provider", None):
            raise
        return TaskModelRoute(provider=None, model=None, provider_name="local")


def _resolve_localization_route(
    args: argparse.Namespace,
    config: AppConfig,
    manager: SecretManager,
    *,
    report_language: str | None,
) -> TaskModelRoute:
    if report_language != "zh":
        return TaskModelRoute(provider=None, model=None, provider_name="local")
    try:
        return resolve_task_route(
            config,
            manager,
            "report_localization",
            provider_override=getattr(args, "localization_provider", None),
            model_override=getattr(args, "localization_model", None),
            global_provider=getattr(args, "provider", None),
            global_model=getattr(args, "model", None),
            provider_replacements=_deepseek_provider_replacements(args),
            default_local=True,
        )
    except ConfigError:
        if getattr(args, "localization_provider", None) or getattr(args, "provider", None):
            raise
        return TaskModelRoute(provider=None, model=None, provider_name="local")


def _deepseek_provider_replacements(args: argparse.Namespace) -> dict[str, str] | None:
    replacement = getattr(args, "deepseek_provider", None)
    if replacement is None:
        return None
    return {"deepseek": replacement}


def _report_language_for_topic(args: argparse.Namespace, config: AppConfig) -> str:
    override = getattr(args, "language", None)
    if override:
        return override
    return config.topic(args.topic).report_language


def _maybe_cached_route(
    route: TaskModelRoute,
    root: Path,
    task_name: str,
    args: argparse.Namespace,
) -> TaskModelRoute:
    if not getattr(args, "model_cache", False) or route.provider is None:
        return route
    return TaskModelRoute(
        provider=CachedLLMProvider(
            route.provider,
            cache_dir=root / "cache" / "model_calls",
            task_name=task_name,
        ),
        model=route.model,
        provider_name=route.provider_name,
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise ResearchRadarError(f"Environment file not found: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if not separator:
            raise ResearchRadarError(f"Invalid environment line in {path}: {key}")
        key = key.strip()
        if not key.isidentifier():
            raise ResearchRadarError(f"Invalid environment variable name in {path}: {key}")
        os.environ[key] = _strip_env_value(value.strip())


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
