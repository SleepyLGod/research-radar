"""Declared context planning for complete, never-truncated paper input."""

from __future__ import annotations

import json
from dataclasses import dataclass

from research_radar.analysis.providers import LLMProvider, Message
from research_radar.exceptions import AnalysisError


@dataclass(frozen=True)
class ReaderContextBudget:
    """Operator-declared capacity and reserves for one exact model identifier."""

    context_window_tokens: int
    output_reserve_tokens: int
    overhead_reserve_tokens: int
    soft_limit: bool = False

    def __post_init__(self) -> None:
        values = (
            self.context_window_tokens,
            self.output_reserve_tokens,
            self.overhead_reserve_tokens,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Reader context limits must be positive integers.")
        if type(self.soft_limit) is not bool:
            raise ValueError("Reader soft_limit must be a boolean.")
        if self.output_reserve_tokens + self.overhead_reserve_tokens >= self.context_window_tokens:
            raise ValueError("Reader context reserves must leave room for input.")


class ReaderInputError(AnalysisError):
    """A complete request cannot safely proceed under the declared input policy."""

    def __init__(self, code: str, message: str, audit: dict[str, object]) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.audit = {**audit, "status": "blocked", "code": code}
        self.reader_attempts: list[dict[str, object]] = []


def check_reader_input(
    messages: list[Message],
    provider: LLMProvider,
    *,
    model: str,
    response_schema: dict[str, object] | None = None,
) -> dict[str, object]:
    """Check every actual request, including repairs, before reaching the cache/provider.

    UTF-8 bytes are a deliberately conservative planning estimate, NOT a tokenizer
    measurement or proof that a remote service will accept the context. Provider-side
    instructions, framing and reasoning need the separately declared reserves.
    """

    rendered = "\n\n".join(f"{m.role.upper()}:\n{m.content}" for m in messages)
    input_bytes = len(rendered.encode("utf-8"))
    schema = (response_schema if response_schema is not None
              else getattr(provider, "response_schema", None))
    if schema is not None:
        input_bytes += len(json.dumps({
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "paper_reading", "strict": True, "schema": schema,
            }},
        }, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    elif getattr(provider, "json_output", False):
        input_bytes += len(json.dumps({"response_format": {"type": "json_object"}}).encode())
    audit: dict[str, object] = {
        "model": model,
        "input_utf8_bytes": input_bytes,
        "input_tokens_estimate": input_bytes,
        "measurement": "utf8_bytes_conservative_estimate",
    }
    budgets = getattr(provider, "reader_contexts", {})
    budget = budgets.get(model)
    if not isinstance(budget, ReaderContextBudget):
        raise ReaderInputError(
            "reader_context_unknown",
            "Configure reader_contexts for this exact model; this request was not sent.",
            audit,
        )
    maximum = getattr(provider, "max_tokens", None)
    if maximum is not None and maximum > budget.output_reserve_tokens:
        raise ReaderInputError(
            "reader_output_reserve_insufficient",
            "Output reserve is smaller than configured max_tokens.",
            audit,
        )
    total = input_bytes + budget.output_reserve_tokens + budget.overhead_reserve_tokens
    audit.update(
        {
            "context_window_tokens": budget.context_window_tokens,
            "output_reserve_tokens": budget.output_reserve_tokens,
            "overhead_reserve_tokens": budget.overhead_reserve_tokens,
            "planned_total_tokens": total,
        }
    )
    if total > budget.context_window_tokens:
        if budget.soft_limit:
            return {**audit, "status": "exceeds_estimate", "soft_limit": True}
        raise ReaderInputError(
            "reader_context_exceeded",
            f"Complete request estimate {total} exceeds declared capacity "
            f"{budget.context_window_tokens}; this request was not sent.",
            audit,
        )
    return {**audit, "status": "fits_estimate"}
