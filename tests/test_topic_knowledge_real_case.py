"""Offline replay of a distilled real case, not a model-quality evaluation."""

from __future__ import annotations

import hashlib
import json
import socket
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from research_radar.analysis.knowledge_inputs import (
    KnowledgeInput,
    build_knowledge_input,
    fingerprint,
)
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.topic_knowledge import KnowledgeError
from research_radar.app_bridge.knowledge_projection import project_knowledge
from research_radar.application.topic_knowledge import load_current_knowledge, organize_topic
from research_radar.security.secrets import KeychainSecretBackend
from research_radar.storage.paper_ledger import LedgerReport


@dataclass(frozen=True)
class RealCase:
    materials: KnowledgeInput
    reports: list[LedgerReport]
    question: str
    observed: dict[str, Any]
    replay: dict[str, Any]


@pytest.fixture(autouse=True)
def forbid_live_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("This regression must not access network or credentials")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "set_secret", forbidden)


@pytest.fixture
def real_case(tmp_path: Path) -> RealCase:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/topic_knowledge_real_case.json").read_text()
    )
    saved = fixture["materials"]
    run = tmp_path / "runs/saved-report"
    run.mkdir(parents=True)
    entries = []
    for paper in saved["papers"]:
        entries.append(
            {
                "title": paper["title"],
                "source": {"url": paper["source_urls"][0], "version": paper["version"]},
                "claims": [
                    {"text": ref["text"], "evidence": ref["evidence"]}
                    for ref in saved["references"]
                    if ref["paper_key"] == paper["paper_key"]
                ],
            }
        )
    draft = {
        "topic_id": saved["topic_id"],
        "sections": [
            {
                "metadata": {
                    "kind": "deep_reads",
                    "deep_reads": entries,
                }
            }
        ],
    }
    (run / "article_draft.json").write_text(json.dumps(draft, ensure_ascii=False))
    (run / "wechat.html").write_text('<meta charset="utf-8"><p>Saved public material</p>')
    reports = [LedgerReport("real-case-excerpt", "2026-10-24", run)]
    materials = build_knowledge_input(tmp_path, saved["topic_id"], reports)
    current_ids = {(r["paper_key"], r["text"]): r["ref_id"] for r in materials.references}
    ids = {r["ref_id"]: current_ids[(r["paper_key"], r["text"])] for r in saved["references"]}

    def remap(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: [ids[r] for r in v] if k == "ref_ids" else remap(v) for k, v in value.items()
            }
        if isinstance(value, list):
            return [remap(v) for v in value]
        return value

    return RealCase(
        materials,
        reports,
        fixture["research_question"],
        remap(fixture["observed_organization"]),
        remap(fixture["reviewed_replay"]),
    )


class ReplayProvider:
    """Replace only model execution with an explicitly hand-edited response."""

    name = "offline-replay"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.request: dict[str, Any] | None = None

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        assert self.request is None, "One operation must not add another model stage"
        self.request = json.loads(messages[1].content)
        return ModelResponse(json.dumps(self.response, ensure_ascii=False), model)


def legacy_snapshot(root: Path, case: RealCase) -> tuple[Path, Path]:
    """Create a v1-shaped historical excerpt with the original weak edges intact."""
    topic_id = case.materials.topic_id
    folder = root / "knowledge" / hashlib.sha256(topic_id.encode()).hexdigest()
    path = folder / "snapshots/00000000000000000000000000000001.json"
    path.parent.mkdir(parents=True)
    snapshot = {
        "schema_version": 1,
        "snapshot_id": path.stem,
        "created_at": "2026-10-29T06:41:21+00:00",
        "topic_id": topic_id,
        "research_question": case.question,
        "language": "zh",
        "prompt_version": "topic-knowledge:1",
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "model": "deepseek-flash",
        "inference_settings": {"thinking": "enabled", "reasoning_effort": "high"},
        "input_fingerprint": case.materials.fingerprint,
        "facet_fingerprint": fingerprint(case.observed["facets"]),
        "inputs": case.materials.to_payload(),
        "organization": case.observed,
    }
    path.write_text(json.dumps(snapshot, ensure_ascii=False))
    pointer = folder / "current.json"
    pointer.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_id": path.stem,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    )
    return path, pointer


def organize(root: Path, case: RealCase, provider: ReplayProvider) -> Any:
    return organize_topic(
        root,
        case.materials.topic_id,
        case.reports,
        research_question=case.question,
        provider=provider,
        model="offline-replay",
        language="zh",
    )


