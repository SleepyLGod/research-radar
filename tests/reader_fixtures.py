"""Explicit synthetic context limits and source selections for offline model doubles."""

from dataclasses import replace

from fixtures.offline_frozen.source_reply import source_response as source_response

from research_radar.analysis.providers import Message, ModelResponse, StaticProvider
from research_radar.analysis.reader_input import ReaderContextBudget
from research_radar.analysis.source_references import build_source_index
from research_radar.models import Artifact, EvidenceAnchor

OFFLINE_READER_CONTEXTS = {
    model: ReaderContextBudget(1_000_000, 32_768, 4_096)
    for model in (
        "fake-reader",
        "fake-verifier",
        "fake-reviewer",
        "fake-model",
        "offline",
        "offline-model",
        "offline-reader",
        "offline-verifier",
        "fixture-reader",
        "fixture-verifier",
        "deepseek-flash",
        "alias",
        "gpt-6-luna",
        "fake-analyst",
        "gpt-test",
        "codex_or_openai_high_reasoning",
    )
}


class OfflineStaticProvider(StaticProvider):
    """Fixture answer with declared fake capacity; never a production capacity claim."""

    reader_contexts = OFFLINE_READER_CONTEXTS

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        response = super().complete(messages, model=model)
        return replace(response, content=source_response(response.content, messages))


def legacy_saved_anchors(records: list[dict]) -> list[EvidenceAnchor]:
    """Keep saved quotes and human locations, not full-paper IDs invalid on excerpt fixtures."""
    anchors = []
    for record in records:
        anchor = EvidenceAnchor(**record)
        location = anchor.location.partition("; source block ")[0] if anchor.location else None
        anchors.append(replace(anchor, location=location))
    return anchors


def current_source_anchors(artifact: Artifact, records: list[dict]) -> list[EvidenceAnchor]:
    """Readdress only unique literal quotes that equal complete current source blocks."""
    index = build_source_index(artifact)
    anchors = []
    for record in records:
        anchor = EvidenceAnchor(**record)
        quote = anchor.quote.strip()
        start = artifact.text.find(quote)
        if (anchor.source_url != artifact.source.url or not quote or start < 0
                or artifact.text.find(quote, start + 1) >= 0):
            raise ValueError("Fixture quote must have one exact occurrence in its source.")
        reference = index.reference_for_span(start, start + len(quote))
        selected = index.resolve(reference)
        if selected["quote"].strip() != quote:
            raise ValueError("Fixture quote differs from the complete current source block.")
        anchors.append(replace(anchor, location=selected["location"]))
    return anchors
