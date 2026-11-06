"""Offline daily-pipeline regressions for verified public content."""

import io
import json
from pathlib import Path
from urllib.request import Request

import pytest
from reader_fixtures import OFFLINE_READER_CONTEXTS
from reader_fixtures import OfflineStaticProvider as StaticProvider
from test_pipeline_fake import (
    DEEP_READING_FIXTURE_TEXT,
    FakeConnector,
    SequenceProvider,
    _deep_reading_claim_units_json,
)

from research_radar.analysis import openai_compatible as transport
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.providers import Message
from research_radar.analysis.routing import build_provider
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.models import Artifact, SourceCandidate
from research_radar.pipeline import daily, paper
from research_radar.security.secrets import InMemorySecretBackend, SecretManager
from research_radar.storage.files import read_json, read_jsonl


@pytest.mark.parametrize("mode", ["daily", "paper"])
def test_unverified_explanation_stays_in_readings_not_public_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    payload = json.loads(_deep_reading_claim_units_json())
    fact = "Memory benchmarks reward unsupported answers."
    explanation = {
        "opening_context": [{
            "text": "Competing memory systems do not implement forgetting.",
            "supporting_claim_ids": ["c1"],
        }],
    }
    payload["deep_readings"]["claim_units"] = [{
        "claim_id": "c1", "section": "problem", "claim_kind": "fact",
        "text": fact, "evidence": [{"quote": fact}], "publishable_default": True,
    }]
    payload["deep_readings"]["reader_explanation"] = explanation
    reader = SequenceProvider([json.dumps(payload)])
    verifier = SequenceProvider(['{"decisions": [{"claim_index": 1, "status": "supported"}]}'])
    monkeypatch.setattr(
        daily if mode == "daily" else paper, "ingest_source",
        lambda source, _: Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT),
    )
    if mode == "daily":
        run = daily.run_daily(
            tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
            deep_limit=1, verifier=verifier, figure_extractor=lambda *_a, **_k: [],
        )
        outputs = [(run / "daily.md").read_text(), (run / "wechat.html").read_text(),
                   json.dumps(read_json(run / "article_draft.json"))]
    else:
        run = paper.run_paper(
            tmp_path, config, "memory", "https://example.com/paper", reader,
            model="offline", verifier=verifier,
        )
        outputs = [(run / "paper.md").read_text()]

    saved = read_jsonl(run / "readings.jsonl")[0]["reader_explanation"]
    assert saved["opening_context"][0]["text"] == explanation["opening_context"][0]["text"]
    assert saved["opening_context"][0]["supporting_claim_ids"] == ["c1"]
    assert saved["opening_context"][0]["review"]["status"] == "needs_review"
    assert all(fact in output for output in outputs)
    assert all(explanation["opening_context"][0]["text"] not in output for output in outputs)
    assert any(claim["status"] == "supported" for claim in read_jsonl(run / "claims.jsonl"))
    assert len(reader.messages) == len(verifier.messages) == 1


def test_single_paper_reading_json_is_not_a_valid_verifier_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    monkeypatch.setattr(
        paper,
        "ingest_source",
        lambda source, _: Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT),
    )

    run = paper.run_paper(
        tmp_path,
        config,
        "memory",
        "https://example.com/paper",
        StaticProvider(_deep_reading_claim_units_json()),
        model="offline",
    )

    assert all(claim["status"] != "supported" for claim in read_jsonl(run / "claims.jsonl"))
    assert "Memory benchmarks reward unsupported answers." not in (run / "paper.md").read_text(
        encoding="utf-8"
    )
    assert any(
        finding["metadata"]["kind"] == "model_review_parse_error"
        for finding in read_jsonl(run / "review_findings.jsonl")
    )


