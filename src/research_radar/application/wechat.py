"""Typed WeChat draft application service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_radar.compose.draft_io import load_article_draft
from research_radar.compose.wechat import render_wechat_publish_html, wechat_publish_html_issues
from research_radar.exceptions import PublishError, ResearchRadarError
from research_radar.publishers.wechat.client import WeChatArticle, WeChatDraftClient
from research_radar.security.crypto import EnvelopeEncryptor, SecretMasterKeyProvider
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import KeychainSecretBackend, SecretManager
from research_radar.storage.encrypted_store import EncryptedJsonStore
from research_radar.storage.files import read_jsonl, write_json, write_text
from research_radar.storage.source_history import append_source_history_outcome_records


@dataclass(frozen=True)
class WeChatDraftOptions:
    """Inputs for preparing or creating one WeChat draft."""

    run_dir: Path
    title: str
    digest: str
    thumb_media_id: str
    author: str = "ResearchRadar"
    dry_run: bool = False


def publish_wechat_draft(
    options: WeChatDraftOptions,
    *,
    secret_manager: SecretManager | None = None,
    client_factory: type[WeChatDraftClient] = WeChatDraftClient,
    history_recorder: Callable[..., dict[str, object] | None] | None = None,
) -> dict[str, object]:
    """Prepare or create one WeChat draft from the verified ArticleDraft."""

    try:
        draft = load_article_draft(options.run_dir / "article_draft.json")
        content_path = options.run_dir / "wechat_publish.html"
        if options.dry_run:
            content = render_wechat_publish_html(draft)
            write_text(content_path, content)
            _assert_publish_html_safe(content, allow_missing_media=True)
            request = _publish_request(options, draft.topic_id, content_path)
            write_json(options.run_dir / "publish_wechat_draft_request.json", request)
            result = {"status": "dry_run", "draft_created": False, "request": request}
            write_json(options.run_dir / "publish_wechat_draft.json", result)
            return result

        manager = secret_manager or SecretManager(KeychainSecretBackend())
        encryptor = EnvelopeEncryptor(SecretMasterKeyProvider(manager.backend))
        token_store = EncryptedJsonStore(
            options.run_dir / "wechat_token.enc.json",
            encryptor,
        )
        client = client_factory(manager, token_store)
        media_url_map, media_uploads = _upload_local_media(options.run_dir, draft, client)
        content = render_wechat_publish_html(draft, media_url_map=media_url_map)
        write_text(content_path, content)
        _assert_publish_html_safe(content, allow_missing_media=False)
        request = _publish_request(
            options,
            draft.topic_id,
            content_path,
            media_uploads=media_uploads,
        )
        write_json(options.run_dir / "publish_wechat_draft_request.json", request)
        if _content_requires_media_upload(content):
            raise PublishError(
                "WeChat draft contains local figure images that were not uploaded."
            )
        article = WeChatArticle(
            title=options.title,
            author=options.author,
            digest=options.digest,
            content=content,
            thumb_media_id=options.thumb_media_id,
        )
        response = client.add_draft(article)
        history = _safe_append_source_history(
            options.run_dir,
            draft,
            options.title,
            history_recorder=history_recorder or append_wechat_draft_source_history,
        )
        result = {
            "status": "created",
            "draft_created": True,
            "request": request,
            "response": response,
            "media_uploads": media_uploads,
            "source_history_outcome": history,
        }
        write_json(options.run_dir / "publish_wechat_draft.json", result)
        return result
    except ResearchRadarError as exc:
        _write_publish_error(options.run_dir, exc)
        raise


def _publish_request(
    options: WeChatDraftOptions,
    topic_id: str,
    content_path: Path,
    *,
    media_uploads: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "target": "wechat_draft",
        "draft_only": True,
        "auto_publish": False,
        "topic_id": topic_id,
        "title": options.title,
        "author": options.author,
        "digest": options.digest,
        "thumb_media_id": options.thumb_media_id,
        "article_draft_path": str(options.run_dir / "article_draft.json"),
        "content_path": str(content_path),
        "media_uploads": media_uploads or [],
    }


def _upload_local_media(
    run_dir: Path,
    draft: object,
    client: WeChatDraftClient,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    media_url_map: dict[str, str] = {}
    uploads: list[dict[str, str]] = []
    for src, path in _local_media_paths(run_dir, draft).items():
        uploaded_url = client.upload_article_image(path)
        media_url_map[src] = uploaded_url
        uploads.append({"local_src": src, "uploaded_url": uploaded_url})
    return media_url_map, uploads


def _local_media_paths(run_dir: Path, draft: object) -> dict[str, Path]:
    media: dict[str, Path] = {}
    base = run_dir.resolve(strict=True)
    for figure in _draft_figures(draft):
        if figure.get("renderable") is False:
            continue
        src = str(figure.get("relative_path") or figure.get("asset_path") or "")
        if not src or not _is_local_media_src(src):
            continue
        if Path(src).is_absolute():
            raise PublishError(f"WeChat image path escapes the run directory: {src}")
        path = (base / src).resolve()
        if not path.is_relative_to(base):
            raise PublishError(f"WeChat image path escapes the run directory: {src}")
        if not path.exists():
            raise PublishError(f"WeChat image upload file not found: {path}")
        media[src] = path
    return media


def _draft_figures(draft: object) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for section in getattr(draft, "sections", []):
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
            if isinstance(raw_figures, list):
                figures.extend(item for item in raw_figures if isinstance(item, dict))
    return figures


def _is_local_media_src(src: str) -> bool:
    lowered = src.casefold()
    return not lowered.startswith(("https://", "http://", "data:"))


def _assert_publish_html_safe(content: str, *, allow_missing_media: bool) -> None:
    issues = wechat_publish_html_issues(content)
    if allow_missing_media:
        issues = [
            issue for issue in issues if issue != "local figure image remains in publish HTML"
        ]
    if issues:
        raise PublishError("WeChat publish HTML failed safety check: " + "; ".join(issues[:3]))


def _content_requires_media_upload(content: str) -> bool:
    return "Figure image requires WeChat media upload before publishing." in content


def _safe_append_source_history(
    run_dir: Path,
    draft: object,
    title: str,
    *,
    history_recorder: Callable[..., dict[str, object] | None],
) -> dict[str, object] | None:
    try:
        return history_recorder(run_dir, draft, title=title)
    except Exception as exc:  # Best-effort audit after the draft already exists.
        return {
            "status": "history_record_failed",
            "error_type": type(exc).__name__,
            "message": redact_text(str(exc)),
        }


def append_wechat_draft_source_history(
    run_dir: Path,
    draft: object,
    *,
    title: str,
) -> dict[str, object] | None:
    """Record successful draft delivery against same-report source history."""
    sources_path = run_dir / "sources.jsonl"
    if not sources_path.exists():
        return None
    urls = article_draft_source_urls(draft)
    sources = [row for row in read_jsonl(sources_path) if str(row.get("url") or "") in urls]
    if not sources:
        return None
    created_at = datetime.now(UTC).isoformat()
    outcome_by_url = {
        str(source["url"]): {
            "wechat_draft_status": "created",
            "wechat_title": title,
            "wechat_created_at": created_at,
        }
        for source in sources
        if source.get("url")
    }
    if not outcome_by_url:
        return None
    root = run_dir.parent.parent if run_dir.parent.name == "runs" else run_dir.parent
    return append_source_history_outcome_records(
        root,
        str(getattr(draft, "topic_id", "unknown")),
        sources,
        run_id=run_dir.name,
        event="wechat_draft",
        outcome_by_url=outcome_by_url,
    )


def article_draft_source_urls(draft: object) -> set[str]:
    """Return public source URLs represented in one ArticleDraft."""
    urls: set[str] = set()
    for section in getattr(draft, "sections", []):
        metadata = getattr(section, "metadata", {})
        if not isinstance(metadata, dict):
            continue
        for key in ("sources", "references"):
            raw_sources = metadata.get(key, [])
            if not isinstance(raw_sources, list):
                continue
            for source in raw_sources:
                if isinstance(source, dict) and source.get("url"):
                    urls.add(str(source["url"]))
        raw_deep_reads = metadata.get("deep_reads", [])
        if not isinstance(raw_deep_reads, list):
            continue
        for deep_read in raw_deep_reads:
            if not isinstance(deep_read, dict):
                continue
            source = deep_read.get("source")
            if isinstance(source, dict) and source.get("url"):
                urls.add(str(source["url"]))
    return urls


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
