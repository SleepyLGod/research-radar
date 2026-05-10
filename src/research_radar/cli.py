"""Command-line interface for ResearchRadar."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path

from research_radar.analysis.deepseek import DeepSeekProvider
from research_radar.analysis.providers import LLMProvider
from research_radar.config import load_config
from research_radar.discovery.arxiv import ArxivConnector
from research_radar.discovery.github import GitHubRepoConnector
from research_radar.discovery.semantic_scholar import SemanticScholarConnector
from research_radar.evidence.ledger import load_claims
from research_radar.exceptions import ResearchRadarError
from research_radar.pipeline.daily import run_daily
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
        choices=["deepseek", "openai", "wechat", "github", "semantic-scholar"],
    )
    secrets_set.set_defaults(handler=handle_secrets_set)

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
        choices=["local", "deepseek"],
        default="local",
        help="Use local dry-run review or DeepSeek-backed model review.",
    )
    daily.add_argument(
        "--model",
        default=None,
        help="Model name for the selected provider. DeepSeek defaults to deepseek-chat.",
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
    daily.set_defaults(handler=handle_run_daily)
    weekly = run_subparsers.add_parser("weekly", help="Compose weekly draft from latest run.")
    weekly.add_argument("--topic", required=True)
    weekly.add_argument("--run", dest="run_dir", type=Path, required=True)
    weekly.set_defaults(handler=handle_run_weekly)

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
    elif args.name == "wechat":
        app_id = input("WeChat App ID: ").strip()
        app_secret = _prompt_secret("WeChat App Secret")
        manager.set_wechat_credentials(app_id, app_secret)
    elif args.name == "github":
        manager.set_github_token(_prompt_secret("GitHub token"))
    elif args.name == "semantic-scholar":
        manager.set_semantic_scholar_api_key(_prompt_secret("Semantic Scholar API key"))
    print(f"Stored {args.name} secrets in the configured secret backend.")


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
    connectors = [
        ArxivConnector(),
        SemanticScholarConnector(manager),
        GitHubRepoConnector(manager),
    ]
    verifier = _daily_verifier(args.provider, manager)
    deep_reader = _daily_deep_reader(args.provider, manager, args.deep_limit)
    verifier_model = _daily_verifier_model(args.provider, args.model)
    run_dir = run_daily(
        args.root,
        config,
        args.topic,
        connectors,
        verifier=verifier,
        verifier_model=verifier_model,
        limit=args.limit,
        deep_reader=deep_reader,
        deep_model=verifier_model,
        deep_limit=args.deep_limit,
    )
    print(f"Created run: {run_dir}")


def handle_run_weekly(args: argparse.Namespace) -> None:
    """Compose weekly artifacts from a run."""

    compose_weekly_from_run(args.run_dir, args.topic)
    print(f"Updated weekly draft artifacts in {args.run_dir}")


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


def _daily_verifier(provider_name: str, manager: SecretManager) -> LLMProvider | None:
    if provider_name == "local":
        return None
    if provider_name == "deepseek":
        return DeepSeekProvider(manager)
    raise ResearchRadarError(f"Unsupported provider: {provider_name}")


def _daily_verifier_model(provider_name: str, model: str | None) -> str | None:
    if provider_name == "deepseek":
        return model or "deepseek-chat"
    return model


def _daily_deep_reader(
    provider_name: str,
    manager: SecretManager,
    deep_limit: int,
) -> LLMProvider | None:
    if deep_limit <= 0:
        return None
    if provider_name == "deepseek":
        return DeepSeekProvider(manager)
    return None


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