@pytest.mark.parametrize(
    "feedback",
    [
        "not JSON",
        '{"decisions": []}',
        '{"decisions": [{"claim_index": 1, "status": "maybe"}]}',
    ],
)
def test_daily_invalid_verifier_has_no_public_deep_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    feedback: str,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    reader = SequenceProvider([_deep_reading_claim_units_json()])
    verifier = SequenceProvider([feedback])
    monkeypatch.setattr(
        daily,
        "ingest_source",
        lambda source, _: Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT),
    )
    run = daily.run_daily(
        tmp_path,
        config,
        "memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_limit=1,
        verifier=verifier,
        figure_extractor=lambda *_args, **_kwargs: [],
    )

    draft = read_json(run / "article_draft.json")
    assert draft["metadata"]["deep_read_count"] == 0
    assert draft["metadata"]["research_outcome"]["status"] == "incomplete"
    assert draft["claims"] == []
    assert "Memory benchmarks reward unsupported answers." not in (run / "wechat.html").read_text(
        encoding="utf-8"
    )
    assert any(
        finding["metadata"]["kind"].startswith("model_review_")
        for finding in read_jsonl(run / "review_findings.jsonl")
    )
    assert len(reader.messages) == len(verifier.messages) == 1


def test_daily_bad_numeric_translation_keeps_original_for_audit_and_stops_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    payload = json.loads(_deep_reading_claim_units_json())
    text = "The authors report accuracy of 70.0%."
    payload["deep_readings"]["claim_units"] = [
        {
            "claim_id": "c1",
            "section": "experiment",
            "claim_kind": "fact",
            "text": text,
            "evidence": [{"quote": text}],
            "publishable_default": True,
        }
    ]
    reader = SequenceProvider([json.dumps(payload)])
    verifier = SequenceProvider([json.dumps({"decisions": [
        {"claim_index": 1, "status": "supported"},
        {"claim_index": 2, "status": "needs_review",
         "reason": "Offline method-context rejection isolates the translation check."},
    ]})])
    localizer = SequenceProvider(
        [
            '{"reader_explanation": {"experiment_interpretation": [{"text": '
            '"作者报告准确率为 70.0%。", "supporting_claim_ids": ["c1"]}]},'
            '"claims": [{"claim_id": "c1", "text": "Experiment: 作者报告准确率为99.9%。"}]}',
        ]
    )

    def ingest(source: SourceCandidate, _directory: Path) -> Artifact:
        return Artifact(source=source, text=f"{DEEP_READING_FIXTURE_TEXT}\n{text}")

    monkeypatch.setattr(daily, "ingest_source", ingest)
    with pytest.raises(AnalysisError, match="Chinese report localization failed"):
        daily.run_daily(
            tmp_path, config, "memory", [FakeConnector()], deep_reader=reader, deep_limit=1,
            verifier=verifier, localizer=localizer, localization_model="offline",
            language="zh", figure_extractor=lambda *_args, **_kwargs: [],
        )
    run = next((tmp_path / "runs").iterdir())
    assert not (run / "article_draft.json").exists()
    assert not (run / "wechat.html").exists()
    assert read_jsonl(run / "claims.jsonl")[0]["text"] == f"Experiment: {text}"
    assert read_jsonl(run / "publication_claims.jsonl")[0]["text"] == f"Experiment: {text}"
    assert read_json(run / "manifest.json")["metadata"]["failure"]["stage"] == "localization"
    assert len(reader.messages) == len(verifier.messages) == 1
    assert len(localizer.messages) == 1


@pytest.mark.parametrize("entries", [[], [{"index": True}], [{"index": 0}, {"index": 0}]])
def test_daily_invalid_localization_index_cannot_publish_chinese_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: list[dict[str, object]],
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    monkeypatch.setattr(daily, "ingest_source", lambda source, _directory: Artifact(
        source=source, text=DEEP_READING_FIXTURE_TEXT,
    ))
    payload = json.loads(_deep_reading_claim_units_json())
    payload["deep_readings"]["claim_units"] = [payload["deep_readings"]["claim_units"][0]]
    payload["deep_readings"]["claim_units"][0]["claim_id"] = "c1"
    reader = SequenceProvider([json.dumps(payload)])
    verifier = SequenceProvider([json.dumps({"decisions": [
        {"claim_index": 1, "status": "supported"},
        {"claim_index": 2, "status": "needs_review",
         "reason": "Offline method-context rejection isolates the translation check."},
    ]})])
    localizer = SequenceProvider([
        json.dumps({"reader_explanation": {"problem_walkthrough": [{
            "text": "这个基准奖励缺少证据的答案。", "supporting_claim_ids": ["c1"],
        }]}, "claims": entries}),
    ])

    with pytest.raises(AnalysisError, match="Chinese report localization failed"):
        daily.run_daily(
            tmp_path, config, "memory", [FakeConnector()], deep_reader=reader, deep_limit=1,
            verifier=verifier, localizer=localizer, localization_model="offline",
            language="zh", figure_extractor=lambda *_args, **_kwargs: [],
        )

    assert not list(tmp_path.rglob("article_draft.json"))
    assert not list(tmp_path.rglob("wechat.html"))
    assert len(reader.messages) == 1
    assert len(verifier.messages) == 1, "Only the original fact review ran; no final review"
    assert len(localizer.messages) == 1, "Invalid composition stops without another request"


