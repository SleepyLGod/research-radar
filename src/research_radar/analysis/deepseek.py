"""DeepSeek OpenAI-compatible provider."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from research_radar.analysis.providers import LLMProvider, Message, ModelResponse
from research_radar.exceptions import AnalysisError
from research_radar.security.secrets import SecretManager


class DeepSeekProvider(LLMProvider):
    """DeepSeek chat completions provider."""

    name = "deepseek"
    endpoint = "https://api.deepseek.com/chat/completions"

    def __init__(self, secrets: SecretManager) -> None:
        self._secrets = secrets

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Call DeepSeek chat completions."""

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
                "Authorization": f"Bearer {self._secrets.get_deepseek_api_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise AnalysisError("DeepSeek request failed.") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError("DeepSeek response did not contain a chat message.") from exc
        return ModelResponse(content=str(content), model=model, metadata={"provider": self.name})
