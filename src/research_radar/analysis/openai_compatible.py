"""OpenAI-compatible chat completions provider."""

from __future__ import annotations

import json
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import AnalysisError
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
    ) -> None:
        self.name = name
        self.endpoint = endpoint
        self._api_key_secret = api_key_secret
        self._secrets = secrets
        self._timeout_seconds = timeout_seconds

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Call a chat completions endpoint and return normalized content."""

        payload = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": 0.2,
        }
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
            raise AnalysisError(
                self._failure_message(exc, model=model, response_text=raw_response)
            ) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError(
                self._failure_message(
                    exc,
                    model=model,
                    response_text=raw_response,
                    summary="response did not contain a chat message",
                )
            ) from exc
        return ModelResponse(
            content=str(content),
            model=model,
            metadata={"provider": self.name, "endpoint": self.endpoint},
        )

    def _failure_message(
        self,
        exc: BaseException,
        *,
        model: str,
        response_text: str = "",
        summary: str = "request failed",
    ) -> str:
        host = urlparse(self.endpoint).netloc or self.endpoint
        parts = [
            f"{self.name} {summary}",
            f"model={model}",
            f"host={host}",
            f"timeout={self._timeout_seconds}s",
            f"error_type={type(exc).__name__}",
        ]
        if isinstance(exc, HTTPError):
            parts.append(f"status={exc.code}")
            response_text = _read_http_error_body(exc) or response_text
        excerpt = _safe_excerpt(response_text)
        if excerpt:
            parts.append(f"response_excerpt={excerpt}")
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
