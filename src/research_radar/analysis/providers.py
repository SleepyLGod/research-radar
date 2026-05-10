"""LLM provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Message:
    """A chat-style model message."""

    role: str
    content: str


@dataclass(frozen=True)
class ModelResponse:
    """A normalized model response."""

    content: str
    model: str
    metadata: dict[str, object] = field(default_factory=dict)


class LLMProvider(Protocol):
    """Protocol for model providers."""

    name: str

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return a model response."""


class StaticProvider:
    """Deterministic provider for tests and dry runs."""

    name = "static"

    def __init__(self, content: str = "No model configured.") -> None:
        self._content = content

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Return the configured static response."""

        return ModelResponse(
            content=self._content,
            model=model,
            metadata={"message_count": len(messages)},
        )
