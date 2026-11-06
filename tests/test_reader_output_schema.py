"""Opt-in schema requests never replace strict Reader parsing."""

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from test_openai_response_contract import make_provider
from test_paper_reading import _artifact, _claim_units_fixture

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import parse_paper_reading
from research_radar.analysis.providers import Message
from research_radar.analysis.reader_input import check_reader_input
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.exceptions import AnalysisError, ProviderTransportError


def test_schema_has_one_paper_and_complete_paragraph_and_context_shapes() -> None:
    schema = paper_reading_response_schema()
    papers = schema["properties"]["deep_readings"]
    assert papers["minItems"] == papers["maxItems"] == 1
    assert schema["additionalProperties"] is False
    body = papers["items"]["properties"]
    assert set(body["evaluation_context"]["properties"]) == {
        "data_construction", "available_inputs", "outcome_measurement",
    }
    paragraph = body["reader_explanation"]["properties"]["opening_context"]["items"]
    assert "review" not in paragraph["properties"]


def test_schema_is_opt_in_counted_and_isolated_in_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    payloads = []

    def request(req, **kwargs):
        payloads.append(json.loads(req.data))
        return io.BytesIO(b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}')

    monkeypatch.setattr(transport, "urlopen", request)
    messages = [Message("user", "read this")]
    plain = make_provider()
    schema = paper_reading_response_schema()
    constrained = make_provider(response_schema=schema)
    for provider in [plain, constrained, constrained]:
        cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="reader")
        cached.complete(messages, model="offline-model")
    assert len(payloads) == 2
    assert "response_format" not in payloads[0]
    assert payloads[1]["response_format"]["json_schema"]["schema"] == schema
    constrained_size = check_reader_input(messages, constrained, model="offline-model")
    plain_size = check_reader_input(messages, plain, model="offline-model")
    assert constrained_size["input_utf8_bytes"] > plain_size["input_utf8_bytes"]
    # Mutating the caller's object cannot change an already identified request.
    schema["properties"].clear()
    assert constrained.cache_identity != plain.cache_identity
    assert constrained.response_schema == paper_reading_response_schema()


def test_schema_rejection_does_not_retry_or_silently_drop_constraint(monkeypatch) -> None:
    requests = []

    def request(req, **kwargs):
        requests.append(req)
        raise HTTPError(req.full_url, 422, "Unsupported", {}, io.BytesIO(b"unsupported schema"))

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError):
        make_provider(response_schema=paper_reading_response_schema()).complete(
            [Message("user", "read")], model="offline-model",
        )
    assert len(requests) == 1


def test_saved_failure_shape_still_fails_strict_local_parser() -> None:
    body = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))["deep_readings"]
    appendix = {**body, "title": "Offline paper appendix", "essence": "Same as first pass."}
    with pytest.raises(AnalysisError, match="exactly one"):
        parse_paper_reading(json.dumps({"deep_readings": [body, appendix]}), _artifact())
