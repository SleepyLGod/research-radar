"""Log and text redaction utilities."""

from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b([\"']?[A-Za-z0-9_.-]*(?:api[_-]?key|app[_-]?secret|access[_-]?token|token|secret)[\"']?)"
        r"\s*[:=]\s*(['\"]?)[A-Za-z0-9._/-]{8,}\2"
    ),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"(?i)(openid|unionid)\s*[:=]\s*(['\"]?)[A-Za-z0-9_-]{8,}\2"),
]

LOCAL_PATH_PATTERN = re.compile(r"/Users/[^/\s]+(?:/[^\s]+)*")
PORT_PATTERN = re.compile(r"\b(?:127\.0\.0\.1|localhost):\d{2,5}\b")


def redact_text(value: str) -> str:
    """Redact sensitive tokens, local paths, and local ports from text."""

    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_replace_secret, redacted)
    redacted = LOCAL_PATH_PATTERN.sub("[LOCAL_PATH]", redacted)
    redacted = PORT_PATTERN.sub("[LOCAL_PORT]", redacted)
    return redacted


def _replace_secret(match: re.Match[str]) -> str:
    if len(match.groups()) >= 1:
        return f"{match.group(1)}=[REDACTED]"
    return "[REDACTED_SECRET]"
