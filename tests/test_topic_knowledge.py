"""Offline knowledge organization: source boundaries, references and atomic promotion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_radar.analysis.knowledge_inputs import build_knowledge_input
from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.topic_knowledge import KnowledgeError, validate_organization
from research_radar.application.topic_knowledge import (
    load_current_knowledge,
    organize_topic,
)
from research_radar.exceptions import AnalysisError, OperationCancelled
from research_radar.storage.paper_ledger import LedgerReport, build_paper_ledger


def report(root: Path, name: str, *, version: str = "v1", topic: str = "memory") -> LedgerReport:
    run = root / "runs" / name
    run.mkdir(parents=True)
    url = f"https://arxiv.org/abs/2601.01234{version}"
    entry = {
        "title": "Memory selection",
        "source": {"title": "Memory selection", "url": url, "version": version},
        "claims": [
            {
                "text": "The method selects memory under a fixed token budget.",
                "evidence": [
                    {"source_url": url, "quote": "We use a fixed budget.", "location": "Section 3"}
                ],
            }
        ],
        "reader_explanation": "Unverified prose must not become an input.",
    }
    draft = {
        "topic_id": topic,
        "sections": [{"metadata": {"kind": "deep_reads", "deep_reads": [entry]}}],
    }
    (run / "article_draft.json").write_text(json.dumps(draft), encoding="utf-8")
    (run / "wechat.html").write_text("<p>已有报告</p>", encoding="utf-8")
    return LedgerReport(name, "2026-10-28", run)


def change_entry(item: LedgerReport, update: dict) -> None:
    path = item.run_dir / "article_draft.json"
    draft = json.loads(path.read_text())
    draft["sections"][0]["metadata"]["deep_reads"][0].update(update)
    path.write_text(json.dumps(draft), encoding="utf-8")


def organization(materials: dict) -> dict:
    papers = materials["papers"]
    refs = materials["references"]
    output = {
        "facets": [{"id": "mechanism", "label": "Mechanism", "description": "Memory use"}],
        "papers": [],
        "groups": [],
        "relations": [],
        "synthesis": [
            {
                "text": "The supplied material describes budgeted selection.",
                "basis": "synthesis",
                "ref_ids": [refs[0]["ref_id"]],
            }
        ],
        "open_questions": [
            {
                "text": "Does selection preserve conflicting evidence?",
                "ref_ids": [refs[0]["ref_id"]],
            }
        ],
    }
    members = []
    for paper in papers:
        ids = paper["ref_ids"]
        output["papers"].append(
            {
                "paper_key": paper["paper_key"],
                "keywords": [{"label": "budget", "ref_ids": ids}],
                "features": [
                    {
                        "name": "Mechanism",
                        "value": "Budgeted selection",
                        "basis": "source_statement",
                        "ref_ids": ids,
                        "missing_reason": None,
                    }
                ],
            }
        )
        members.append(
            {
                "paper_key": paper["paper_key"],
                "reason": "Budget constrains selection.",
                "ref_ids": ids,
            }
        )
    output["groups"] = [
        {"facet_id": "mechanism", "label": "Budgeted selection", "members": members}
    ]
    return output


class OfflineProvider:
    name = "offline"

    def __init__(self, action=None) -> None:
        self.calls = 0
        self.action = action
        self.messages: list[Message] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.calls += 1
        self.messages = messages
        materials = json.loads(messages[1].content)
        result = organization(materials)
        if self.action:
            self.action(result)
        return ModelResponse(json.dumps(result), model, {"private_extra": "not persisted"})


def run(root: Path, reports: list[LedgerReport], provider=None, **kwargs):
    return organize_topic(
        root,
        "memory",
        reports,
        research_question="How is memory selected?",
        provider=provider or OfflineProvider(),
        model="offline-model",
        **kwargs,
    )


def test_input_uses_ledger_identity_versions_and_exact_source_provenance(tmp_path: Path) -> None:
    a, b, c = [
        report(tmp_path, name, version=version)
        for name, version in [("one", "v1"), ("two", "v1"), ("three", "v2")]
    ]
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    materials = build_knowledge_input(tmp_path, "memory", [c, b, a, a])
    assert len(materials.papers) == 2
    assert len(materials.references) == 3
    assert {p["paper_id"] for p in materials.papers} == {
        build_paper_ledger(tmp_path, "memory", [a])["papers"][0]["paper_id"]
    }
    assert sorted(p["version"] for p in materials.papers) == ["v1", "v2"]
    ref = materials.references[0]
    assert ref["json_pointer"] == "/sections/0/metadata/deep_reads/0/claims/0"
    assert ref["evidence"][0]["quote"] == "We use a fixed budget."
    assert "Unverified prose" not in json.dumps(materials.to_payload())
    assert str(tmp_path) not in json.dumps(materials.to_payload())
    assert materials.fingerprint == build_knowledge_input(tmp_path, "memory", [a, b, c]).fingerprint
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("mutation", ["topic", "missing", "outside", "symlink", "conflict"])
def test_invalid_requested_reports_fail_instead_of_silently_replacing_scope(
    tmp_path: Path,
    mutation: str,
) -> None:
    item = report(tmp_path, "one", topic="other" if mutation == "topic" else "memory")
    reports = [item]
    if mutation == "missing":
        reports = [LedgerReport("absent", "2026-10-28", tmp_path / "missing")]
    elif mutation == "outside":
        reports = [LedgerReport("outside", "2026-10-28", tmp_path.parent)]
    elif mutation == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(item.run_dir, target_is_directory=True)
        reports = [LedgerReport("alias", "2026-10-28", alias)]
    elif mutation == "conflict":
        reports.append(LedgerReport("one", "2026-10-27", item.run_dir))
    with pytest.raises(KnowledgeError):
        build_knowledge_input(tmp_path, "memory", reports)


@pytest.mark.parametrize("status", ["unsupported", "uncertain"])
def test_nonpublic_claim_is_not_promoted_and_empty_input_never_calls_provider(
    tmp_path: Path,
    status: str,
) -> None:
    item = report(tmp_path, "one")
    change_entry(item, {"claims": [{"text": "Rejected fact", "status": status, "evidence": []}]})
    provider = OfflineProvider()
    with pytest.raises(KnowledgeError, match="usable"):
        run(tmp_path, [item], provider)
    assert provider.calls == 0


def test_cross_paper_evidence_cannot_become_a_feature_input(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    change_entry(
        item,
        {
            "claims": [
                {
                    "text": "Fact",
                    "evidence": [
                        {
                            "source_url": "https://arxiv.org/abs/2601.99999v1",
                            "quote": "Other paper",
                            "location": "p. 1",
                        }
                    ],
                }
            ]
        },
    )
    with pytest.raises(KnowledgeError, match="evidence"):
        build_knowledge_input(tmp_path, "memory", [item])


def test_strict_output_accepts_multilabel_groups_and_explicit_unknown(tmp_path: Path) -> None:
    materials = build_knowledge_input(tmp_path, "memory", [report(tmp_path, "one")])
    data = organization(materials.to_payload())
    data["groups"].append({**data["groups"][0], "label": "Retrieval"})
    data["papers"][0]["features"].append(
        {
            "name": "Evaluation split",
            "value": None,
            "basis": "unknown",
            "ref_ids": [],
            "missing_reason": "The supplied public claims do not cover the split.",
        }
    )
    result = validate_organization(json.dumps(data), materials)
    assert len(result["groups"]) == 2
    assert result["papers"][0]["features"][1]["value"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_ref",
        "other_paper_ref",
        "unknown_field",
        "missing_paper",
        "duplicate_paper",
        "bad_basis",
        "empty_refs",
        "unknown_facet",
        "unknown_without_reason",
        "forged_metadata",
        "duplicate_json_key",
        "code_fence",
        "nonfinite",
    ],
)
def test_invalid_model_outputs_are_rejected(tmp_path: Path, mutation: str) -> None:
    materials = build_knowledge_input(
        tmp_path, "memory", [report(tmp_path, "one"), report(tmp_path, "two", version="v2")]
    )
    data = organization(materials.to_payload())
    feature = data["papers"][0]["features"][0]
    if mutation == "unknown_ref":
        feature["ref_ids"] = ["invented"]
    elif mutation == "other_paper_ref":
        feature["ref_ids"] = materials.papers[1]["ref_ids"]
    elif mutation == "unknown_field":
        feature["confidence"] = 0.99
    elif mutation == "missing_paper":
        data["papers"].pop()
    elif mutation == "duplicate_paper":
        data["papers"].append(data["papers"][0])
    elif mutation == "bad_basis":
        feature["basis"] = "verified"
    elif mutation == "empty_refs":
        feature["ref_ids"] = []
    elif mutation == "unknown_facet":
        data["groups"][0]["facet_id"] = "invented"
    elif mutation == "unknown_without_reason":
        feature.update(value=None, basis="unknown", ref_ids=[])
    elif mutation == "forged_metadata":
        data["provider"] = "trusted"
    content = json.dumps(data)
    if mutation == "duplicate_json_key":
        content = content.replace('"facets":', '"papers": [], "facets":', 1)
    elif mutation == "code_fence":
        content = "```json\n" + content + "\n```"
    elif mutation == "nonfinite":
        content = content.replace('"synthesis":', '"extra": NaN, "synthesis":', 1)
    with pytest.raises(KnowledgeError):
        validate_organization(content, materials)


@pytest.mark.parametrize("mutation", ["one_side", "self", "invented_kind"])
def test_relation_requires_both_papers_and_conservative_kind(tmp_path: Path, mutation: str) -> None:
    materials = build_knowledge_input(
        tmp_path, "memory", [report(tmp_path, "one"), report(tmp_path, "two", version="v2")]
    )
    data = organization(materials.to_payload())
    a, b = materials.papers
    data["relations"] = [
        {
            "source": a["paper_key"],
            "target": b["paper_key"],
            "kind": "shared_problem",
            "basis": "synthesis",
            "reason": "Both concern memory selection.",
            "ref_ids": a["ref_ids"] + b["ref_ids"],
        }
    ]
    if mutation == "one_side":
        data["relations"][0]["ref_ids"] = a["ref_ids"]
    elif mutation == "self":
        data["relations"][0]["target"] = a["paper_key"]
    else:
        data["relations"][0]["kind"] = "outperforms"
    with pytest.raises(KnowledgeError):
        validate_organization(json.dumps(data), materials)


def test_saved_snapshot_is_self_contained_private_and_leaves_reports_unchanged(
    tmp_path: Path,
) -> None:
    item = report(tmp_path, "one")
    before = {p: p.read_bytes() for p in item.run_dir.iterdir()}
    provider = OfflineProvider()
    result = run(tmp_path, [item], provider)
    current = load_current_knowledge(tmp_path, "memory")
    assert current == result.snapshot
    assert current["provider"] == "offline" and current["model"] == "offline-model"
    assert current["inputs"]["references"][0]["evidence"][0]["quote"] == "We use a fixed budget."
    assert current["organization"]["groups"][0]["members"]
    assert provider.calls == 1
    assert "private_extra" not in result.path.read_text()
    assert str(tmp_path) not in result.path.read_text()
    assert result.path.stat().st_mode & 0o777 == 0o600
    assert result.path.parent.stat().st_mode & 0o777 == 0o700
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("failure", ["provider", "bad_output", "cancel", "changed_input"])
def test_failed_organization_preserves_previous_current(tmp_path: Path, failure: str) -> None:
    item = report(tmp_path, "one")
    first = run(tmp_path, [item])
    stopped = False

    def action(data: dict) -> None:
        nonlocal stopped
        if failure == "provider":
            raise AnalysisError("Offline failure")
        if failure == "bad_output":
            data["papers"][0]["keywords"][0]["ref_ids"] = ["invented"]
        if failure == "cancel":
            stopped = True
        if failure == "changed_input":
            change_entry(item, {"title": "Changed while organizing"})

    with pytest.raises((KnowledgeError, AnalysisError, OperationCancelled)):
        run(tmp_path, [item], OfflineProvider(action), cancelled=lambda: stopped)
    assert load_current_knowledge(tmp_path, "memory") == first.snapshot


def test_cancellation_before_provider_does_not_start_a_call(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    provider = OfflineProvider()
    with pytest.raises(OperationCancelled):
        run(tmp_path, [item], provider, cancelled=lambda: True)
    assert provider.calls == 0


def test_corrupt_pointer_is_preserved_and_prevents_model_call(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    first = run(tmp_path, [item])
    pointer = first.path.parent.parent / "current.json"
    pointer.write_bytes(b"{broken")
    provider = OfflineProvider()
    with pytest.raises(KnowledgeError):
        run(tmp_path, [item], provider)
    assert pointer.read_bytes() == b"{broken" and provider.calls == 0


def test_symlinked_knowledge_root_is_not_written(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    item = report(workspace, "one")
    other = tmp_path / "other"
    other.mkdir()
    (workspace / "knowledge").symlink_to(other, target_is_directory=True)
    with pytest.raises(KnowledgeError):
        run(workspace, [item])
    assert list(other.iterdir()) == []


def test_pointer_write_failure_retains_previous_snapshot_and_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_radar.application import topic_knowledge

    item = report(tmp_path, "one")
    first = run(tmp_path, [item])
    pointer = first.path.parent.parent / "current.json"
    before = pointer.read_bytes()
    original_write = topic_knowledge.write_json

    def fail_pointer(path: Path, value: object, *, before_replace=None) -> None:
        if path == pointer:
            raise PermissionError("Offline pointer write denied")
        original_write(path, value, before_replace=before_replace)

    monkeypatch.setattr(topic_knowledge, "write_json", fail_pointer)
    with pytest.raises(PermissionError):
        run(tmp_path, [item])
    assert pointer.read_bytes() == before
    assert load_current_knowledge(tmp_path, "memory") == first.snapshot
    assert len(list(first.path.parent.glob("*.json"))) == 2


def test_cancel_after_snapshot_write_does_not_promote_it(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    first = run(tmp_path, [item])
    with pytest.raises(OperationCancelled):
        run(tmp_path, [item], cancelled=lambda: len(list(first.path.parent.glob("*.json"))) > 1)
    assert load_current_knowledge(tmp_path, "memory") == first.snapshot
    assert len(list(first.path.parent.glob("*.json"))) == 2


def test_overlapping_same_topic_is_rejected_and_lock_released_after_failure(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    nested = OfflineProvider()

    def overlap(data: dict) -> None:
        run(tmp_path, [item], nested)

    with pytest.raises(KnowledgeError, match="already running"):
        run(tmp_path, [item], OfflineProvider(overlap))
    assert nested.calls == 0
    assert run(tmp_path, [item]).snapshot == load_current_knowledge(tmp_path, "memory")


def test_same_family_mirror_merges_but_query_identified_papers_do_not(tmp_path: Path) -> None:
    a, b = report(tmp_path, "one"), report(tmp_path, "two")
    change_entry(b, {"source": {"url": "https://arxiv.org/pdf/2601.01234v1"}})
    materials = build_knowledge_input(tmp_path, "memory", [a, b])
    assert len(materials.papers) == 1 and len(materials.references) == 2
    for item, query in [(a, "first"), (b, "second")]:
        url = f"https://openreview.net/forum?id={query}"
        change_entry(
            item,
            {
                "source": {"url": url},
                "claims": [
                    {
                        "text": "Public claim",
                        "evidence": [{"source_url": url, "quote": "Original", "location": "p. 2"}],
                    }
                ],
            },
        )
    materials = build_knowledge_input(tmp_path, "memory", [a, b])
    assert len(materials.papers) == 2
    assert {p["version"] for p in materials.papers} == {None}


def test_response_may_leave_papers_ungrouped_without_forced_edges(tmp_path: Path) -> None:
    materials = build_knowledge_input(tmp_path, "memory", [report(tmp_path, "one")])
    data = organization(materials.to_payload())
    data.update(facets=[], groups=[], relations=[], synthesis=[], open_questions=[])
    assert validate_organization(json.dumps(data), materials)["relations"] == []


def test_successive_operations_keep_independent_snapshots_and_topics(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    other = report(tmp_path, "other", topic="other")
    first, second = run(tmp_path, [item]), run(tmp_path, [item])
    result = organize_topic(
        tmp_path,
        "other",
        [other],
        research_question="Other question?",
        provider=OfflineProvider(),
        model="other-model",
        language="en",
    )
    assert first.path != second.path and first.path.exists()
    assert load_current_knowledge(tmp_path, "memory") == second.snapshot
    assert load_current_knowledge(tmp_path, "other") == result.snapshot
    assert load_current_knowledge(tmp_path, "absent") is None


def test_title_only_sources_do_not_generate_analyzed_papers(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    path = item.run_dir / "article_draft.json"
    data = json.loads(path.read_text())
    data["sections"].append(
        {
            "metadata": {
                "kind": "new_updated_sources",
                "sources": [
                    {
                        "title": "Unopened paper",
                        "url": "https://arxiv.org/abs/2601.99999v1",
                    }
                ],
            }
        }
    )
    path.write_text(json.dumps(data))
    materials = build_knowledge_input(tmp_path, "memory", [item])
    assert len(materials.papers) == 1
    assert all("Unopened" not in p["title"] for p in materials.papers)


def test_input_size_limit_fails_before_model_without_truncating_material(tmp_path: Path) -> None:
    item = report(tmp_path, "one")
    change_entry(
        item,
        {
            "claims": [
                {
                    "text": "Existing claim" * 50_000,
                    "evidence": [
                        {
                            "source_url": "https://arxiv.org/abs/2601.01234v1",
                            "quote": "Original",
                            "location": "p. 1",
                        }
                    ],
                }
            ]
        },
    )
    provider = OfflineProvider()
    with pytest.raises(KnowledgeError, match="size"):
        run(tmp_path, [item], provider)
    assert provider.calls == 0


def test_model_settings_are_recorded_without_extra_diagnostics(tmp_path: Path) -> None:
    item = report(tmp_path, "one")

    class ConfiguredOfflineProvider(OfflineProvider):
        def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
            response = super().complete(messages, model=model)
            return ModelResponse(
                response.content,
                "resolved-model",
                {
                    "thinking": "enabled",
                    "reasoning_effort": "xhigh",
                    "private": "not retained",
                },
            )

    result = run(tmp_path, [item], ConfiguredOfflineProvider())
    assert result.snapshot["model"] == "resolved-model"
    assert result.snapshot["requested_model"] == "offline-model"
    assert result.snapshot["inference_settings"] == {
        "thinking": "enabled",
        "reasoning_effort": "xhigh",
    }
    assert "not retained" not in result.path.read_text()


@pytest.mark.parametrize("change", ["cancel", "source"])
def test_pointer_staging_cannot_skip_final_cancel_and_freshness_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    item = report(tmp_path, "one")
    first = run(tmp_path, [item])
    pointer = first.path.parent.parent / "current.json"
    before = pointer.read_bytes()
    stopped = False
    original_write = Path.write_text

    def change_after_staging(path: Path, data: str, *args, **kwargs) -> int:
        nonlocal stopped
        result = original_write(path, data, *args, **kwargs)
        if path == pointer.with_suffix(".json.tmp"):
            if change == "cancel":
                stopped = True
            else:
                change_entry(item, {"title": "Source changed while pointer was staged"})
        return result

    monkeypatch.setattr(Path, "write_text", change_after_staging)
    with pytest.raises((KnowledgeError, OperationCancelled)):
        run(tmp_path, [item], cancelled=lambda: stopped)
    assert pointer.read_bytes() == before
    assert load_current_knowledge(tmp_path, "memory") == first.snapshot
