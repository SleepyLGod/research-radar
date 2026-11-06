"""Amendment provenance and failures stay bound to their actual shared workflow route."""

from __future__ import annotations

import copy
import json
import re
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from method_contract_controls import control
from reader_fixtures import OFFLINE_READER_CONTEXTS
from test_fact_revision import Reviewer, Reviser
from test_method_contract_pipeline import Reading, Writing

from research_radar.analysis.anchor_repair import apply_anchor_resolution
from research_radar.analysis.fact_revision import revise_publication_facts
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import parse_paper_reading, validate_paper_reading
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import (
    ModelReviewResult,
    fact_is_reviewed,
    review_publication_facts,
)
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact
from research_radar.pipeline import daily, paper
from research_radar.security.secrets import KeychainSecretBackend


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No network or credentials in amendment-context regressions")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


class PlainReviewer:
    """Declared decisions only; the tests inspect input, not a model's semantic ability."""

    name = "offline-plain"
    reader_contexts = OFFLINE_READER_CONTEXTS
    supports_response_schema = False

    def __init__(self, status: str = "supported", *, initial: bool = True) -> None:
        self.status, self.initial = status, initial
        self.requests: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.requests.append(messages)
        rows = re.findall(r"^(\d+)\. CLAIM: (.*)\nCLAIM REFERENCE: (.*)",
                          messages[-1].content, re.MULTILINE)
        decisions = [{"claim_index": int(i), "reason": "Explicit offline decision.",
            "status": ("needs_review" if self.initial and len(self.requests) == 1 else self.status)
                      if json.loads(ref)["claim_id"] == "m1" else "supported"}
            for i, _, ref in rows]
        return ModelResponse(json.dumps({"decisions": decisions}), model)


def initial_review(
    reviewer: PlainReviewer, old: str = "Each user is initialized from a persona seed.",
) -> tuple[Artifact, ModelReviewResult, Reviser]:
    artifact, payload, _ = control("memconflict")
    complete = copy.deepcopy(payload["deep_readings"]["claim_units"][0])
    payload["deep_readings"]["claim_units"][0]["text"] = old
    reading = parse_paper_reading(json.dumps(payload), artifact)
    claims, _ = validate_paper_reading(reading, artifact)
    claims, _, _ = apply_anchor_resolution(claims, artifact)
    initial = review_publication_facts(claims, reviewer, model="offline",
                                      readings=[reading], artifacts=[artifact])
    return artifact, initial, Reviser(artifact, complete)


@pytest.mark.parametrize("status", ["supported", "needs_review", "unsupported"])
def test_plain_review_gets_exact_prior_assertion_and_evidence_without_promoting_a_refusal(
    status: str,
) -> None:
    reviewer = PlainReviewer(status)
    artifact, initial, reviser = initial_review(reviewer)
    original = copy.deepcopy(initial)
    result = revise_publication_facts(initial, reviser, model="offline", verifier=reviewer,
        verifier_model="offline", artifacts=[artifact])
    changed = next(c for c in result.claims if c.metadata.get("fact_revision"))
    request = "\n".join(m.content for m in reviewer.requests[-1])
    assert "AMENDMENT HISTORY (JSON):\n" in request
    history, _ = json.JSONDecoder().raw_decode(request.split("AMENDMENT HISTORY (JSON):\n", 1)[1])
    refs = [json.loads(ref) for ref in re.findall(r"^CLAIM REFERENCE: (.*)", request, re.MULTILINE)]
    reference = next(ref for ref in refs if ref["claim_id"] == "m1")
    assert history == [{**reference, "revision_of": changed.metadata["fact_revision"]}]
    assert "do not approve removal of necessary qualifications" in request
    assert "AMENDMENT HISTORY" not in "\n".join(m.content for m in reviewer.requests[0])
    context = json.loads(request.split("FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n", 1)[1])
    assert any(artifact.text in s["reading_packet"] for s in context["full_sources"])
    assert fact_is_reviewed(changed) is (status == "supported")
    assert initial == original
    assert len(reviewer.requests) == 2 and len(reviser.requests) == 1
    assert revise_publication_facts(result, reviser, model="offline", verifier=reviewer,
        verifier_model="offline", artifacts=[artifact]) is result


