"""Synthetic discovery PDF and model responses, not pre-rendered report artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.discovery.base import DiscoveryContext
from research_radar.models import SourceCandidate, SourceType

TITLE = "Offline Grounded Agent Memory Benchmark"
SOURCE_URL = "https://example.com/offline-memory-paper"


def create_paper(path: Path) -> None:
    """Create original synthetic PDF input with actual text and a crop-safe figure."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    sections = [
        ("Abstract", "Agent memory systems require grounded retrieval."),
        ("Introduction", "Memory benchmarks reward unsupported answers."),
        ("Method", "Require cited memory evidence before crediting answers."),
        (
            "Related work",
            "The paper studies grounded answerability rather than answer match alone.",
        ),
        ("Evaluation", "The evaluation runs on a fixture benchmark."),
        ("Limitations", "The system only evaluates benchmark-style tasks."),
        ("Conclusion", "The useful contribution is the evaluation lens."),
    ]
    for heading, sentence in sections:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        lines = [heading, sentence]
        lines += [
            "Accuracy is the main fixture metric.",
            "The fixture result shows grounded answers score higher.",
        ]
        lines += [
            "Synthetic benchmark context: cited memory evidence supports grounded answers."
        ] * 22
        content = "BT /F1 10 Tf 50 750 Td 15 TL\n"
        content += "\n".join(f"({line}) Tj T*" for line in lines) + "\nET\n"
        if heading == "Method":
            # Large white margins keep the real production crop policy satisfied.
            content += "q 0.15 0.55 0.3 rg 160 190 100 60 re f\n"
            content += "0.7 0.2 0.2 rg 350 190 100 60 re f Q\n"
            content += "BT /F1 10 Tf 60 140 Td "
            content += (
                "(Figure 1: Cited memory evidence architecture for crediting answers.) Tj ET\n"
            )
        stream = DecodedStreamObject()
        stream.set_data(content.encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle)


class FrozenDiscovery:
    """Serve one synthetic source through production discovery orchestration."""

    name = "offline_frozen"

    def __init__(self, root: Path) -> None:
        self.root = root

    def discover(self, context: DiscoveryContext) -> list[SourceCandidate]:
        """Return a public citation plus local acquisition URI without any network."""
        path = self.root / "offline-inputs" / "paper.pdf"
        if not path.exists():
            create_paper(path)
        return [
            SourceCandidate(
                title=TITLE,
                url=SOURCE_URL,
                source_type=SourceType.PAPER,
                source_name=self.name,
                score=1.0,
                summary=(
                    "An agent memory benchmark evaluates grounded retrieval with cited evidence."
                ),
                metadata={"pdf_url": path.as_uri(), "license": "CC0"},
            )
        ]


class FrozenModel:
    """Return fixed model IO while keeping parsing and evidence policy real."""

    name = "offline_frozen"

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        """Reject unknown tasks rather than falling back to a real provider."""
        if not messages:
            raise AssertionError("Expected a production prompt")
        if model == "fixture-reader":
            content = Path(__file__).with_name("reader.json").read_text(encoding="utf-8")
        elif model == "fixture-verifier":
            content = json.dumps(
                {
                    "decisions": [
                        {
                            "claim_index": index,
                            "status": "supported",
                            "risk": "low",
                            "reason": "Synthetic fixture quote is present in the local paper.",
                        }
                        for index in range(1, 7)
                    ]
                }
            )
        else:
            raise AssertionError(f"Unexpected offline model: {model}")
        return ModelResponse(content=content, model=model)
