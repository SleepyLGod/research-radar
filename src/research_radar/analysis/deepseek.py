"""DeepSeek OpenAI-compatible provider."""

from __future__ import annotations

from research_radar.analysis.openai_compatible import OpenAICompatibleProvider
from research_radar.security.secrets import SecretManager


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek chat completions provider."""

    endpoint = "https://api.deepseek.com/chat/completions"

    def __init__(self, secrets: SecretManager) -> None:
        super().__init__(
            name="deepseek",
            endpoint=self.endpoint,
            api_key_secret="deepseek.api_key",
            secrets=secrets,
        )
