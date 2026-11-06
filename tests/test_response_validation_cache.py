"""Task-level validation protects cache writes and previously saved replies."""

import json
from pathlib import Path

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS, source_response
from test_paper_reading import _artifact, _claim_units_fixture
from test_publication_composition import candidates

from research_radar.analysis.localization import _compose_reading
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import model_paper_reading_with_attempts
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import ReaderInputError
from research_radar.analysis.review import review_publication_facts
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, SourceCandidate, SourceType


class TaskReplies:
    """A deterministic task provider with no executable or network access."""

    name = "offline"
    reader_contexts = {**OFFLINE_READER_CONTEXTS}

    def __init__(self, replies: list[dict], *, schema: bool = False) -> None:
        self.replies = replies
        self.supports_response_schema = schema
        self.calls = 0

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.calls += 1
        return ModelResponse(source_response(json.dumps(self.replies.pop(0)), messages), model)

    def complete_with_schema(
        self, messages: list[Message], *, model: str, response_schema: dict,
    ) -> ModelResponse:
        assert response_schema
        return self.complete(messages, model=model)


@pytest.mark.parametrize("schema", [False, True])
def test_reader_rejects_invalid_content_before_caching(tmp_path: Path, schema: bool) -> None:
    valid = json.loads(_claim_units_fixture(["Memory benchmark fixture."]))
    invalid = json.loads(json.dumps(valid))
    invalid["deep_readings"]["evaluation_context"] = {
        "data_construction": ["c999"], "available_inputs": [], "outcome_measurement": [],
    }
    underlying = TaskReplies([invalid, valid, valid], schema=schema)
    cache = CachedLLMProvider(underlying, cache_dir=tmp_path, task_name="deep_reading")

    def run() -> object:
        return model_paper_reading_with_attempts(_artifact(), cache, model="fake-reader",
                                                facts_only=True)

    with pytest.raises(AnalysisError) as error:
        run()
    assert error.value.reader_attempts[0]["status"] == "failed"
    assert not list(cache.cache_dir.glob("*.json"))
    assert run().reading.claim_units
    assert underlying.calls == 2
    saved = next(cache.cache_dir.glob("*.json"))
    record = json.loads(saved.read_text())
    record["content"] = source_response(json.dumps(invalid), [Message("user", "")])
    saved.write_text(json.dumps(record))
    assert run().reading.claim_units
    assert underlying.calls == 3 and cache.hit_count == 0
    run()
    assert underlying.calls == 3 and cache.hit_count == 1
    cache.reader_contexts = {}
    with pytest.raises(ReaderInputError, match="reader_context_unknown"):
        run()
    assert underlying.calls == 3 and cache.hit_count == 1


def test_writer_rejects_invalid_content_before_caching(tmp_path: Path) -> None:
    reading, claim = candidates()
    valid = {"reader_explanation": {"experiment_interpretation": [{
        "text": "作者评估了 12 个模拟用户。", "supporting_claim_ids": ["c1"],
    }]}}
    underlying = TaskReplies([{}, valid, valid])
    cache = CachedLLMProvider(underlying, cache_dir=tmp_path, task_name="report_localization")
    with pytest.raises(AnalysisError):
        _compose_reading(reading, [claim], cache, model="offline")
    assert not list(cache.cache_dir.glob("*.json"))
    for _ in range(2):
        prose, _ = _compose_reading(reading, [claim], cache, model="offline")
        assert prose.experiment_interpretation
    assert underlying.calls == 2 and cache.hit_count == 1
    saved = next(cache.cache_dir.glob("*.json"))
    record = json.loads(saved.read_text())
    record["content"] = "{}"
    saved.write_text(json.dumps(record))
    prose, _ = _compose_reading(reading, [claim], cache, model="offline")
    assert prose.experiment_interpretation and underlying.calls == 3


def test_legacy_fact_review_rejects_incomplete_content_before_caching(tmp_path: Path) -> None:
    reading, claim = candidates()
    source = Artifact(SourceCandidate(reading.title, reading.source_url, SourceType.PAPER,
                                      "offline"), claim.evidence[0].quote)
    valid = {"decisions": [{"claim_index": 1, "status": "supported",
                            "reason": "Offline controlled approval."}]}
    underlying = TaskReplies([{}, valid, valid])
    cache = CachedLLMProvider(underlying, cache_dir=tmp_path, task_name="verifier")
    with pytest.raises(AnalysisError):
        review_publication_facts([claim], cache, model="offline", readings=[reading],
                                 artifacts=[source])
    assert not list(cache.cache_dir.glob("*.json"))
    for _ in range(2):
        result = review_publication_facts([claim], cache, model="offline", readings=[reading],
                                          artifacts=[source])
        assert result.claims[0].is_publishable()
    assert underlying.calls == 2 and cache.hit_count == 1
    saved = next(cache.cache_dir.glob("*.json"))
    record = json.loads(saved.read_text())
    record["content"] = "{}"
    saved.write_text(json.dumps(record))
    result = review_publication_facts([claim], cache, model="offline", readings=[reading],
                                       artifacts=[source])
    assert result.claims[0].is_publishable() and underlying.calls == 3


@pytest.mark.parametrize("schema", [False, True])
def test_cache_validation_does_not_turn_provider_failure_into_reader_repair(
    tmp_path: Path, schema: bool,
) -> None:
    class FailingReplies(TaskReplies):
        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            self.calls += 1
            raise AnalysisError("Offline provider failure, not a malformed Reader answer.")

    underlying = FailingReplies([], schema=schema)
    cache = CachedLLMProvider(underlying, cache_dir=tmp_path, task_name="deep_reading")
    with pytest.raises(AnalysisError, match="Offline provider failure"):
        model_paper_reading_with_attempts(_artifact(), cache, model="fake-reader", facts_only=True)
    assert underlying.calls == 1
    assert not list(cache.cache_dir.glob("*.json"))
