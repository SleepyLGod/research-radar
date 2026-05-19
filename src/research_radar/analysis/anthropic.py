"""Anthropic Messages API provider."""

from __future__ import annotations

import json
from http.client import HTTPException
from urllib.request import Request, urlopen

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import AnalysisError
from research_radar.security.secrets import SecretManager


class AnthropicMessagesProvider:
    """Provider for Anthropic's Messages API."""

    endpoint = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        *,
        name: str,
        api_key_secret: str,
        secrets: SecretManager,
        timeout_seconds: int = 120,
    ) -> None:
        self.name = name
        self._api_key_secret = api_key_secret
        self._secrets = secrets
        self._timeout_seconds = timeout_seconds

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Call Anthropic Messages and return normalized content."""

        payload = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": _anthropic_messages(messages),
        }
        system_text = _system_text(messages)
        if system_text:
            payload["system"] = system_text
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self._secrets.get_named_secret(self._api_key_secret),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPException, OSError, json.JSONDecodeError) as exc:
            raise AnalysisError(f"{self.name} request failed.") from exc
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError(
                f"{self.name} response did not contain a text message."
            ) from exc
        return ModelResponse(
            content=str(text),
            model=model,
            metadata={"provider": self.name, "endpoint": self.endpoint},
        )


def _system_text(messages: list[Message]) -> str:
    return "\n\n".join(message.content for message in messages if message.role == "system")


def _anthropic_messages(messages: list[Message]) -> list[dict[str, str]]:
    converted = [
        {
            "role": message.role if message.role in {"user", "assistant"} else "user",
            "content": message.content,
        }
        for message in messages
        if message.role != "system"
    ]
    if converted:
        return converted
    return [{"role": "user", "content": ""}]
