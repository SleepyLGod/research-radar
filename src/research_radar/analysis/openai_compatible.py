"""OpenAI-compatible chat completions provider."""

from __future__ import annotations

import json
from http.client import HTTPException
from urllib.request import Request, urlopen

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.exceptions import AnalysisError
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
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPException, OSError, json.JSONDecodeError) as exc:
            raise AnalysisError(f"{self.name} request failed.") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError(
                f"{self.name} response did not contain a chat message."
            ) from exc
        return ModelResponse(
            content=str(content),
            model=model,
            metadata={"provider": self.name, "endpoint": self.endpoint},
        )