def test_daily_forwards_matched_experiment_context_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    payload = json.loads(_deep_reading_claim_units_json())
    quote = "The selected run scores 70.4% overall (214/304)."
    explanation = "The paper reports 70.4% on LoCoMo using 304 questions."
    payload["deep_readings"]["claim_units"] = [{
        "claim_id": "c1", "section": "experiment", "claim_kind": "fact",
        "text": explanation, "evidence": [{"quote": quote}], "publishable_default": True,
    }]
    payload["deep_readings"]["reader_explanation"] = {
        "experiment_interpretation": [{"text": explanation, "supporting_claim_ids": ["c1"]}],
    }
    reader = SequenceProvider([json.dumps(payload)])
    verifier = SequenceProvider(['{"decisions": [{"claim_index": 1, "status": "supported"}]}'])
    text = (
        f"{DEEP_READING_FIXTURE_TEXT}\n2.1 LoCoMo evaluation\n"
        f"The evaluation uses 304 questions.\n{quote}\n"
        "2.2 Separate experiment\nThis unrelated score is 99.9%."
    )
    monkeypatch.setattr(
        daily, "ingest_source", lambda source, _: Artifact(source=source, text=text),
    )

    run = daily.run_daily(
        tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
        deep_limit=1, verifier=verifier, figure_extractor=lambda *_args, **_kwargs: [],
    )

    prompt = verifier.messages[0][-1].content
    assert "2.1 LoCoMo evaluation" in prompt
    assert "214/304" in prompt
    claim_request, full_context = prompt.split("FULL SOURCE CONTEXT AND PARAGRAPHS (JSON):\n", 1)
    assert "unrelated score" not in claim_request
    assert "unrelated score" in json.loads(full_context)["full_sources"][0]["reading_packet"]
    draft = read_json(run / "article_draft.json")
    assert draft["metadata"]["deep_read_count"] == 1
    assert draft["claims"][0]["status"] == "supported"
    assert quote in draft["claims"][0]["evidence"][0]["quote"]
    assert draft["claims"][0]["evidence"][0]["quote"] in text
    assert explanation in (run / "daily.md").read_text()


