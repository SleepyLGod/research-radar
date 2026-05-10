"""Secret storage abstractions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from research_radar.exceptions import SecretError


class SecretBackend(Protocol):
    """Protocol implemented by secret storage backends."""

    def set_secret(self, name: str, value: str) -> None:
        """Store a secret value."""

    def get_secret(self, name: str) -> str:
        """Return a secret value."""


@dataclass(frozen=True)
class KeychainSecretBackend:
    """Secret backend backed by macOS Keychain through keyring."""

    service_name: str = "ResearchRadar"

    def set_secret(self, name: str, value: str) -> None:
        """Store a secret in Keychain."""

        if not value:
            raise SecretError(f"Refusing to store empty secret: {name}")
        try:
            import keyring
        except ImportError as exc:
            raise SecretError("Install keyring to use the Keychain secret backend.") from exc
        keyring.set_password(self.service_name, name, value)

    def get_secret(self, name: str) -> str:
        """Read a secret from Keychain."""

        try:
            import keyring
        except ImportError as exc:
            raise SecretError("Install keyring to use the Keychain secret backend.") from exc
        value = keyring.get_password(self.service_name, name)
        if value is None:
            raise SecretError(f"Secret not found: {name}")
        return value


class InMemorySecretBackend:
    """In-memory backend for tests."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set_secret(self, name: str, value: str) -> None:
        """Store a test secret in memory."""

        if not value:
            raise SecretError(f"Refusing to store empty secret: {name}")
        self._values[name] = value

    def get_secret(self, name: str) -> str:
        """Read a test secret from memory."""

        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretError(f"Secret not found: {name}") from exc


class EnvSecretBackend:
    """Secret backend backed by current process environment variables."""

    _names = {
        "deepseek.api_key": "DEEPSEEK_API_KEY",
        "openai.api_key": "OPENAI_API_KEY",
        "wechat.app_id": "WECHAT_APP_ID",
        "wechat.app_secret": "WECHAT_APP_SECRET",
        "github.token": "GITHUB_TOKEN",
        "semantic_scholar.api_key": "SEMANTIC_SCHOLAR_API_KEY",
    }

    def set_secret(self, name: str, value: str) -> None:
        """Store a secret in the current process environment."""

        env_name = self._env_name(name)
        if not value:
            raise SecretError(f"Refusing to store empty secret: {name}")
        os.environ[env_name] = value

    def get_secret(self, name: str) -> str:
        """Read a secret from the current process environment."""

        env_name = self._env_name(name)
        value = os.environ.get(env_name)
        if value is None or not value.strip():
            raise SecretError(f"Secret not found in environment: {env_name}")
        return value

    def _env_name(self, name: str) -> str:
        try:
            return self._names[name]
        except KeyError as exc:
            raise SecretError(f"Unknown environment-backed secret: {name}") from exc


@dataclass(frozen=True)
class SecretManager:
    """Typed secret facade used by provider clients."""

    backend: SecretBackend

    def set_deepseek_api_key(self, value: str) -> None:
        """Store the DeepSeek API key."""

        self.backend.set_secret("deepseek.api_key", value)

    def get_deepseek_api_key(self) -> str:
        """Return the DeepSeek API key."""

        return self.backend.get_secret("deepseek.api_key")

    def set_openai_api_key(self, value: str) -> None:
        """Store the OpenAI API key."""

        self.backend.set_secret("openai.api_key", value)

    def get_openai_api_key(self) -> str:
        """Return the OpenAI API key."""

        return self.backend.get_secret("openai.api_key")

    def set_wechat_credentials(self, app_id: str, app_secret: str) -> None:
        """Store WeChat Official Account credentials."""

        self.backend.set_secret("wechat.app_id", app_id)
        self.backend.set_secret("wechat.app_secret", app_secret)

    def get_wechat_app_id(self) -> str:
        """Return the WeChat app id."""

        return self.backend.get_secret("wechat.app_id")

    def get_wechat_app_secret(self) -> str:
        """Return the WeChat app secret."""

        return self.backend.get_secret("wechat.app_secret")

    def set_github_token(self, value: str) -> None:
        """Store the GitHub API token."""

        self.backend.set_secret("github.token", value)

    def get_github_token(self) -> str:
        """Return the GitHub API token."""

        return self.backend.get_secret("github.token")

    def set_semantic_scholar_api_key(self, value: str) -> None:
        """Store the Semantic Scholar API key."""

        self.backend.set_secret("semantic_scholar.api_key", value)

    def get_semantic_scholar_api_key(self) -> str:
        """Return the Semantic Scholar API key."""

        return self.backend.get_secret("semantic_scholar.api_key")