def test_prompt_revision_is_auditable_without_rewriting_the_historical_case(
    tmp_path: Path,
    real_case: RealCase,
) -> None:
    old_path, _ = legacy_snapshot(tmp_path, real_case)
    before = old_path.read_bytes()
    old = load_current_knowledge(tmp_path, real_case.materials.topic_id)
    assert old is not None
    result = organize(tmp_path, real_case, ReplayProvider(real_case.replay))
    assert result.snapshot["prompt_version"] != old["prompt_version"]
    assert result.snapshot["inputs"] == old["inputs"]
    assert result.path != old_path and old_path.read_bytes() == before
    assert json.loads(old_path.read_text())["organization"] == real_case.observed


def test_historical_empty_facets_and_weak_relations_remain_readable_for_comparison(
    tmp_path: Path,
    real_case: RealCase,
) -> None:
    path, pointer = legacy_snapshot(tmp_path, real_case)
    before = (path.read_bytes(), pointer.read_bytes())
    loaded = load_current_knowledge(tmp_path, real_case.materials.topic_id)
    assert loaded is not None
    graph = project_knowledge(real_case.materials.topic_id, loaded)["graph"]
    populated = {g["facet_id"] for g in graph["groups"]}
    assert {f["id"] for f in graph["facets"]} - populated == {
        "memory_mechanism",
        "assumption_scope",
        "comparability_boundary",
    }
    assert {r["kind"] for r in graph["relations"]} == {
        "shared_problem",
        "related_mechanism",
        "different_assumption",
        "shared_evaluation",
    }
    assert (path.read_bytes(), pointer.read_bytes()) == before


def test_reviewed_offline_replay_preserves_evidence_through_service_and_projection(
    tmp_path: Path,
    real_case: RealCase,
) -> None:
    provider = ReplayProvider(real_case.replay)
    before = {p: p.read_bytes() for p in real_case.reports[0].run_dir.iterdir()}
    result = organize(tmp_path, real_case, provider)
    graph = project_knowledge(real_case.materials.topic_id, result.snapshot)["graph"]
    assert graph["research_question"] == real_case.question
    assert provider.request is not None
    assert len(provider.request["references"]) == 34
    assert provider.request["language"] == "zh"
    assert str(tmp_path) not in json.dumps(provider.request)
    assert {p["title"] for p in graph["papers"]} == {
        "MemConflict: Evaluating Long-Term Memory Systems Under Memory Conflicts",
        "MemGuide: Intent-Driven Memory Selection for Goal-Oriented Multi-Session LLM Agents",
    }
    assert {r["kind"] for r in graph["relations"]} == {"shared_problem", "related_mechanism"}
    assert {f["id"] for f in graph["facets"]} == {g["facet_id"] for g in graph["groups"]}
    refs = {r["ref_id"]: r for r in graph["references"]}
    member = next(g for g in graph["groups"] if g["label"] == "Diagnostic benchmark")["members"][0]
    protocol = next(refs[r] for r in member["ref_ids"] if "两级评估协议" in refs[r]["text"])
    assert protocol["evidence"][0]["quote"] == (
        "two-level evaluation protocol that combines black-box answer assessment with white-box "
        "memory analysis, separating final-answer correctness from retrieval and ranking of the "
        "gold memory item."
    )
    for relation in graph["relations"]:
        assert {refs[r]["paper_key"] for r in relation["ref_ids"]} == {
            relation["source"],
            relation["target"],
        }
    assert load_current_knowledge(tmp_path, real_case.materials.topic_id) == result.snapshot
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("mutation", ["invented_ref", "one_sided_relation", "other_paper_member"])
def test_real_case_bad_references_cannot_replace_the_previous_snapshot(
    tmp_path: Path,
    real_case: RealCase,
    mutation: str,
) -> None:
    path, pointer = legacy_snapshot(tmp_path, real_case)
    before = (path.read_bytes(), pointer.read_bytes())
    response = deepcopy(real_case.replay)
    relation = response["relations"][0]
    if mutation == "invented_ref":
        relation["ref_ids"] = ["invented"]
    elif mutation == "one_sided_relation":
        relation["ref_ids"] = next(
            p["ref_ids"] for p in real_case.materials.papers if p["paper_key"] == relation["source"]
        )
    else:
        member = response["groups"][0]["members"][0]
        member["ref_ids"] = next(
            p["ref_ids"]
            for p in real_case.materials.papers
            if p["paper_key"] != member["paper_key"]
        )
    with pytest.raises(KnowledgeError):
        organize(tmp_path, real_case, ReplayProvider(response))
    assert (path.read_bytes(), pointer.read_bytes()) == before
