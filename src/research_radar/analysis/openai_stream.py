"""Bounded SSE decoding into one complete Chat Completions response."""

from __future__ import annotations

import codecs
import json
import re
from collections.abc import Callable, Iterable, Iterator

from research_radar.security.redaction import redact_text

_MAX_STREAM_CHARS = 1_048_576
_LINE_END = re.compile(r"\r\n|\r|\n")
_ERROR_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/\[\]$~-]{1,128}")
_MODEL_ENVELOPE = re.compile(
    r"[\"'](?:reasoning_content|reasoning|choices|messages|content|delta|authorization|headers)[\"']\s*:",
    re.IGNORECASE,
)


class ChatStreamError(ValueError):
    """A fixed failure state and optional sanitized, bounded provider error fields."""

    def __init__(self, state: str, *, provider_error: dict[str, object] | None = None) -> None:
        super().__init__(state)
        self.state = state
        self.provider_error = provider_error or {}


def parse_chat_stream(
    chunks: Iterable[bytes], *, redact_error: Callable[[str], str] = redact_text,
) -> dict[str, object]:
    """Collect final-answer deltas; require one terminal choice and a DONE event."""

    content: list[str] = []
    content_chars = 0
    finish: str | None = None
    model: str | None = None
    tools = False
    refusal = False
    for data in _event_data(chunks):
        if data.strip() == "[DONE]":
            if finish is None:
                raise ChatStreamError("stream_missing_finish")
            message: dict[str, object] = {"content": "".join(content)}
            if tools:
                message["tool_calls"] = True
            if refusal:
                message["refusal"] = True
            return {"model": model, "choices": [{"message": message, "finish_reason": finish}]}
        try:
            payload = json.loads(data)
        except (ValueError, RecursionError):
            raise ChatStreamError("stream_invalid_json") from None
        if not isinstance(payload, dict):
            raise ChatStreamError("stream_invalid_shape")
        if "error" in payload:
            raise ChatStreamError(
                "stream_provider_error",
                provider_error=_provider_error_fields(payload["error"], redact_error),
            )
        reported = payload.get("model")
        if isinstance(reported, str) and reported:
            if model is not None and reported != model:
                raise ChatStreamError("stream_model_changed")
            model = reported
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ChatStreamError("stream_invalid_shape")
        if not choices and isinstance(payload.get("usage"), dict):
            continue
        if not choices or finish is not None:
            raise ChatStreamError("stream_invalid_shape")
        choice = choices[0]
        if (
            not isinstance(choice, dict) or type(choice.get("index", 0)) is not int
            or choice.get("index", 0) != 0 or not isinstance(choice.get("delta"), dict)
        ):
            raise ChatStreamError("stream_invalid_shape")
        delta = choice["delta"]
        text = delta.get("content")
        if text is not None:
            if not isinstance(text, str):
                raise ChatStreamError("invalid_message_content")
            content_chars += len(text)
            if content_chars > _MAX_STREAM_CHARS:
                raise ChatStreamError("stream_size_limit")
            if text:
                content.append(text)
        tools = tools or bool(delta.get("tool_calls") or delta.get("function_call"))
        refusal = refusal or bool(delta.get("refusal"))
        reason = choice.get("finish_reason")
        if reason is not None:
            if not isinstance(reason, str):
                raise ChatStreamError("stream_invalid_shape")
            finish = reason
    raise ChatStreamError("stream_missing_done")


def _provider_error_fields(
    error: object, redact: Callable[[str], str],
) -> dict[str, object]:
    """Copy scalar error fields only; never stringify an envelope or nested payload."""
    if isinstance(error, str):
        error = {"message": error}
    if not isinstance(error, dict):
        return {}
    safe: dict[str, object] = {}
    for key in ("code", "type", "param"):
        if key not in error:
            continue
        value = error[key]
        if value is None:
            safe[key] = None
        elif key == "code" and type(value) is int and abs(value) <= 10**12:
            safe[key] = value
        elif isinstance(value, str) and _ERROR_IDENTIFIER.fullmatch(value):
            sanitized = redact(value)
            if len(sanitized) <= 128:
                safe[key] = sanitized
    message = error.get("message")
    if isinstance(message, str) and message.strip() and not _MODEL_ENVELOPE.search(message):
        # Redact before cutting: a credential crossing the boundary must not leak a prefix.
        message = "".join(char if char.isprintable() else " " for char in redact(message))
        safe["message"] = message if len(message) <= 500 else message[:497] + "..."
    return safe


def _event_data(chunks: Iterable[bytes]) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    buffer = ""
    data: list[str] = []
    event_chars = 0

    def line_data(line: str) -> str | None:
        nonlocal event_chars
        if len(line) + event_chars > _MAX_STREAM_CHARS:
            raise ChatStreamError("stream_size_limit")
        if not line:
            if not data:
                return None
            result = "\n".join(data)
            data.clear()
            event_chars = 0
            return result
        field, _, value = line.partition(":")
        if field == "data":
            value = value.removeprefix(" ")
            data.append(value)
            event_chars += len(value) + 1
        return None

    for chunk in chunks:
        try:
            buffer += decoder.decode(chunk)
        except UnicodeError:
            raise ChatStreamError("stream_invalid_utf8") from None
        while match := _LINE_END.search(buffer):
            # A CR at a chunk boundary may be the first half of CRLF.
            if match[0] == "\r" and match.end() == len(buffer):
                break
            line, buffer = buffer[:match.start()], buffer[match.end():]
            event = line_data(line)
            if event is not None:
                yield event
        if len(buffer) + event_chars > _MAX_STREAM_CHARS:
            raise ChatStreamError("stream_size_limit")
    try:
        decoder.decode(b"", final=True)
    except UnicodeError:
        raise ChatStreamError("stream_invalid_utf8") from None
    if buffer.endswith("\r"):
        event = line_data(buffer[:-1])
        if event is not None:
            yield event
