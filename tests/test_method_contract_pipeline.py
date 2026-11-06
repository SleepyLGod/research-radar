"""The new finite review contract reaches Chinese prose in the shared single-paper pipeline."""

import json
import socket
from dataclasses import replace

import pytest
from method_contract_controls import control
from reader_fixtures import OFFLINE_READER_CONTEXTS, source_response
from test_review_targets import SchemaReviewer

from research_radar.analysis.paper_reading import parse_paper_reading
from research_radar.analysis.providers import ModelResponse
from research_radar.config import parse_config
from research_radar.exceptions import AnalysisError
from research_radar.pipeline import paper
from research_radar.security.secrets import KeychainSecretBackend


class Reading:
    """A declared editorial extraction passed through the same schema call as a real Reader."""

    name = "offline-reader"
    supports_response_schema = True
    reader_contexts = OFFLINE_READER_CONTEXTS

    def __init__(self, response, order):
        self.response, self.order = response, order

    def complete(self, *_args, **_kwargs):
        raise AssertionError("No Reader fallback")

    def complete_with_schema(self, messages, *, model, response_schema):
        if "revisions" in response_schema["properties"]:
            self.order.append("amend")
            return ModelResponse(json.dumps({"revisions": {
                identity: {"text": None, "evidence": [],
                           "reason": "Offline control declines to change the extraction."}
                for identity in response_schema["properties"]["revisions"]["properties"]
            }}), model)
        self.order.append("reader")
        assert (
            "method"
            in response_schema["properties"]["deep_readings"]["items"]["properties"]["claim_units"][
                "items"
            ]["required"]
        )
        return ModelResponse(source_response(json.dumps(self.response), messages), model)


class Writing:
    """Human-authored Chinese control, not a live writing-quality measurement."""

    name = "offline-writer"
    reader_contexts = OFFLINE_READER_CONTEXTS

    def __init__(self, response, order):
        self.response, self.order = response, order

    def complete(self, messages, *, model):
        self.order.append("writer")
        return ModelResponse(json.dumps(self.response, ensure_ascii=False), model)


class Reviewing(SchemaReviewer):
    def __init__(self, order, bad=""):
        super().__init__(bad)
        self.order = order

    def complete_with_schema(self, *args, **kwargs):
        self.order.append("review")
        return super().complete_with_schema(*args, **kwargs)


