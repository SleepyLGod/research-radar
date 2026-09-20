"""Offline regression for sources listed before their first successful deep read."""

import json
from pathlib import Path

from test_pipeline_fake import (
    DEEP_READING_FIXTURE_TEXT,
    FakeConnector,
    SequenceProvider,
    _deep_reading_json,
)

from research_radar.config import parse_config
from research_radar.exceptions import DiscoveryError, IngestionError
from research_radar.models import Artifact, SourceCandidate, SourceType
from research_radar.pipeline import daily
from research_radar.storage.files import read_json


def test_seen_retry_candidate_does_not_hide_new_version(tmp_path: Path) -> None:
    config = parse_config({"topics": [{
        "id": "memory", "queries": ["agent memory"], "source_intent": "research_brief",
    }]})

    class VersionsConnector:
        name = "fake"
        versions = [1]

        def discover(self, context) -> list[SourceCandidate]:
            return [SourceCandidate(
                title="Agent memory benchmark paper",
                url=f"https://arxiv.org/abs/2604.01707v{version}",
                canonical_id=f"2604.01707v{version}",
                source_type=SourceType.PAPER, source_name="arxiv",
                summary="An agent memory benchmark paper with evidence evaluation.",
                score=3.0 - version,
            ) for version in self.versions]

    connector = VersionsConnector()
    daily.run_daily(tmp_path, config, "memory", [connector])
    connector.versions = [1, 2]
    run = daily.run_daily(tmp_path, config, "memory", [connector])
    assert read_json(run / "summary.json")["public_reportable_source_count"] == 1
    assert "https://arxiv.org/abs/2604.01707v2" in (run / "daily.md").read_text()


def test_listed_source_can_be_read_then_is_suppressed(monkeypatch, tmp_path: Path) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    daily.run_daily(tmp_path, config, "memory", [FakeConnector()])
    reader = SequenceProvider([_deep_reading_json()])
    verifier = SequenceProvider(
        [
            json.dumps(
                {
                    "decisions": [
                        {
                            "index": index,
                            "status": "supported",
                            "reason": "Fixture evidence matches.",
                        }
                        for index in range(1, 7)
                    ]
                }
            )
        ]
    )
    monkeypatch.setattr(
        daily,
        "ingest_source",
        lambda source, _: Artifact(
            source=source,
            text=DEEP_READING_FIXTURE_TEXT,
        ),
    )
    run = daily.run_daily(
        tmp_path,
        config,
        "memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_limit=1,
        verifier=verifier,
    )
    draft = read_json(run / "article_draft.json")
    assert len(reader.messages) == 1
    assert draft["metadata"]["deep_read_count"] == 1
    assert draft["metadata"]["research_outcome"]["status"] == "ready"
    seen = next(
        section for section in draft["sections"] if section["metadata"]["kind"] == "seen_before"
    )
    assert not seen["metadata"]["sources"]
    assert (
        read_json(run / "summary.json")["research_outcome"] == draft["metadata"]["research_outcome"]
    )
    again = daily.run_daily(
        tmp_path,
        config,
        "memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_limit=1,
        verifier=verifier,
    )
    assert len(reader.messages) == 1
    assert read_json(again / "summary.json")["research_outcome"]["status"] == "no_new_content"
    assert len(verifier.messages) == 1


def test_full_text_failure_is_retained_and_can_retry(monkeypatch, tmp_path: Path) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    reader = SequenceProvider([_deep_reading_json()])
    verifier = SequenceProvider([])

    def fail(source, directory):
        raise IngestionError("Fixture source unavailable")

    monkeypatch.setattr(daily, "ingest_source", fail)
    failed = daily.run_daily(
        tmp_path,
        config,
        "memory",
        [FakeConnector()],
        deep_reader=reader,
        deep_limit=1,
        verifier=verifier,
    )
    outcome = read_json(failed / "summary.json")["research_outcome"]
    assert outcome == {"status": "incomplete", "reasons": ["full_text_unavailable"]}
    assert not verifier.messages
    assert "verification" not in read_json(failed / "article_draft.json")["lede"].lower()
    monkeypatch.setattr(
        daily,
        "ingest_source",
        lambda source, _: Artifact(
            source=source,
            text=DEEP_READING_FIXTURE_TEXT,
        ),
    )
    retried = daily.run_daily(
        tmp_path, config, "memory", [FakeConnector()], deep_reader=reader, deep_limit=1
    )
    assert read_json(retried / "summary.json")["research_outcome"]["status"] == "ready"


