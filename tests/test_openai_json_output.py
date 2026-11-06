"""Supported JSON-object mode is explicit, strict and isolated from plain-text caches."""

import io
import json
from pathlib import Path

import pytest
from test_openai_response_contract import make_provider

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.providers import Message
from research_radar.exceptions import ProviderTransportError


@pytest.mark.parametrize("stream", [False, True])
def test_json_mode_is_opt_in_and_has_a_distinct_cache(
    stream: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def request(req: object, **kwargs: object) -> io.BytesIO:
        requests.append(json.loads(req.data))
        if stream:
            return io.BytesIO(b'data: {"choices":[{"index":0,"delta":{"content":"{}"},'
                              b'"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"},
                                                  "finish_reason": "stop"}]}).encode())

    monkeypatch.setattr(transport, "urlopen", request)
    for enabled in (False, True, True):
        CachedLLMProvider(make_provider(json_output=enabled, stream=stream), cache_dir=tmp_path,
            task_name="reader").complete([Message("user", "Return JSON")], model="offline")
    assert len(requests) == 2
    assert "response_format" not in requests[0]
    assert requests[1]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("content", ["broken JSON", '[]', '{"unclosed":1', 'null', '"text"', '   '])
def test_bad_json_mode_response_is_not_retried_or_cached(
    stream: bool, content: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def request(req: object, **kwargs: object) -> io.BytesIO:
        calls.append(req)
        if stream:
            frame = json.dumps({"choices": [{"index": 0, "delta": {"content": content},
                                              "finish_reason": "stop"}]}).encode()
            return io.BytesIO(b'data: ' + frame + b'\n\ndata: [DONE]\n\n')
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content},
                                                  "finish_reason": "stop"}]}).encode())

    monkeypatch.setattr(transport, "urlopen", request)
    with pytest.raises(ProviderTransportError) as caught:
        CachedLLMProvider(make_provider(json_output=True, stream=stream), cache_dir=tmp_path,
            task_name="reader").complete([Message("user", "Return JSON")], model="offline")
    assert caught.value.diagnostics["response_state"] == (
        "invalid_json_output" if content.strip() else "missing_final_answer")
    assert len(calls) == 1
    assert not list(tmp_path.glob("**/*.json"))
    if content.strip():
        assert content not in str(caught.value)


@pytest.mark.parametrize("enabled", [None, 0, 1, "true"])
def test_invalid_json_mode_is_rejected(enabled: object) -> None:
    with pytest.raises(ValueError):
        make_provider(json_output=enabled)


def test_json_object_and_specific_schema_are_not_silently_combined() -> None:
    with pytest.raises(ValueError):
        make_provider(json_output=True, response_schema={"type": "object"})