def execute(root, name, monkeypatch, *, artifact=None, bad=""):
    """Exercise the production entry with source excerpts or a supplied complete source."""
    excerpt, response, chinese = control(name)
    artifact = artifact or excerpt
    artifact = replace(artifact, source=replace(artifact.source, score=1))
    order = []
    reviewer = Reviewing(order, bad)
    monkeypatch.setattr(paper, "ingest_source", lambda *_args: artifact)
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    run = paper.run_paper(
        root,
        config,
        "memory",
        artifact.source.url,
        Reading(response, order),
        model="offline",
        verifier=reviewer,
        verifier_model="offline",
        localizer=Writing(chinese, order),
        localization_model="offline",
        language="zh",
    )
    return run, reviewer, order


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_typed_reader_schema_review_writer_and_final_prose_in_production(
    name, tmp_path, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline regression must not access a network or credential")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)
    run, reviewer, order = execute(tmp_path, name, monkeypatch)
    assert order == ["reader", "review", "writer", "review"]
    assert len(reviewer.requests) == 2
    assert any(t["kind"] == "operation" for t in reviewer.requests[0][2].values())
    assert all(t["kind"] in ("fact", "paragraph") for t in reviewer.requests[1][2].values())
    rendered = (run / "paper.md").read_text().split("## 证据链")[0]
    assert "## 方法与机制" in rendered and "## 实验与评估" in rendered
    assert "## 局限与未来工作" in rendered
    if name == "memconflict":
        assert "宏平均" in rendered and "top-3" in rendered and "不含未来会话" in rendered
    else:
        assert all(
            s in rendered for s in ("辅助问题", "0.73", "0.80", "2.52", "1.21", "Mistral-7B")
        )
    saved = json.loads((run / "fact_review.json").read_text())
    assert saved["structured_review"]["raw_response"]
    assert (run / "localized_readings.jsonl").is_file()


@pytest.mark.parametrize("bad", ["missing", "duplicate", "unknown"])
def test_bad_review_never_reaches_writer_or_final_artifacts(tmp_path, monkeypatch, bad):
    with pytest.raises(AnalysisError):
        execute(tmp_path, "memconflict", monkeypatch, bad=bad)
    assert not list(tmp_path.rglob("paper.md"))
    assert not list(tmp_path.rglob("localized_readings.jsonl"))


def test_one_bounded_amendment_reaches_chinese_writer_and_final_review(tmp_path, monkeypatch):
    from test_fact_revision import Reviewer, Reviser

    artifact, response, chinese = control("memconflict")
    unit = json.loads(json.dumps(response["deep_readings"]["claim_units"][0]))
    response["deep_readings"]["claim_units"][0]["text"] = (
        "Each user is initialized from a persona seed.")
    order = []

    class AmendingReader(Reading):
        def complete_with_schema(self, messages, *, model, response_schema):
            if "revisions" in response_schema["properties"]:
                order.append("amend")
                return Reviser(artifact, unit).complete_with_schema(
                    messages, model=model, response_schema=response_schema)
            return super().complete_with_schema(messages, model=model,
                                                response_schema=response_schema)

    class BoundReviewer(Reviewer):
        def complete_with_schema(self, messages, *, model, response_schema):
            order.append("review")
            return super().complete_with_schema(messages, model=model,
                                                response_schema=response_schema)

    monkeypatch.setattr(paper, "ingest_source", lambda *_args: artifact)
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    run = paper.run_paper(tmp_path, config, "memory", artifact.source.url,
        AmendingReader(response, order), model="offline", verifier=BoundReviewer(),
        verifier_model="offline", localizer=Writing(chinese, order),
        localization_model="offline", language="zh")

    assert order == ["reader", "review", "amend", "review", "writer", "review"]
    audit = json.loads((run / "fact_revision.json").read_text())
    assert audit["status"] == "reviewed"
    assert audit["attempts"][0]["accepted_candidate_ids"] == ["m1"]
    assert audit["initial_claims"][0]["text"].endswith("from a persona seed.")
    assert "Persona Hub" in (run / "paper.md").read_text()
    assert "宏平均" in (run / "paper.md").read_text()


def test_failed_amendment_keeps_original_review_and_stops_before_writing(tmp_path, monkeypatch):
    from test_fact_revision import Reviewer

    artifact, response, chinese = control("memconflict")
    response["deep_readings"]["claim_units"][0]["text"] = (
        "Each user is initialized from a persona seed.")
    order = []

    class FailingAmendment(Reading):
        def complete_with_schema(self, messages, *, model, response_schema):
            if "revisions" in response_schema["properties"]:
                order.append("amend")
                raise AnalysisError("Offline amendment transport failure.")
            return super().complete_with_schema(messages, model=model,
                                                response_schema=response_schema)

    monkeypatch.setattr(paper, "ingest_source", lambda *_args: artifact)
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    with pytest.raises(AnalysisError, match="amendment transport failure"):
        paper.run_paper(tmp_path, config, "memory", artifact.source.url,
            FailingAmendment(response, order), model="offline", verifier=Reviewer(),
            verifier_model="offline", localizer=Writing(chinese, order),
            localization_model="offline", language="zh")
    run = next((tmp_path / "runs").iterdir())
    audit = json.loads((run / "fact_revision.json").read_text())
    assert audit["status"] == "failed"
    assert len(audit["attempts"]) == 1
    assert json.loads(audit["initial_feedback"])["structured_review"]
    assert audit["initial_readings"][0]["claim_units"][0]["text"] == (
        "Each user is initialized from a persona seed.")
    assert json.loads((run / "run_error.json").read_text())["stage"] == "reader"
    assert order == ["reader", "amend"]
    assert not (run / "paper.md").exists()


def test_real_wrong_pair_cannot_be_rebound_to_another_relation_assertion():
    artifact, response, _ = control("memconflict")
    first = response["deep_readings"]["method_flow"]["links"][0]
    first["relation_claim_id"] = "r3"  # r3 explicitly connects different declared operations.
    with pytest.raises(AnalysisError, match="endpoints"):
        parse_paper_reading(json.dumps(response), artifact)


@pytest.mark.parametrize("wrong", [False, True])
def test_numeric_narrative_beside_a_table_is_not_a_method_row(wrong):
    from research_radar.analysis.anchor_repair import apply_anchor_resolution
    from research_radar.models import (
        Artifact,
        Claim,
        ClaimStatus,
        EvidenceAnchor,
        SourceCandidate,
        SourceType,
    )

    quote = (
        "when using Mistral-7B as the\nLLM Reader, MemGuide increases JGA from 0.73 to 0.80\n"
        "and reduces DTE from 2.52 to 1.21"
    )
    text = "Table 3 Overall accuracy score\nMethod JGA DTE\nMemGuide 0.80 1.21\n" + quote
    source = SourceCandidate("Offline", "https://example.test/paper", SourceType.PAPER, "fixture")
    claim = Claim(
        "Experiment: With Mistral-7B, JGA increases from 0.73 to "
        + ("0.99." if wrong else "0.80."),
        ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source.url, quote)],
    )
    checked, _, _ = apply_anchor_resolution([claim], Artifact(source, text))
    assert checked[0].is_publishable() is (not wrong)


