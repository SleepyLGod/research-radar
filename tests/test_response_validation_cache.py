"""Task-level validation protects cache writes and previously saved replies."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS, source_response
from test_explanation_support_contract import _reading
from test_localization import _claim
from test_paper_reading import _artifact, _claim_units_fixture
from test_publication_composition import candidates

from research_radar.analysis.localization import (
    _compose_reading,
    localization_failed,
    localize_report_content,
)
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_reading import model_paper_reading_with_attempts
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.reader_input import ReaderInputError
from research_radar.analysis.review import review_publication_facts
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, SourceCandidate, SourceType


@pytest.mark.parametrize("bad", ["structure", "paragraph", "support", "quantity"])
def test_legacy_translation_validates_before_cache_write_and_rechecks_old_hits(
    tmp_path: Path, bad: str,
) -> None:
    reading = replace(_reading("Accuracy is 70%.", ["c1"]), claim_units=[])
    valid = {"readings": [{"index": 0, "reader_explanation": {"opening_context": [{
        "text": "准确率为 70%。", "supporting_claim_ids": ["c1"],
    }]}}]}
    invalid = json.loads(json.dumps(valid))
    if bad == "structure":
        invalid = {}
    elif bad == "paragraph":
        invalid["readings"][0]["reader_explanation"] = {}
    elif bad == "support":
        invalid["readings"][0]["reader_explanation"]["opening_context"][0][
            "supporting_claim_ids"] = ["c999"]
    else:
        invalid["readings"][0]["reader_explanation"]["opening_context"][0][
            "text"] = "准确率为 99%。"
    underlying = TaskReplies([invalid, valid, valid])

    def run() -> object:
        cache = CachedLLMProvider(underlying, cache_dir=tmp_path, task_name="report_localization")
        return localize_report_content(readings=[reading], claims=[], sources=[],
            provider=cache, model="offline", language="zh")

    assert localization_failed(run())
    assert underlying.calls == 1
    assert not list(tmp_path.rglob("*.json"))
    assert not localization_failed(run())
    saved = next(tmp_path.rglob("*.json"))
    record = json.loads(saved.read_text())
    record["content"] = json.dumps(invalid)
    saved.write_text(json.dumps(record))
    recovered = run()
    assert not localization_failed(recovered)
    assert recovered.readings[0].reader_explanation.opening_context[0].text == "准确率为 70%。"
    assert underlying.calls == 3
    assert not localization_failed(run())
    assert underlying.calls == 3


def test_display_translation_quantity_failure_is_not_cached(tmp_path: Path) -> None:
    claim = replace(_claim(), text="Experiment: Accuracy is 70%.")
    valid = {"claims": [{"index": 0, "text": "准确率为 70%。"}]}
    provider = TaskReplies([{"claims": [{"index": 0, "text": "准确率为 99%。"}]}, valid])
    cache = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="report_localization")
    failed = localize_report_content(readings=[], claims=[claim], sources=[],
        provider=cache, model="offline", language="zh")
    assert localization_failed(failed)
    assert failed.claims == [claim]
    assert any(f.metadata.get("kind") == "report_localization_quantity_changed"
               for f in failed.findings)
    assert not list(cache.cache_dir.glob("*.json"))
    assert not localization_failed(localize_report_content(readings=[], claims=[claim], sources=[],
        provider=cache, model="offline", language="zh"))
    assert provider.calls == 2


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