def test_discovery_failure_does_not_claim_verification_rejected(tmp_path: Path) -> None:
    class FailedConnector:
        name = "arxiv"

        def discover(self, context):
            raise DiscoveryError("Fixture discovery unavailable")

    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    verifier = SequenceProvider([])
    run = daily.run_daily(
        tmp_path,
        config,
        "memory",
        [FailedConnector()],
        deep_reader=SequenceProvider([]),
        deep_limit=1,
        verifier=verifier,
    )
    draft = read_json(run / "article_draft.json")
    assert not verifier.messages
    assert draft["metadata"]["research_outcome"]["status"] == "incomplete"
    assert "discovery_failed" in draft["metadata"]["research_outcome"]["reasons"]
    assert "verification" not in draft["lede"].lower()


def test_actual_verifier_rejections_have_no_public_deep_entry(monkeypatch, tmp_path: Path) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    verifier = SequenceProvider(
        [
            json.dumps(
                {
                    "decisions": [
                        {"index": index, "status": "unsupported", "reason": "Fixture rejection."}
                        for index in range(1, 7)
                    ]
                }
            )
        ]
    )
    monkeypatch.setattr(
        daily,
        "ingest_source",
        lambda source, _: Artifact(
            source=source,
            text=DEEP_READING_FIXTURE_TEXT,
        ),
    )
    run = daily.run_daily(
        tmp_path,
        config,
        "memory",
        [FakeConnector()],
        deep_reader=SequenceProvider([_deep_reading_json()]),
        deep_limit=1,
        verifier=verifier,
    )
    draft = read_json(run / "article_draft.json")
    assert len(verifier.messages) == 1
    assert draft["metadata"]["deep_read_count"] == 0
    assert draft["metadata"]["research_outcome"] == {
        "status": "incomplete",
        "reasons": ["verification_no_public_claims"],
    }
    assert "verification ran" in draft["lede"]


def test_unanchored_evidence_does_not_invoke_or_blame_verifier(monkeypatch, tmp_path: Path) -> None:
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    payload = json.loads(_deep_reading_json())
    for section in payload["deep_readings"].values():
        if isinstance(section, dict) and "evidence" in section:
            section["evidence"] = [{"quote": "Absent quotation with no source support."}]
    verifier = SequenceProvider([])
    monkeypatch.setattr(
        daily,
        "ingest_source",
        lambda source, _: Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT),
    )
    run = daily.run_daily(
        tmp_path, config, "memory", [FakeConnector()],
        deep_reader=SequenceProvider([json.dumps(payload)]), deep_limit=1, verifier=verifier,
    )
    draft = read_json(run / "article_draft.json")
    assert not verifier.messages
    assert draft["metadata"]["research_outcome"] == {
        "status": "incomplete", "reasons": ["evidence_insufficient"],
    }
    assert draft["metadata"]["deep_read_count"] == 0
    assert "verification" not in draft["lede"].lower()


def test_new_paper_is_ranked_before_previously_listed_paper(monkeypatch, tmp_path: Path) -> None:
    from dataclasses import replace

    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    daily.run_daily(tmp_path, config, "memory", [FakeConnector()])

    class TwoPapers(FakeConnector):
        def discover(self, context):
            previous = super().discover(context)[0]
            return [
                previous,
                replace(previous, title="New memory paper", url="https://example.com/new"),
            ]

    ingested = []

    def ingest(source, directory):
        ingested.append(source.url)
        return Artifact(source=source, text=DEEP_READING_FIXTURE_TEXT)

    monkeypatch.setattr(daily, "ingest_source", ingest)
    daily.run_daily(
        tmp_path,
        config,
        "memory",
        [TwoPapers()],
        deep_reader=SequenceProvider([_deep_reading_json()]),
        deep_limit=1,
    )
    assert ingested == ["https://example.com/new"]