def test_a_true_table_still_rejects_a_value_from_another_methods_row():
    from research_radar.analysis.anchor_repair import apply_anchor_resolution
    from research_radar.models import (
        Artifact,
        Claim,
        ClaimStatus,
        EvidenceAnchor,
        SourceCandidate,
        SourceType,
    )

    text = "Table 3 Results\nMethod Accuracy Score\nMistral-7B 0.73 2.52\nMemGuide 0.80 1.21"
    source = SourceCandidate("Offline", "https://example.test/paper", SourceType.PAPER, "fixture")
    claim = Claim(
        "Experiment: Mistral-7B achieves accuracy 0.80.",
        ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source.url, text)],
    )
    checked, _, _ = apply_anchor_resolution([claim], Artifact(source, text))
    assert not checked[0].is_publishable()


def test_saved_memguide_narrative_resolution_does_not_require_a_numeric_method_row():
    from research_radar.analysis.anchor_repair import AnchorResolution, _table_anchor_row_failure
    from research_radar.models import Claim, ClaimStatus

    quote = (
        "when using Mistral-7B as the\nLLM Reader, MemGuide increases JGA from 0.73 to 0.80\n"
        "and reduces DTE from 2.52 to 1.21"
    )
    context = (
        "Table 4: Results of traditional TOD models, summary-based\n"
        "methods, and MemGuide. Models marked with ∗ focus on\n"
        "DST only. † indicates a simplified AutoTOD pipeline.\n"
        "outperforms FCP across all tested models, demonstrating ro-\n"
        "bust gains in task accuracy, response quality, and interac-\n"
        "tion efficiency. For example, " + quote
    )
    claim = Claim(
        "Experiment: With Mistral-7B as the reader, the authors report JGA increasing "
        "from 0.73 to 0.80 and DTE decreasing from 2.52 to 1.21.",
        ClaimStatus.SUPPORTED,
    )
    resolution = AnchorResolution(0, "", "matched", "exact", quote=quote, resolved_quote=context)
    assert _table_anchor_row_failure(claim, [resolution]) is None


@pytest.mark.parametrize(
    "line,expected",
    [
        ("LLM Reader, MemGuide increases JGA from 0.73 to 0.80", None),
        ("and reduces DTE from 2.52 to 1.21", None),
        ("Mistral-7B 0.73 2.52", ("Mistral-7B", ["0.73", "2.52"])),
        ("Method 0.73", ("Method", ["0.73"])),
    ],
)
def test_table_row_parser_cannot_backtrack_past_intervening_narrative(line, expected):
    from research_radar.evidence.tables import numeric_row

    assert numeric_row(line) == expected


def test_incomplete_final_schema_review_never_creates_public_chinese_output(tmp_path, monkeypatch):
    import sys

    class FinalFailure(Reviewing):
        def complete_with_schema(self, *args, **kwargs):
            if self.requests:
                self.bad = "missing"
            return super().complete_with_schema(*args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "Reviewing", FinalFailure)
    with pytest.raises(AnalysisError):
        execute(tmp_path, "memguide", monkeypatch)
    assert not list(tmp_path.rglob("paper.md"))
    assert not list(tmp_path.rglob("deep_reading.md"))
