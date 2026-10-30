"""OpenAI-compatible chat completions provider."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from http.client import HTTPException, HTTPResponse, IncompleteRead, RemoteDisconnected
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from research_radar.analysis.openai_stream import ChatStreamError, parse_chat_stream
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import OperationCancelled, ProviderTransportError
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import SecretManager

_RESPONSE_FAILURES = {
    "output_limit": "response exhausted its output budget",
    "content_filtered": "response was blocked or refused",
    "unsupported_tool_call": "response requested an unsupported tool call",
    "invalid_finish_reason": "response did not finish normally",
    "missing_final_answer": "response did not contain a final answer",
    "invalid_message_content": "response content was not text",
}


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible chat completions APIs."""

    def __init__(
        self,
        *,
        name: str,
        endpoint: str,
        api_key_secret: str,
        secrets: SecretManager,
        timeout_seconds: int = 120,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        cancellation_event: Event | None = None,
    ) -> None:
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
            raise ValueError("max_tokens must be a positive integer.")
        if type(stream) is not bool:
            raise ValueError("stream must be a boolean.")
        self.name = name
        self.endpoint = endpoint
        self._api_key_secret = api_key_secret
        self._secrets = secrets
        self._timeout_seconds = timeout_seconds
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.stream = stream
        self._cancellation_event = cancellation_event
        identity_parts = [f"endpoint_sha256={hashlib.sha256(endpoint.encode('utf-8')).hexdigest()}"]
        if thinking is not None:
            identity_parts.append(f"thinking={thinking}")
        if reasoning_effort is not None:
            identity_parts.append(f"reasoning_effort={reasoning_effort}")
        if max_tokens is not None:
            identity_parts.append(f"max_tokens={max_tokens}")
        if stream:
            identity_parts.append("stream=true")
        self.cache_identity = ";".join(identity_parts)

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Call a chat completions endpoint and return normalized content."""

        self._check_cancelled()
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if self.thinking is not None:
            payload["thinking"] = {"type": self.thinking}
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.stream:
            payload["stream"] = True
        if self.thinking != "enabled" and self.reasoning_effort is None:
            payload["temperature"] = 0.2
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._secrets.get_named_secret(self._api_key_secret)}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started_at = time.monotonic()
        deadline = started_at + self._timeout_seconds
        for attempt in (1, 2):
            self._check_cancelled()
            raw_response = ""
            timeout = self._timeout_seconds if attempt == 1 else deadline - time.monotonic()
            try:
                with urlopen(request, timeout=timeout) as response:
                    if self.stream:
                        data = parse_chat_stream(self._stream_chunks(response, deadline))
                    else:
                        raw_response = response.read().decode("utf-8")
                        data = json.loads(raw_response)
                self._check_cancelled()
                if self.stream and time.monotonic() >= deadline:
                    raise TimeoutError("The model-call time budget expired.")
                break
            except (
                HTTPException, OSError, json.JSONDecodeError, UnicodeDecodeError,
                RecursionError, ChatStreamError,
            ) as exc:
                self._check_cancelled()
                response_state = None
                if isinstance(exc, ChatStreamError):
                    response_state = exc.state
                elif isinstance(exc, UnicodeDecodeError):
                    response_state = "invalid_response_encoding"
                elif isinstance(exc, (json.JSONDecodeError, RecursionError)):
                    response_state = "invalid_response_json"
                error = self._transport_error(
                    exc, model=model,
                    response_text=raw_response if isinstance(exc, (HTTPException, OSError)) else "",
                    attempt_count=attempt,
                    summary=(
                        _RESPONSE_FAILURES.get(
                            exc.state, "response stream was invalid or incomplete",
                        )
                        if isinstance(exc, ChatStreamError) else "request failed"
                    ),
                    request=request, elapsed_seconds=time.monotonic() - started_at,
                    response_state=response_state,
                )
                if (
                    attempt == 2 or not _is_transient_disconnect(exc)
                    or deadline - time.monotonic() <= 1
                ):
                    raise error from exc
                if self._cancellation_event is None:
                    time.sleep(1)
                else:
                    self._cancellation_event.wait(1)
                self._check_cancelled()
                if deadline <= time.monotonic():
                    raise error from exc
        try:
            choice = data["choices"][0]
            message = choice["message"]
            finish_reason = choice.get("finish_reason")
            if not isinstance(message, dict):
                raise TypeError("Chat message must be an object.")
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise self._transport_error(
                exc,
                model=model,
                summary="response did not contain a chat message",
                attempt_count=attempt,
                request=request, elapsed_seconds=time.monotonic() - started_at,
                response_state="invalid_response_shape",
            ) from exc
        response_state = _response_failure_state(message, finish_reason)
        if response_state is not None:
            summary = _RESPONSE_FAILURES[response_state]
            raise self._transport_error(
                ValueError(summary), model=model, summary=summary, attempt_count=attempt,
                request=request, elapsed_seconds=time.monotonic() - started_at,
                response_state=response_state,
                finish_reason=finish_reason if finish_reason in (
                    "length", "content_filter", "tool_calls", "function_call", "stop",
                ) else None,
            )
        reported_model = data.get("model")
        if (
            not isinstance(reported_model, str) or not reported_model
            or len(reported_model) > 200 or any(c.isspace() for c in reported_model)
            or _safe_excerpt(reported_model, request=request, limit=200) != reported_model
        ):
            reported_model = None
        return ModelResponse(
            content=message["content"],
            model=model,
            metadata={
                "provider": self.name,
                "endpoint": self.endpoint,
                "thinking": self.thinking or "inherited",
                "reasoning_effort": self.reasoning_effort or "inherited",
                "attempt_count": attempt,
                "reported_model": reported_model,
                "finish_reason": finish_reason,
            },
        )

    def _check_cancelled(self) -> None:
        if self._cancellation_event is not None and self._cancellation_event.is_set():
            raise OperationCancelled("The task was cancelled.")

    def _stream_chunks(self, response: HTTPResponse, deadline: float) -> Iterator[bytes]:
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The model-call time budget expired.")
            # urllib's HTTPResponse has no public timeout setter. Keep the CPython
            # socket adapter here; the SSE decoder knows nothing about sockets.
            sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if sock is not None:
                sock.settimeout(remaining)
            chunk = response.read1(8192)
            self._check_cancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError("The model-call time budget expired.")
            if not chunk:
                return
            yield chunk

    def _transport_error(
        self,
        exc: BaseException,
        *,
        model: str,
        response_text: str = "",
        summary: str = "request failed",
        attempt_count: int = 1,
        request: Request | None = None,
        elapsed_seconds: float | None = None,
        response_state: str | None = None,
        finish_reason: str | None = None,
    ) -> ProviderTransportError:
        diagnostics = self._failure_diagnostics(
            exc,
            model=model,
            response_text=response_text,
            summary=summary,
            request=request,
        )
        if elapsed_seconds is not None:
            diagnostics["elapsed_seconds"] = round(elapsed_seconds, 3)
        if response_state is not None:
            diagnostics.update(response_state=response_state, finish_reason=finish_reason)
        if request is not None:
            diagnostics["request_byte_count"] = len(request.data or b"")
            try:
                payload = json.loads(request.data or b"{}")
            except (ValueError, TypeError):
                payload = {}
            if isinstance(payload, dict):
                max_tokens = payload.get("max_tokens")
                if type(max_tokens) is int and max_tokens > 0:
                    diagnostics["max_tokens"] = max_tokens
                if type(payload.get("stream")) is bool:
                    diagnostics["stream"] = payload["stream"]
                effort = payload.get("reasoning_effort")
                if isinstance(effort, str) and effort in {"low", "medium", "high", "xhigh", "max"}:
                    diagnostics["reasoning_effort"] = effort
        diagnostics.update(attempt_count=attempt_count, retryable=_is_transient_disconnect(exc))
        return ProviderTransportError(_failure_message(diagnostics), diagnostics)

    def _failure_diagnostics(
        self,
        exc: BaseException,
        *,
        model: str,
        response_text: str = "",
        summary: str = "request failed",
        request: Request | None = None,
    ) -> dict[str, object]:
        host = urlparse(self.endpoint).hostname or "unknown"
        diagnostics: dict[str, object] = {
            "provider": self.name,
            "summary": summary,
            "model": model,
            "host": host,
            "timeout_seconds": self._timeout_seconds,
            "error_type": type(exc).__name__,
        }
        if isinstance(exc, HTTPError):
            diagnostics["status"] = exc.code
            diagnostics["http_reason"] = _safe_excerpt(str(exc.reason), request=request, limit=160)
            diagnostics["response_headers"] = {
                name.casefold(): _safe_excerpt(value, request=request, limit=160)
                for name, value in (exc.headers.items() if exc.headers is not None else ())
                if name.casefold() in {"x-request-id", "x-nvcf-reqid", "retry-after", "server"}
            }
            response_text = _read_http_error_body(exc) or response_text
        if isinstance(exc, IncompleteRead):
            response_text = "" if self.stream else exc.partial.decode("utf-8", errors="replace")
            diagnostics.update(
                {
                    "partial_byte_count": len(exc.partial),
                    "expected_byte_count": exc.expected,
                    "transport_state": (
                        "partial_stream_response" if self.stream else
                        _incomplete_read_state(response_text)
                    ),
                }
            )
        model_response = self.stream or isinstance(exc, IncompleteRead) or any(
            marker in response_text.casefold() for marker in ('"choices"', '"reasoning_content"')
        )
        excerpt = "" if model_response else _safe_excerpt(response_text, request=request)
        if excerpt:
            diagnostics["response_excerpt"] = excerpt
        return diagnostics


def _is_transient_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return False
    cause = exc.reason if isinstance(exc, URLError) else exc
    return isinstance(cause, (
        IncompleteRead, RemoteDisconnected, ConnectionResetError,
        ConnectionAbortedError, BrokenPipeError,
    ))


def _response_failure_state(message: dict[str, object], finish_reason: object) -> str | None:
    """Reject incomplete or non-text completions without exposing their contents."""

    if finish_reason == "length":
        return "output_limit"
    if finish_reason == "content_filter" or message.get("refusal"):
        return "content_filtered"
    if (
        finish_reason in ("tool_calls", "function_call")
        or message.get("tool_calls") or message.get("function_call")
    ):
        return "unsupported_tool_call"
    if finish_reason is not None and finish_reason != "stop":
        return "invalid_finish_reason"
    content = message.get("content")
    if content is None:
        return "missing_final_answer"
    if not isinstance(content, str):
        return "invalid_message_content"
    if not content.strip():
        return "missing_final_answer"
    return None


def _failure_message(diagnostics: dict[str, object]) -> str:
    parts = [
        f"{diagnostics['provider']} {diagnostics['summary']}",
        f"model={diagnostics['model']}",
        f"host={diagnostics['host']}",
        f"timeout={diagnostics['timeout_seconds']}s",
        f"error_type={diagnostics['error_type']}",
    ]
    for key in (
        "attempt_count",
        "status",
        "http_reason",
        "response_headers",
        "elapsed_seconds",
        "request_byte_count",
        "max_tokens",
        "stream",
        "reasoning_effort",
        "partial_byte_count",
        "expected_byte_count",
        "transport_state",
        "response_state",
        "finish_reason",
        "response_excerpt",
    ):
        if key in diagnostics and diagnostics[key] is not None:
            parts.append(f"{key}={diagnostics[key]}")
    return "; ".join(parts) + "."


def _read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read(4096).decode("utf-8", errors="replace")
    except (HTTPException, OSError):
        return ""


def _safe_excerpt(value: str, *, request: Request | None = None, limit: int = 500) -> str:
    if not value:
        return ""
    if request is not None:
        authorization = request.get_header("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ")
            if token:
                value = value.replace(token, "[redacted]")
    redacted = redact_text(value).replace("\n", "\\n").replace("\r", "\\r")
    if len(redacted) <= limit:
        return redacted
    return redacted[:limit].rstrip() + "..."


def _incomplete_read_state(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "empty_partial"
    lowered = stripped.casefold()
    if '"error"' in lowered:
        return "partial_provider_error"
    if '"choices"' in lowered or '"message"' in lowered or '"content"' in lowered:
        return "partial_model_response"
    if stripped.startswith("{") or stripped.startswith("["):
        return "partial_json"
    return "unknown_partial"