@pytest.mark.parametrize(
    ("text", "quotes", "expected_public"),
    [
        ("Author-reported: MemTree was evaluated on 304 questions.",
         ["The evaluation of MemTree used 304 questions."], True),
        ("Author-reported: Self-RAG was evaluated on 304 questions.",
         ["The evaluation of MemTree used 304 questions."], False),
        ("FRQAD scores 100.0%, versus 70.7% for Fisher-Rao.",
         ["FRQAD 18,840 100.0%", "Fisher-Rao 13,316 70.7%"], True),
        ("FRQAD scores 70.7%, versus 100.0% for Fisher-Rao.",
         ["FRQAD 18,840 100.0%\nFisher-Rao 13,316 70.7%"], False),
    ],
)
def test_daily_public_draft_preserves_attribution_and_method_value_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    text: str, quotes: list[str], expected_public: bool,
) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    payload = json.loads(_deep_reading_claim_units_json())
    payload["deep_readings"]["claim_units"] = [{
        "claim_id": "c1", "section": "experiment", "claim_kind": "fact",
        "text": text, "evidence": [{"quote": quote} for quote in quotes],
        "publishable_default": True,
    }]
    payload["deep_readings"]["reader_explanation"] = {
        "experiment_interpretation": [{"text": text, "supporting_claim_ids": ["c1"]}],
    }
    reader = SequenceProvider([json.dumps(payload)])
    verifier = SequenceProvider(['{"decisions": [{"claim_index": 1, "status": "supported"}]}'])
    source_text = (
        f"{DEEP_READING_FIXTURE_TEXT}\n2.1 Evaluation\n"
        "The evaluation of MemTree used 304 questions.\n"
        "Table 4: Preference evaluation\nMethod Correct pairs Accuracy\n"
        "FRQAD 18,840 100.0%\nFisher-Rao 13,316 70.7%"
    )
    monkeypatch.setattr(
        daily, "ingest_source", lambda source, _: Artifact(source=source, text=source_text),
    )

    run = daily.run_daily(
        tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
        deep_limit=1, verifier=verifier, figure_extractor=lambda *_args, **_kwargs: [],
    )

    draft = read_json(run / "article_draft.json")
    assert draft["metadata"]["deep_read_count"] == int(expected_public)
    if expected_public:
        assert draft["claims"][0]["text"] == f"Experiment: {text}"
        selected = [anchor["quote"] for anchor in draft["claims"][0]["evidence"]]
        assert all(any(quote in block for block in selected) for quote in quotes)
        assert all(block in source_text for block in selected)
        assert text in (run / "daily.md").read_text(encoding="utf-8")
    else:
        assert draft["claims"] == []
        assert text not in (run / "wechat.html").read_text(encoding="utf-8")


def test_streaming_reader_reuses_daily_verifier_and_public_draft_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = parse_config({
        "topics": [{"id": "memory", "queries": ["agent memory"]}],
        "model_providers": {"offline": {
            "kind": "openai_compatible", "base_url": "https://example.invalid/chat/completions",
            "api_key_secret": "offline.key", "stream": True,
        }},
    })
    manager = SecretManager(InMemorySecretBackend())
    manager.backend.set_secret("offline.key", "offline-only-key")
    underlying = build_provider(config, manager, "offline")
    underlying.reader_contexts = OFFLINE_READER_CONTEXTS
    reader = CachedLLMProvider(underlying,
                               cache_dir=tmp_path / "model-cache", task_name="reader")
    raw = _deep_reading_claim_units_json()
    payloads = []

    def request(req: Request, **_kwargs: object) -> io.BytesIO:
        from reader_fixtures import source_response

        payloads.append(json.loads(req.data))
        answer = source_response(raw, [Message(**m) for m in payloads[-1]["messages"]])
        chunks = [{"reasoning_content": "private reasoning"}, {"content": answer[:100]},
                  {"content": answer[100:]}]
        body = b"".join(
            f"data: {json.dumps({'choices': [{'index': 0, 'delta': delta}]})}\n\n".encode()
            for delta in chunks
        )
        return io.BytesIO(body + b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                          + b'data: [DONE]\n\n')

    monkeypatch.setattr(transport, "urlopen", request)
    monkeypatch.setattr(
        daily, "ingest_source", lambda source, _: Artifact(source=source,
                                                           text=DEEP_READING_FIXTURE_TEXT),
    )
    verifier = SequenceProvider(['{"decisions":[{"claim_index":1,"status":"supported"}]}'])

    run = daily.run_daily(
        tmp_path, config, "memory", [FakeConnector()], deep_reader=reader,
        deep_limit=1, verifier=verifier, figure_extractor=lambda *_a, **_k: [],
    )

    draft = read_json(run / "article_draft.json")
    assert draft["metadata"]["research_outcome"]["status"] == "ready"
    assert draft["metadata"]["deep_read_count"] == 1
    assert draft["claims"][0]["status"] == "supported"
    assert "Memory benchmarks reward unsupported answers." in (run / "daily.md").read_text()
    assert len(payloads) == 1 and payloads[0]["stream"] is True
    assert len(verifier.messages) == 1
    assert "Memory benchmarks reward unsupported answers." in verifier.messages[0][-1].content
    files = [
        p for p in tmp_path.rglob("*")
        if p.is_file() and p.suffix in {".json", ".jsonl", ".md"}
    ]
    assert all("private reasoning" not in p.read_text(encoding="utf-8") for p in files)
