"""Safe Git publication for a previously generated static archive."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree

from research_radar.compose.archive import export_archive_run
from research_radar.config import ArchivePublishConfig
from research_radar.exceptions import PublishError
from research_radar.security.redaction import redact_text
from research_radar.storage.files import write_json

_GIT_TIMEOUT_SECONDS = 120
_PRIVATE_METADATA_KEYS = {"role", "status", "score", "reuse_status"}
_PRIVATE_METADATA_TEXT = re.compile(
    r"\brole=[A-Za-z_][\w-]*\s*(?:[,;|·]|\s)\s*status=[A-Za-z_][\w-]*"
    r"(?:\s*(?:[,;|·]|\s)\s*score=-?\d+(?:\.\d+)?)?",
    flags=re.IGNORECASE,
)
_PRIVATE_REUSE_TEXT = re.compile(r"\breuse_status\s*=", flags=re.IGNORECASE)


@dataclass(frozen=True)
class ArchiveGitPublishResult:
    """Outcome of a Git-backed archive publication."""

    status: str
    run_id: str
    report_url: str
    commit: str
    dry_run: bool


def publish_archive_git(
    run_dir: Path,
    settings: ArchivePublishConfig,
    *,
    dry_run: bool = False,
) -> ArchiveGitPublishResult:
    """Export, validate, commit, and push one run to a Pages checkout."""

    try:
        return _publish_archive_git(run_dir, settings, dry_run=dry_run)
    except (OSError, ValueError, PublishError) as exc:
        error = exc if isinstance(exc, PublishError) else PublishError(str(exc))
        write_json(
            run_dir / "archive_publish_error.json",
            {
                "target": "archive_git",
                "stage": "publish",
                "error_type": type(error).__name__,
                "message": redact_text(str(error))[:500],
            },
        )
        if isinstance(exc, PublishError):
            raise
        raise error from exc


def _publish_archive_git(
    run_dir: Path,
    settings: ArchivePublishConfig,
    *,
    dry_run: bool,
) -> ArchiveGitPublishResult:
    checkout, output_dir = _validated_checkout(settings)
    _assert_checkout_ready(checkout, settings)
    _sync_remote(checkout, settings, allow_fast_forward=not dry_run)
    _preflight_export(run_dir, output_dir, settings)
    report_url = _report_url(settings.base_url or "", run_dir.name)
    if dry_run:
        result = ArchiveGitPublishResult(
            status="dry_run",
            run_id=run_dir.name,
            report_url=report_url,
            commit=_git(checkout, "rev-parse", "HEAD"),
            dry_run=True,
        )
        write_json(run_dir / "archive_publish_result.json", asdict(result))
        return result

    export_archive_run(
        run_dir,
        output_dir,
        base_url=settings.base_url or "",
        site_language=settings.site_language,
    )
    _validate_archive(output_dir, run_dir.name, settings.base_url or "")
    _git(checkout, "add", "--", settings.output_subdir)
    if _git_status(checkout, cached=True) == "":
        result = ArchiveGitPublishResult(
            status="unchanged",
            run_id=run_dir.name,
            report_url=report_url,
            commit=_git(checkout, "rev-parse", "HEAD"),
            dry_run=False,
        )
    else:
        _git(
            checkout,
            "commit",
            "-s",
            "-m",
            f"[publish] Update ResearchRadar archive: {run_dir.name}",
        )
        commit = _git(checkout, "rev-parse", "HEAD")
        _git(checkout, "push", settings.remote, f"HEAD:{settings.branch}")
        result = ArchiveGitPublishResult(
            status="published",
            run_id=run_dir.name,
            report_url=report_url,
            commit=commit,
            dry_run=False,
        )
    write_json(run_dir / "archive_publish_result.json", asdict(result))
    return result


def _validated_checkout(settings: ArchivePublishConfig) -> tuple[Path, Path]:
    if settings.checkout is None:
        raise PublishError("archive.checkout is required for Git publication")
    if not settings.base_url:
        raise PublishError("archive.base_url is required for Git publication")
    try:
        checkout = settings.checkout.resolve(strict=True)
    except OSError as exc:
        raise PublishError(f"Archive checkout not found: {settings.checkout}") from exc
    if not (checkout / ".git").exists():
        raise PublishError(f"Archive checkout is not a Git checkout: {checkout}")
    output_dir = checkout / settings.output_subdir
    try:
        output_dir.resolve().relative_to(checkout)
    except ValueError as exc:
        raise PublishError("archive.output_subdir must stay inside the checkout") from exc
    return checkout, output_dir


def _assert_checkout_ready(checkout: Path, settings: ArchivePublishConfig) -> None:
    branch = _git(checkout, "branch", "--show-current")
    if branch != settings.branch:
        raise PublishError(
            f"Archive checkout must be on {settings.branch}; "
            f"current branch is {branch or '<detached>'}"
        )
    if _git_status(checkout):
        raise PublishError("Archive checkout must be clean before publication")


def _sync_remote(
    checkout: Path,
    settings: ArchivePublishConfig,
    *,
    allow_fast_forward: bool,
) -> None:
    _git(checkout, "fetch", "--quiet", settings.remote, settings.branch)
    remote_ref = f"{settings.remote}/{settings.branch}"
    counts = _git(checkout, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}")
    try:
        ahead, behind = (int(value) for value in counts.split())
    except (TypeError, ValueError) as exc:
        raise PublishError("Unable to compare the archive checkout with its remote") from exc
    if ahead:
        raise PublishError("Archive checkout has unpushed commits; reconcile it before publishing")
    if behind:
        if not allow_fast_forward:
            raise PublishError(
                "Archive checkout is behind its remote; update it before running dry-run"
            )
        _git(checkout, "merge", "--ff-only", remote_ref)


def _preflight_export(
    run_dir: Path,
    output_dir: Path,
    settings: ArchivePublishConfig,
) -> None:
    with TemporaryDirectory(prefix="research-radar-archive-") as temp:
        staged_output = Path(temp) / settings.output_subdir
        if output_dir.exists():
            shutil.copytree(output_dir, staged_output)
        result = export_archive_run(
            run_dir,
            staged_output,
            base_url=settings.base_url or "",
            site_language=settings.site_language,
        )
        _validate_archive(staged_output, run_dir.name, settings.base_url or "")
        if not result.report_path.exists():
            raise PublishError("Archive preflight did not produce the report page")


def _validate_archive(output_dir: Path, run_id: str, base_url: str) -> None:
    required = [
        output_dir / "archive.json",
        output_dir / "index.html",
        output_dir / "feed.xml",
        output_dir / "reports" / run_id / "index.html",
        output_dir / "reports" / run_id / "metadata.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise PublishError(f"Archive validation found missing output: {missing[0]}")
    try:
        ElementTree.parse(output_dir / "feed.xml")
    except ElementTree.ParseError as exc:
        raise PublishError("Archive RSS is not valid XML") from exc

    banned = ("/" + "private/", "file" + "://")
    local_user_path = re.compile(r"/" r"Users/[^/\s]+")
    for path in output_dir.rglob("*"):
        if path.suffix.casefold() not in {".html", ".json", ".xml"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        marker = _private_metadata_marker(path, text)
        if marker is None:
            marker = next((item for item in banned if item in text), None)
        if marker is None and local_user_path.search(text):
            marker = "local user path"
        if marker:
            raise PublishError(f"Archive validation rejected public marker: {marker}")
        if path.suffix.casefold() == ".html":
            _validate_html_images(path, output_dir, text)
    report_url = _report_url(base_url, run_id)
    report_html = required[3].read_text(encoding="utf-8")
    if report_url not in report_html:
        raise PublishError("Archive report canonical URL does not match the configured base URL")


def _validate_html_images(path: Path, output_dir: Path, html: str) -> None:
    parser = _ImageSourceParser()
    parser.feed(html)
    output_root = output_dir.resolve(strict=True)
    for source in parser.sources:
        parsed = urlsplit(source)
        if parsed.scheme in {"http", "https"}:
            continue
        if parsed.scheme or parsed.netloc:
            raise PublishError(f"Archive image uses an unsupported URL: {source}")
        candidate = (path.parent / unquote(parsed.path)).resolve(strict=False)
        try:
            candidate.relative_to(output_root)
        except ValueError as exc:
            raise PublishError(f"Archive image escapes the output directory: {source}") from exc
        if not candidate.is_file():
            raise PublishError(f"Archive image is missing: {source}")


class _ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "img":
            return
        values = dict(attrs)
        source = values.get("src")
        if source:
            self.sources.append(source)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _private_metadata_marker(path: Path, text: str) -> str | None:
    if path.suffix.casefold() == ".json":
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise PublishError(f"Archive JSON is invalid: {path.name}") from exc
        marker = _find_private_metadata_key(payload)
        if marker:
            return marker
    visible_text = ""
    if path.suffix.casefold() == ".html":
        parser = _VisibleTextParser()
        parser.feed(text)
        visible_text = " ".join(parser.parts)
    elif path.suffix.casefold() == ".xml":
        try:
            visible_text = " ".join(ElementTree.fromstring(text).itertext())
        except ElementTree.ParseError as exc:
            raise PublishError(f"Archive XML is invalid: {path.name}") from exc
    if _PRIVATE_METADATA_TEXT.search(visible_text):
        return "internal source metadata"
    if _PRIVATE_REUSE_TEXT.search(visible_text):
        return "reuse_status"
    return None


def _find_private_metadata_key(value: object) -> str | None:
    if isinstance(value, dict):
        marker = next((key for key in _PRIVATE_METADATA_KEYS if key in value), None)
        if marker:
            return marker
        for item in value.values():
            marker = _find_private_metadata_key(item)
            if marker:
                return marker
    elif isinstance(value, list):
        for item in value:
            marker = _find_private_metadata_key(item)
            if marker:
                return marker
    return None


def _git_status(checkout: Path, *, cached: bool = False) -> str:
    args = ("diff", "--cached", "--name-only") if cached else ("status", "--porcelain")
    return _git(checkout, *args)


def _git(checkout: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PublishError(
            f"Git command timed out ({args[0]}) after {_GIT_TIMEOUT_SECONDS}s"
        ) from exc
    if completed.returncode != 0:
        detail = redact_text((completed.stderr or completed.stdout).strip())[:500]
        raise PublishError(f"Git command failed ({args[0]}): {detail or 'unknown error'}")
    return completed.stdout.strip()


def _report_url(base_url: str, run_id: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", f"reports/{run_id}/")
