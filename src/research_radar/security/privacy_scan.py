"""Privacy scanner for files intended to be committed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from research_radar.exceptions import PrivacyScanError

SKIP_DIRS = {
    ".git",
    ".venv",
    ".uv-cache",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "runs",
    "data",
    "cache",
    "secrets",
}

SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".lock"}
SKIP_NAMES = {".env", "config.yaml"}


@dataclass(frozen=True)
class PrivacyFinding:
    """A single privacy scan finding."""

    path: Path
    line_number: int
    kind: str
    line: str


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("local_path", re.compile(r"/Users/[^/\s]+")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
    (
        "api_key_assignment",
        re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9._/-]{12,}['\"]"),
    ),
    (
        "wechat_access_token",
        re.compile(r"(?i)access_token['\"]?\s*[:=]\s*['\"][A-Za-z0-9._-]{12,}['\"]"),
    ),
    ("openid", re.compile(r"(?i)(openid|unionid)['\"]?\s*[:=]\s*['\"][A-Za-z0-9_-]{8,}['\"]")),
]

_SMTP_PASSWORD_REFERENCE = re.compile(
    r"""password_secret\s*(?:(?::\s*str\s*=)|[:=])\s*['\"]?email\.smtp_password"""
    r"""['\"]?\s*,?\s*(?:#.*)?""",
    flags=re.IGNORECASE,
)


def scan_path(path: Path) -> list[PrivacyFinding]:
    """Scan a file or directory for privacy-sensitive strings."""

    if path.is_file():
        return _scan_file(path)
    findings: list[PrivacyFinding] = []
    for item in sorted(path.rglob("*")):
        if not item.is_file() or _should_skip(item):
            continue
        findings.extend(_scan_file(item))
    return findings


def assert_clean(path: Path) -> None:
    """Raise if privacy findings are detected."""

    findings = scan_path(path)
    if findings:
        lines = [
            f"{finding.path}:{finding.line_number}: {finding.kind}: {finding.line.strip()}"
            for finding in findings
        ]
        raise PrivacyScanError("Privacy scan failed:\n" + "\n".join(lines))


def _scan_file(path: Path) -> list[PrivacyFinding]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[PrivacyFinding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if _is_allowed_example_line(line):
            continue
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(PrivacyFinding(path=path, line_number=index, kind=kind, line=line))
    return findings


def _should_skip(path: Path) -> bool:
    return (
        path.name in SKIP_NAMES
        or bool(SKIP_DIRS.intersection(path.parts))
        or path.suffix.lower() in SKIP_SUFFIXES
    )


def _is_allowed_example_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    lowered = stripped.lower()
    if "fake" in lowered or "example" in lowered:
        return True
    if "api_key_secret" in lowered and ".api_key" in stripped:
        return True
    if _SMTP_PASSWORD_REFERENCE.fullmatch(stripped):
        return True
    if "local_path_pattern" in lowered or 're.compile(r"/users/' in lowered:
        return True
    if "private/tmp" in lowered and "var/folders" in lowered:
        return True
    if "/Users/someone" in stripped:
        return True
    if stripped.endswith("=") and any(
        name in stripped
        for name in [
            "DEEPSEEK_API_KEY",
            "XIAOMI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "WECHAT_APP_SECRET",
            "WECHAT_APP_ID",
            "GITHUB_TOKEN",
            "SEMANTIC_SCHOLAR_API_KEY",
            "WEB_SEARCH_API_KEY",
        ]
    ):
        return True
    return False
