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
from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.wechat import (
    render_wechat_html,
    render_wechat_publish_html,
    wechat_publish_html_issues,
)
from research_radar.config import AppConfig, load_config, parse_config
from research_radar.discovery.arxiv import ArxivConnector
from research_radar.discovery.base import DiscoveryConnector
from research_radar.discovery.github import GitHubRepoConnector
from research_radar.discovery.openalex import OpenAlexConnector
from research_radar.discovery.semantic_scholar import SemanticScholarConnector
from research_radar.discovery.web_search import (
    TAVILY_SEARCH_ENDPOINT,
    GenericWebSearchConnector,
    TavilyWebSearchConnector,
)
from research_radar.evaluation.topic_smoke import run_topic_smoke, select_topic_specs
from research_radar.evidence.ledger import load_claims
from research_radar.exceptions import ConfigError, PublishError, ResearchRadarError, SecretError
from research_radar.pipeline.daily import run_daily
from research_radar.pipeline.paper import run_paper
from research_radar.pipeline.weekly import compose_weekly_from_run
from research_radar.publishers.wechat.client import (
    WeChatArticle,
    WeChatDraftClient,
)
from research_radar.scheduler.local import (
    DailyDraftScheduleSpec,
    parse_daily_time,
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
    weekly = run_subparsers.add_parser("weekly", help="Compose weekly draft from latest run.")
    weekly.add_argument("--topic", required=True)
    weekly.add_argument("--run", dest="run_dir", type=Path, required=True)
    weekly.set_defaults(handler=handle_run_weekly)

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

    privacy_parser = subparsers.add_parser("privacy", help="Privacy utilities.")
    privacy_subparsers = privacy_parser.add_subparsers(dest="privacy_command", required=True)
    privacy_scan = privacy_subparsers.add_parser(
        "scan",
        help="Scan committed files for private data.",
    )
    privacy_scan.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    privacy_scan.set_defaults(handler=handle_privacy_scan)

    return parser


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
    connectors = _daily_connectors(config, manager)
    report_language = _report_language_for_topic(args, config)
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
    reader_route = _resolve_daily_reader_route(args, config, manager)
    anchor_repair_route = _resolve_anchor_repair_route(args, config, manager)
    localization_route = _resolve_localization_route(
        args,
        config,
        manager,
        report_language=report_language,
    )
    verifier_route = resolve_task_route(
        config,
        manager,
        "verifier",
        provider_override=getattr(args, "verifier_provider", None),
        model_override=getattr(args, "verifier_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        provider_replacements=_deepseek_provider_replacements(args),
        default_local=True,
    )
    gist_route = _maybe_cached_route(gist_route, args.root, "source_gist", args)
    reader_route = _maybe_cached_route(reader_route, args.root, "deep_reading", args)
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
    verifier_route = _maybe_cached_route(verifier_route, args.root, "verifier", args)
    run_dir = run_daily(
        args.root,
        config,
        args.topic,
        connectors,
        verifier=verifier_route.provider,
        verifier_model=verifier_route.model,
        gist_provider=gist_route.provider,
        gist_model=gist_route.model,
        limit=args.limit,
        deep_reader=reader_route.provider,
        deep_model=reader_route.model,
        deep_limit=args.deep_limit,
        anchor_repair_provider=anchor_repair_route.provider,
        anchor_repair_model=anchor_repair_route.model,
        localizer=localization_route.provider,
        localization_model=localization_route.model,
        language=getattr(args, "language", None),
    )
    if getattr(args, "run_dir_output", None) is not None:
        write_text(args.run_dir_output, str(run_dir))
    print(f"Created run: {run_dir}")


def handle_run_weekly(args: argparse.Namespace) -> None:
    """Compose weekly artifacts from a run."""

    compose_weekly_from_run(args.run_dir, args.topic)
    print(f"Updated weekly draft artifacts in {args.run_dir}")


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
    connectors = _daily_connectors(config, manager)
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


def handle_publish_wechat(args: argparse.Namespace) -> None:
    """Create a WeChat draft."""

    try:
        draft = load_article_draft(args.run_dir / "article_draft.json")
        publish_content_path = args.run_dir / "wechat_publish.html"
        if args.dry_run:
            content = render_wechat_publish_html(draft)
            write_text(publish_content_path, content)
            _assert_wechat_publish_html_safe(content, allow_missing_media=True)
            request = _wechat_publish_request(
                args,
                draft_topic=draft.topic_id,
                content_path=publish_content_path,
            )
            write_json(args.run_dir / "publish_wechat_draft_request.json", request)
            result = {
                "status": "dry_run",
                "draft_created": False,
                "request": request,
            }
            write_json(args.run_dir / "publish_wechat_draft.json", result)
            print(f"Prepared WeChat draft dry run: {args.run_dir / 'publish_wechat_draft.json'}")
            return
        manager = SecretManager(KeychainSecretBackend())
        encryptor = EnvelopeEncryptor(SecretMasterKeyProvider(manager.backend))
        token_store = EncryptedJsonStore(args.run_dir / "wechat_token.enc.json", encryptor)
        client = WeChatDraftClient(manager, token_store)
        media_url_map, media_uploads = _upload_local_wechat_media(args.run_dir, draft, client)
        content = render_wechat_publish_html(
            draft,
            media_url_map=media_url_map,
        )
        write_text(publish_content_path, content)
        _assert_wechat_publish_html_safe(content, allow_missing_media=False)
        request = _wechat_publish_request(
            args,
            draft_topic=draft.topic_id,
            content_path=publish_content_path,
            media_uploads=media_uploads,
        )
        write_json(args.run_dir / "publish_wechat_draft_request.json", request)
        if _publish_content_requires_media_upload(content):
            raise PublishError(
                "WeChat draft contains local figure images that were not uploaded."
            )
        article = WeChatArticle(
            title=args.title,
            author=args.author,
            digest=args.digest,
            content=content,
            thumb_media_id=args.thumb_media_id,
        )
        response = client.add_draft(article)
        result = {
            "status": "created",
            "draft_created": True,
            "request": request,
            "response": response,
            "media_uploads": media_uploads,
        }
        write_json(args.run_dir / "publish_wechat_draft.json", result)
        print(f"Created WeChat draft: {response}")
    except ResearchRadarError as exc:
        _write_publish_error(args.run_dir, exc)
        raise


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
    print(f"  logs: {artifacts.log_dir}")
    print()
    print("Install manually with:")
    print(f"  cp {artifacts.plist_path} ~/Library/LaunchAgents/")
    print(f"  launchctl load ~/Library/LaunchAgents/{artifacts.plist_path.name}")


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
        return "gpt-5.5"
    return None


def handle_privacy_scan(args: argparse.Namespace) -> None:
    """Run the privacy scanner."""

    assert_clean(args.path)
    print("Privacy scan passed.")


def _wechat_publish_request(
    args: argparse.Namespace,
    *,
    draft_topic: str,
    content_path: Path,
    media_uploads: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "target": "wechat_draft",
        "draft_only": True,
        "auto_publish": False,
        "topic_id": draft_topic,
        "title": args.title,
        "author": args.author,
        "digest": args.digest,
        "thumb_media_id": args.thumb_media_id,
        "article_draft_path": str(args.run_dir / "article_draft.json"),
        "content_path": str(content_path),
        "media_uploads": media_uploads or [],
    }


def _publish_content_requires_media_upload(content: str) -> bool:
    return "Figure image requires WeChat media upload before publishing." in content


def _assert_wechat_publish_html_safe(content: str, *, allow_missing_media: bool) -> None:
    issues = wechat_publish_html_issues(content)
    if allow_missing_media:
        issues = [
            issue for issue in issues if issue != "local figure image remains in publish HTML"
        ]
    if issues:
        raise PublishError("WeChat publish HTML failed safety check: " + "; ".join(issues[:3]))


def _upload_local_wechat_media(
    run_dir: Path,
    draft: object,
    client: WeChatDraftClient,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    local_media = _local_wechat_media_paths(run_dir, draft)
    media_url_map: dict[str, str] = {}
    uploads: list[dict[str, str]] = []
    for src, path in local_media.items():
        uploaded_url = client.upload_article_image(path)
        media_url_map[src] = uploaded_url
        uploads.append({"local_src": src, "uploaded_url": uploaded_url})
    return media_url_map, uploads


def _local_wechat_media_paths(run_dir: Path, draft: object) -> dict[str, Path]:
    media: dict[str, Path] = {}
    for figure in _draft_figures(draft):
        if figure.get("renderable") is False:
            continue
        src = str(figure.get("relative_path") or figure.get("asset_path") or "")
        if not src or not _is_local_media_src(src):
            continue
        path = Path(src)
        if not path.is_absolute():
            path = run_dir / src
        if not path.exists():
            raise PublishError(f"WeChat image upload file not found: {path}")
        media[src] = path
    return media


def _draft_figures(draft: object) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    sections = getattr(draft, "sections", [])
    for section in sections:
        metadata = getattr(section, "metadata", {})
        if not isinstance(metadata, dict) or metadata.get("kind") != "deep_reads":
            continue
        raw_deep_reads = metadata.get("deep_reads", [])
        if not isinstance(raw_deep_reads, list):
            continue
        for deep_read in raw_deep_reads:
            if not isinstance(deep_read, dict):
                continue
            raw_figures = deep_read.get("figures", [])
            if not isinstance(raw_figures, list):
                continue
            figures.extend(figure for figure in raw_figures if isinstance(figure, dict))
    return figures


def _is_local_media_src(src: str) -> bool:
    lowered = src.casefold()
    return not (
        lowered.startswith("https://")
        or lowered.startswith("http://")
        or lowered.startswith("data:")
    )


def _write_publish_error(run_dir: Path, exc: ResearchRadarError) -> None:
    write_json(
        run_dir / "publish_error.json",
        {
            "target": "wechat_draft",
            "stage": "publish",
            "error_type": type(exc).__name__,
            "message": redact_text(str(exc)),
        },
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


def _daily_connectors(
    config: AppConfig,
    manager: SecretManager,
) -> list[DiscoveryConnector]:
    connectors: list[DiscoveryConnector] = [
        ArxivConnector(),
        SemanticScholarConnector(manager),
        OpenAlexConnector(),
    ]
    web_search = _web_search_connector(config, manager)
    if web_search is not None:
        connectors.append(web_search)
    connectors.append(GitHubRepoConnector(manager))
    return connectors


def _web_search_connector(
    config: AppConfig,
    manager: SecretManager,
) -> DiscoveryConnector | None:
    web_search = config.discovery.web_search
    provider = web_search.provider or ("generic" if web_search.endpoint is not None else None)
    if provider is None:
        return None
    if provider == "tavily":
        secret_name = web_search.header_secret_name or "web_search.api_key"
        try:
            token = manager.get_named_secret(secret_name)
        except SecretError:
            print(
                "Web search disabled: missing configured Tavily API key.",
                file=sys.stderr,
            )
            return None
        return TavilyWebSearchConnector(
            api_key=token,
            endpoint=web_search.endpoint or TAVILY_SEARCH_ENDPOINT,
            max_results=web_search.max_results,
            search_depth=web_search.search_depth,
            timeout_seconds=web_search.timeout_seconds,
        )
    if web_search.endpoint is None:
        return None
    headers: dict[str, str] = {}
    if web_search.header_secret_name:
        try:
            token = manager.get_named_secret(web_search.header_secret_name)
        except SecretError:
            print(
                "Web search disabled: missing configured header secret.",
                file=sys.stderr,
            )
            return None
        headers["Authorization"] = f"Bearer {token}"
    return GenericWebSearchConnector(
        web_search.endpoint,
        headers=headers,
        timeout_seconds=web_search.timeout_seconds,
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
