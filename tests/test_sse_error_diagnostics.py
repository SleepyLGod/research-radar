"""Bounded provider-reported SSE errors, without inference from English wording."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from test_openai_streaming import DONE, Response, event, frame, provider

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.openai_stream import ChatStreamError, parse_chat_stream
from research_radar.analysis.providers import Message
from research_radar.exceptions import ProviderTransportError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def fail_stream(
    monkeypatch: pytest.MonkeyPatch, error: object, *, schema: bool = False,
) -> ProviderTransportError:
    """Replace only HTTP IO; keep the shared decoder and diagnostic path real."""
    response = io.BytesIO(frame({"error": error}) + DONE)
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: response)
    instance = provider(stream=True, response_schema={"type": "object"} if schema else None)
    with pytest.raises(ProviderTransportError) as failed:
        instance.complete([], model="alias")
    assert response.closed
    return failed.value


def test_schema_error_preserves_only_safe_structured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = fail_stream(
        monkeypatch,
        {
            "code": "invalid_json_schema",
            "type": "invalid_request_error",
            "param": "response_format.json_schema.schema",
            "message": "Schema requires additionalProperties.",
            "reasoning_content": "PRIVATE REASONING",
            "content": "PRIVATE ANSWER",
            "request": {"Authorization": "PRIVATE HEADER"},
        },
        schema=True,
    )

    assert failed.diagnostics["provider_error_kind"] == "schema_rejected"
    assert failed.diagnostics["provider_error"] == {
        "code": "invalid_json_schema",
        "type": "invalid_request_error",
        "param": "response_format.json_schema.schema",
        "message": "Schema requires additionalProperties.",
    }
    assert "PRIVATE" not in str(failed) + str(failed.diagnostics)
    assert "Schema requires additionalProperties." in str(failed)


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("invalid_api_key", "authentication"),
        ("rate_limit_exceeded", "rate_limit"),
        ("insufficient_quota", "quota"),
        ("server_error", "service"),
        ("unrecognized_vendor_code", "unclassified"),
        (400, "unclassified"),
    ],
)
def test_known_codes_classify_without_interpreting_error_prose(
    monkeypatch: pytest.MonkeyPatch,
    code: object,
    kind: str,
) -> None:
    failed = fail_stream(
        monkeypatch,
        {
            "code": code,
            "type": "api_error",
            "param": "response_format",
            "message": "invalid JSON schema; authentication; quota; timeout",
        },
        schema=True,
    )
    assert failed.diagnostics["provider_error_kind"] == kind
    assert failed.diagnostics["provider_error"]["code"] == code
    assert failed.diagnostics["response_state"] == "stream_provider_error"
    assert failed.diagnostics["retryable"] is False


def test_schema_wording_and_param_are_not_a_machine_schema_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = fail_stream(
        monkeypatch,
        {
            "type": "invalid_request_error",
            "param": "response_format.json_schema.schema",
            "message": "The JSON schema was rejected.",
        },
        schema=True,
    )
    assert failed.diagnostics["provider_error_kind"] == "unclassified"


def test_schema_code_without_a_schema_request_does_not_claim_this_constraint_was_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = fail_stream(monkeypatch, {"code": "invalid_json_schema", "message": "Bad schema"})
    assert failed.diagnostics["provider_error_kind"] == "unclassified"


@pytest.mark.parametrize(
    "error", [None, [], 123, {"code": True, "type": [], "param": {}, "message": []}]
)
def test_invalid_field_types_are_not_stringified_into_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    error: object,
) -> None:
    failed = fail_stream(monkeypatch, error)
    assert failed.diagnostics["provider_error"] == {}
    assert failed.diagnostics["provider_error_kind"] == "unclassified"


def test_plain_string_error_keeps_bounded_explanation_but_no_inferred_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = fail_stream(monkeypatch, "Service could not complete the request.")
    assert failed.diagnostics["provider_error"] == {
        "message": "Service could not complete the request."
    }
    assert failed.diagnostics["provider_error_kind"] == "unclassified"


def test_key_redaction_happens_before_message_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = fail_stream(
        monkeypatch,
        {
            "message": "x" * 490 + "offline-only-key" + " extra" * 500,
            "code": "offline-only-key",
            "type": "bad_request",
            "param": "offline-only-key",
        },
    )
    diagnostic = str(failed) + json.dumps(failed.diagnostics)
    assert "offline-only-key" not in diagnostic
    assert "offline-on" not in diagnostic
    assert len(failed.diagnostics["provider_error"]["message"]) <= 500


@pytest.mark.parametrize("field", ["code", "type", "param"])
def test_oversized_machine_fields_are_omitted_not_truncated_into_valid_codes(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    failed = fail_stream(monkeypatch, {field: "invalid_json_schema" + " " * 1000}, schema=True)
    assert field not in failed.diagnostics["provider_error"]
    assert failed.diagnostics["provider_error_kind"] == "unclassified"


@pytest.mark.parametrize("key", ["reasoning_content", "choices", "messages", "content"])
def test_serialized_model_or_request_content_is_not_a_service_explanation(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    failed = fail_stream(
        monkeypatch,
        {
            "code": "server_error",
            "message": json.dumps({key: "PRIVATE PAYLOAD"}),
        },
    )
    assert "message" not in failed.diagnostics["provider_error"]
    assert "PRIVATE" not in str(failed) + str(failed.diagnostics)


def test_direct_decoder_error_is_already_redacted_and_does_not_retain_other_fields() -> None:
    raw = frame(
        {"error": {"message": "api_key=sk-" + "x" * 30, "reasoning_content": "PRIVATE REASONING"}}
    )
    with pytest.raises(ChatStreamError) as failed:
        parse_chat_stream([raw])
    assert "sk-" + "x" * 30 not in json.dumps(failed.value.provider_error)
    assert "PRIVATE" not in str(failed.value.provider_error)
    assert str(failed.value) == "stream_provider_error"


def test_failure_after_partial_content_never_caches_or_repairs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requests = []
    wire = (
        event(extra={"reasoning_content": "PRIVATE REASONING"})
        + event("PRIVATE ANSWER")
        + frame({"error": {"code": "server_error", "message": "Upstream failed."}})
    )
    response = Response([wire[i : i + 1] for i in range(len(wire))])

    def exchange(*_a: object, **_k: object) -> Response:
        requests.append(1)
        return response

    monkeypatch.setattr(transport, "urlopen", exchange)
    cached = CachedLLMProvider(provider(stream=True), cache_dir=tmp_path, task_name="reader")
    with pytest.raises(ProviderTransportError) as failed:
        cached.complete([Message("user", "PRIVATE PROMPT")], model="alias")
    assert requests == [1]
    assert not list(tmp_path.rglob("*.json"))
    assert "PRIVATE" not in str(failed.value) + str(failed.value.diagnostics)
    assert failed.value.diagnostics["provider_error"]["message"] == "Upstream failed."


@pytest.mark.parametrize("chunk_size", [1, 17, 4096])
def test_error_diagnostics_survive_split_utf8_with_the_request_key_removed(
    monkeypatch: pytest.MonkeyPatch,
    chunk_size: int,
) -> None:
    key = "nvapi-" + "offline" * 7
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("offline.key", key)
    instance = transport.OpenAICompatibleProvider(
        name="offline",
        endpoint="https://example.invalid/chat/completions",
        secrets=manager,
        api_key_secret="offline.key",
        stream=True,
    )
    wire = frame({"error": {"message": f"参数错误；凭据 {key}；请核对请求。"}})
    response = Response([wire[i : i + chunk_size] for i in range(0, len(wire), chunk_size)])
    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: response)
    with pytest.raises(ProviderTransportError) as failure:
        instance.complete([], model="offline")
    details = failure.value.diagnostics["provider_error"]
    assert "参数错误" in details["message"]
    assert key not in str(failure.value) + str(details)
    assert response.closed


def test_nullable_fields_are_kept_as_unknown_not_literal_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = fail_stream(monkeypatch, {"code": None, "type": None, "param": None, "message": None})
    assert failed.diagnostics["provider_error"] == {"code": None, "type": None, "param": None}
    assert failed.diagnostics["provider_error_kind"] == "unclassified"


@pytest.mark.parametrize("field", ["code", "type", "param"])
def test_machine_fields_do_not_copy_free_prose_or_terminal_controls(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    failed = fail_stream(monkeypatch, {field: "not a machine field\x1b[31m"})
    assert field not in failed.diagnostics["provider_error"]


def test_message_has_no_terminal_escape_and_preserves_useful_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = fail_stream(monkeypatch, {"message": "\x1b[31mSchema invalid\x00"})
    assert "Schema invalid" in failed.diagnostics["provider_error"]["message"]
    assert "\x1b" not in failed.diagnostics["provider_error"]["message"]
    assert "\x00" not in failed.diagnostics["provider_error"]["message"]


def test_error_message_does_not_echo_the_authenticated_request_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "https://endpoint_user:endpoint_password@example.invalid/chat/completions"
    monkeypatch.setattr(
        transport,
        "urlopen",
        lambda *_a, **_k: io.BytesIO(
            frame(
                {
                    "error": {
                        "message": f"Request to {endpoint} failed.",
                        "code": "server_error",
                    }
                }
            )
        ),
    )
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("offline.key", "offline-only-key")
    instance = transport.OpenAICompatibleProvider(
        name="offline",
        endpoint=endpoint,
        secrets=manager,
        api_key_secret="offline.key",
        stream=True,
    )
    with pytest.raises(ProviderTransportError) as failure:
        instance.complete([], model="alias")
    serialized = str(failure.value) + json.dumps(failure.value.diagnostics)
    assert "endpoint_user" not in serialized
    assert "endpoint_password" not in serialized
    assert failure.value.diagnostics["host"] == "example.invalid"


def test_production_paper_failure_persists_redacted_error_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from research_radar.config import parse_config
    from research_radar.models import Artifact
    from research_radar.pipeline import paper
    from research_radar.storage.files import read_json

    monkeypatch.setattr(
        paper, "ingest_source", lambda source, _: Artifact(source, "Saved paper text")
    )
    monkeypatch.setattr(
        transport,
        "urlopen",
        lambda *_a, **_k: io.BytesIO(
            frame(
                {
                    "error": {
                        "code": "invalid_json_schema",
                        "param": "response_format",
                        "message": "Rejected schema; offline-only-key",
                        "reasoning_content": "PRIVATE REASONING",
                    }
                }
            )
        ),
    )
    with pytest.raises(ProviderTransportError):
        paper.run_paper(
            tmp_path,
            parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]}),
            "memory",
            "https://example.invalid/paper",
            provider(stream=True, response_schema={"type": "object"}),
            model="alias",
        )
    run = next((tmp_path / "runs").iterdir())
    failure = read_json(run / "run_error.json")
    assert failure["stage"] == "reader"
    assert failure["transport"]["provider_error_kind"] == "schema_rejected"
    assert failure["transport"]["provider_error"]["param"] == "response_format"
    assert all(
        "offline-only-key" not in p.read_text() and "PRIVATE REASONING" not in p.read_text()
        for p in run.iterdir()
        if p.is_file()
    )
