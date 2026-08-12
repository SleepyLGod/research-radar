"""OpenAI-compatible chat completions provider."""

from __future__ import annotations

import json
from http.client import HTTPException, IncompleteRead
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import ProviderTransportError
from research_radar.security.redaction import redact_text
from research_radar.security.secrets import SecretManager


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
    ) -> None:
        self.name = name
        self.endpoint = endpoint
        self._api_key_secret = api_key_secret
        self._secrets = secrets
        self._timeout_seconds = timeout_seconds
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        identity_parts = []
        if thinking is not None:
            identity_parts.append(f"thinking={thinking}")
        if reasoning_effort is not None:
            identity_parts.append(f"reasoning_effort={reasoning_effort}")
        self.cache_identity = ";".join(identity_parts)

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Call a chat completions endpoint and return normalized content."""

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
        raw_response = ""
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_response = response.read().decode("utf-8", errors="replace")
                data = json.loads(raw_response)
        except (HTTPException, OSError, json.JSONDecodeError) as exc:
            raise self._transport_error(exc, model=model, response_text=raw_response) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise self._transport_error(
                exc,
                model=model,
                response_text=raw_response,
                summary="response did not contain a chat message",
            ) from exc
        return ModelResponse(
            content=str(content),
            model=model,
            metadata={
                "provider": self.name,
                "endpoint": self.endpoint,
                "thinking": self.thinking or "inherited",
                "reasoning_effort": self.reasoning_effort or "inherited",
            },
        )

    def _transport_error(
        self,
        exc: BaseException,
        *,
        model: str,
        response_text: str = "",
        summary: str = "request failed",
    ) -> ProviderTransportError:
        diagnostics = self._failure_diagnostics(
            exc,
            model=model,
            response_text=response_text,
            summary=summary,
        )
        return ProviderTransportError(_failure_message(diagnostics), diagnostics)

    def _failure_diagnostics(
        self,
        exc: BaseException,
        *,
        model: str,
        response_text: str = "",
        summary: str = "request failed",
    ) -> dict[str, object]:
        host = urlparse(self.endpoint).netloc or self.endpoint
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
            response_text = _read_http_error_body(exc) or response_text
        if isinstance(exc, IncompleteRead):
            response_text = exc.partial.decode("utf-8", errors="replace")
            diagnostics.update(
                {
                    "partial_byte_count": len(exc.partial),
                    "expected_byte_count": exc.expected,
                    "transport_state": _incomplete_read_state(response_text),
                }
            )
        excerpt = _safe_excerpt(response_text)
        if excerpt:
            diagnostics["response_excerpt"] = excerpt
        return diagnostics


def _failure_message(diagnostics: dict[str, object]) -> str:
    parts = [
        f"{diagnostics['provider']} {diagnostics['summary']}",
        f"model={diagnostics['model']}",
        f"host={diagnostics['host']}",
        f"timeout={diagnostics['timeout_seconds']}s",
        f"error_type={diagnostics['error_type']}",
    ]
    for key in (
        "status",
        "partial_byte_count",
        "expected_byte_count",
        "transport_state",
        "response_excerpt",
    ):
        if key in diagnostics and diagnostics[key] is not None:
            parts.append(f"{key}={diagnostics[key]}")
    return "; ".join(parts) + "."


def _read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _safe_excerpt(value: str, *, limit: int = 500) -> str:
    if not value:
        return ""
    redacted = redact_text(value).replace("\n", "\\n")
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
