"""Encode historical offline replies as source selections; never repair their evidence."""

import json
import re

from research_radar.analysis.providers import Message
from research_radar.analysis.source_references import build_source_index
from research_radar.evidence.quotes import find_quote
from research_radar.models import Artifact, SourceCandidate, SourceType


def source_response(content: str, messages: list[Message]) -> str:
    """Adapt test doubles only; unmatched evidence and malformed JSON remain unchanged."""
    prompt = messages[-1].content
    if "Evidence is a selection" not in prompt or "\nSOURCE TEXT\n" not in prompt:
        return content
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    marked = prompt.split("\nSOURCE TEXT\n", 1)[1].split("\nEND SOURCE TEXT\n", 1)[0]
    text = re.sub(r"\nsource_id=b[0-9a-f]{16}:\d+\n", "", marked)
    url = prompt.split("\nURL: ", 1)[1].splitlines()[0]
    index = build_source_index(
        Artifact(SourceCandidate("offline", url, SourceType.PAPER, "fixture"), text)
    )

    def visit(value: object) -> object:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in ("evidence", "evidence_index", "experiment_evidence") and isinstance(
                item, list
            ):
                selected = []
                for anchor in item:
                    quote = anchor.get("quote") if isinstance(anchor, dict) else None
                    match = find_quote(quote, text) if isinstance(quote, str) else None
                    if match is not None:
                        for ref in index.references_for_span(match.start, match.end):
                            if ref not in selected:
                                selected.append(ref)
                    else:
                        selected.append(anchor)
                result[key] = selected
            else:
                result[key] = visit(item)
        return result

    result = visit(payload)
    if isinstance(result, dict):
        body = result.get("deep_readings")
        if isinstance(body, list) and len(body) == 1:
            body = body[0]
        if isinstance(body, dict) and "method_flow" not in body:
            # Old doubles with no method proposal still propose no operations.
            body["method_flow"] = {"operations": [], "links": [], "gaps": []}
        if isinstance(body, dict) and "evaluation_context" not in body:
            body["evaluation_context"] = {key: [] for key in (
                "data_construction", "available_inputs", "outcome_measurement")}
    return json.dumps(result, ensure_ascii=False)
