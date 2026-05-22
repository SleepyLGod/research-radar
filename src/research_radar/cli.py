"""Command-line interface for ResearchRadar."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path

from research_radar.analysis.routing import TaskModelRoute, resolve_task_route
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
from research_radar.exceptions import ConfigError, ResearchRadarError, SecretError
from research_radar.pipeline.daily import run_daily
from research_radar.pipeline.paper import run_paper
from research_radar.pipeline.weekly import compose_weekly_from_run
from research_radar.publishers.wechat.client import (
    WeChatArticle,
    WeChatDraftClient,
    load_wechat_html,
)
from research_radar.security.crypto import EnvelopeEncryptor, SecretMasterKeyProvider
from research_radar.security.privacy_scan import assert_clean
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import EnvSecretBackend, KeychainSecretBackend, SecretManager
from research_radar.storage.encrypted_store import EncryptedJsonStore
from research_radar.storage.files import write_text
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
            "openai",
            "anthropic",
            "wechat",
            "github",
            "semantic-scholar",
            "web-search",
        ],
    )
    secrets_set.set_defaults(handler=handle_secrets_set)

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
        help="Topic ids to run. Defaults to the built-in three-topic smoke suite.",
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
    publish_wechat.set_defaults(handler=handle_publish_wechat)

    privacy_parser = subparsers.add_parser("privacy", help="Privacy utilities.")
    privacy_subparsers = privacy_parser.add_subparsers(dest="privacy_command", required=True)
    privacy_scan = privacy_subparsers.add_parser(
        "scan",
        help="Scan committed files for private data.",
    )
    privacy_scan.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    privacy_scan.set_defaults(handler=handle_privacy_scan)

    return parser


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
    gist_route = resolve_task_route(
        config,
        manager,
        "source_gist",
        provider_override=getattr(args, "gist_provider", None),
        model_override=getattr(args, "gist_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        default_local=True,
    )
    reader_route = _resolve_daily_reader_route(args, config, manager)
    anchor_repair_route = _resolve_anchor_repair_route(args, config, manager)
    verifier_route = resolve_task_route(
        config,
        manager,
        "verifier",
        provider_override=getattr(args, "verifier_provider", None),
        model_override=getattr(args, "verifier_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        default_local=True,
    )
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
        language=getattr(args, "language", None),
    )
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
    reader_route = resolve_task_route(
        config,
        manager,
        "deep_reading",
        provider_override=getattr(args, "reader_provider", None),
        model_override=getattr(args, "reader_model", None),
        global_provider=getattr(args, "provider", None),
        global_model=getattr(args, "model", None),
        default_local=False,
    )
    verifier_route = _resolve_verifier_route(args, config, manager, fallback=reader_route)
    anchor_repair_route = _resolve_anchor_repair_route(args, config, manager)
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
        default_local=False,
    )
    verifier_route = _resolve_verifier_route(args, config, manager, fallback=reader_route)
    anchor_repair_route = _resolve_anchor_repair_route(args, config, manager)
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
        specs=select_topic_specs(args.topics),
        limit=args.limit,
        deep_limit=args.deep_limit,
        language=getattr(args, "language", None),
    )
    print(f"Wrote topic smoke summary: {report.markdown_path}")
    if not report.passed:
        raise ResearchRadarError(f"Topic smoke failed: {report.markdown_path}")


def handle_compose_wechat(args: argparse.Namespace) -> None:
    """Compose WeChat HTML from claims."""

    claims = load_claims(args.run_dir / "claims.jsonl")
    topic_id = args.topic or args.run_dir.name
    from research_radar.compose.wechat import compose_wechat_html

    write_text(args.run_dir / "wechat.html", compose_wechat_html(topic_id, claims))
    print(f"Wrote {args.run_dir / 'wechat.html'}")


def handle_publish_wechat(args: argparse.Namespace) -> None:
    """Create a WeChat draft."""

    manager = SecretManager(KeychainSecretBackend())
    encryptor = EnvelopeEncryptor(SecretMasterKeyProvider(manager.backend))
    token_store = EncryptedJsonStore(args.run_dir / "wechat_token.enc.json", encryptor)
    client = WeChatDraftClient(manager, token_store)
    article = WeChatArticle(
        title=args.title,
        author=args.author,
        digest=args.digest,
        content=load_wechat_html(args.run_dir),
        thumb_media_id=args.thumb_media_id,
    )
    result = client.add_draft(article)
    print(f"Created WeChat draft: {result}")


def handle_privacy_scan(args: argparse.Namespace) -> None:
    """Run the privacy scanner."""

    assert_clean(args.path)
    print("Privacy scan passed.")


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
            default_local=True,
        )
    except ConfigError:
        if getattr(args, "anchor_repair_provider", None) or getattr(args, "provider", None):
            raise
        return TaskModelRoute(provider=None, model=None, provider_name="local")


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
    return GenericWebSearchConnector(web_search.endpoint, headers=headers)


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