def test_plain_verifier_cache_separates_different_prior_assertions(tmp_path: Path) -> None:
    backend = PlainReviewer(initial=False)
    cached = CachedLLMProvider(backend, cache_dir=tmp_path, task_name="verifier")
    for old in ["Each user is initialized from a persona seed.",
                "Each user is initialized from a persona seed.",
                "A user's initialization uses a persona seed."]:
        artifact, initial, reviser = initial_review(PlainReviewer(), old)
        result = revise_publication_facts(initial, reviser, model="offline", verifier=cached,
            verifier_model="offline", artifacts=[artifact])
        assert any(fact_is_reviewed(c) and c.metadata.get("fact_revision") for c in result.claims)
    assert len(backend.requests) == 2  # Exact repeat hits; different amendment history misses.


@pytest.mark.parametrize("entry", ["paper", "daily"])
@pytest.mark.parametrize("failure", ["proposal", "review"])
def test_production_failure_records_actual_amendment_route_and_stops(
    entry: str, failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, response, chinese = control("memconflict")
    complete = copy.deepcopy(response["deep_readings"]["claim_units"][0])
    response["deep_readings"]["claim_units"][0]["text"] = (
        "Each user is initialized from a persona seed.")
    artifact = replace(artifact, source=replace(artifact.source, score=1))
    order = []

    class AmendingReader(Reading):
        def complete_with_schema(
            self, messages: list[Message], *, model: str, response_schema: dict,
        ) -> ModelResponse:
            if "revisions" not in response_schema["properties"]:
                return super().complete_with_schema(messages, model=model,
                                                    response_schema=response_schema)
            order.append("amend")
            if failure == "proposal":
                raise AnalysisError("Offline proposal failure")
            return Reviser(artifact, complete).complete_with_schema(messages, model=model,
                                                                  response_schema=response_schema)

    class FailingReview(Reviewer):
        def complete_with_schema(
            self, messages: list[Message], *, model: str, response_schema: dict,
        ) -> ModelResponse:
            if self.requests and failure == "review":
                order.append("recheck")
                raise AnalysisError("Offline recheck failure")
            order.append("review")
            return super().complete_with_schema(messages, model=model,
                                                response_schema=response_schema)

    reader = AmendingReader(response, order)
    verifier, writer = FailingReview(), Writing(chinese, order)
    verifier.reader_contexts = {**OFFLINE_READER_CONTEXTS,
                               "fake-verifier": OFFLINE_READER_CONTEXTS["offline"]}
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"],
                                      "report_language": "zh"}]})
    if entry == "paper":
        monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
        def call() -> Path:
            return paper.run_paper(tmp_path, config, "memory", artifact.source.url,
                reader, model="fake-reader", verifier=verifier, verifier_model="fake-verifier",
                localizer=writer, localization_model="offline", language="zh")
    else:
        from test_pipeline_fake import FakeConnector

        monkeypatch.setattr(daily, "ingest_source", lambda *_: artifact)
        def call() -> Path:
            return daily.run_daily(tmp_path, config, "memory", connectors=[FakeConnector()],
                deep_reader=reader, deep_model="fake-reader", verifier=verifier,
                verifier_model="fake-verifier", localizer=writer, localization_model="offline",
                language="zh", deep_limit=1)
    with pytest.raises(AnalysisError, match="Offline (proposal|recheck) failure"):
        call()
    run = next((tmp_path / "runs").iterdir())
    route = {"stage": "reader" if failure == "proposal" else "verifier",
        "provider": reader.name if failure == "proposal" else verifier.name,
        "model": "fake-reader" if failure == "proposal" else "fake-verifier"}
    saved = json.loads((run / "run_error.json").read_text())
    assert {key: saved[key] for key in route} == route
    assert json.loads((run / "manifest.json").read_text())["metadata"]["failure"] == saved
    audit = json.loads((run / "fact_revision.json").read_text())
    assert audit["status"] == "failed" and audit["initial_feedback"]
    assert audit["failure"] == route
    events = [json.loads(line) for line in (run / "run_progress.jsonl").read_text().splitlines()]
    stopped = next(e for e in reversed(events) if e["status"] == "failed")
    assert {key: stopped[key] for key in route} == route
    assert order == ["reader", "review", "amend"] + (["recheck"] if failure == "review" else [])
    assert not (run / "paper.md").exists() and not (run / "draft.json").exists()
