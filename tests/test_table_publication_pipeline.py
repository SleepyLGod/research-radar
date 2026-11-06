"""Saved paper excerpts reach Chinese prose through explicit offline editorial decisions."""

import copy
import hashlib
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from method_contract_controls import control
from test_method_contract_pipeline import Reading, Reviewing
from test_positioned_tables import DATA

from research_radar.analysis.figures import PdfPageBbox, PdfTextWord
from research_radar.analysis.providers import ModelResponse
from research_radar.config import parse_config
from research_radar.pipeline import paper
from research_radar.security.secrets import KeychainSecretBackend


def publication_input(name: str, *, compound: bool = False):
    """Hand-checked table assertions supplement the existing method/condition controls."""
    artifact, response, chinese = control(name)
    case = copy.deepcopy(next(c for c in DATA["cases"]
                              if c["name"] == ("conflict3" if name == "memconflict" else "guide3")))
    artifact = replace(artifact, text=artifact.text + "\n\n" + case["text"])
    if name == "memconflict":
        quote = case["text"].split("AA UOCS AA CRS AA AA\n")[1]
        extra = [
            ("MemOS reports Static AA of 0.4375.", "MemOS 的 Static AA 为 0.4375。"),
            ("MemOS reports Conditional AA of 0.8449.", "MemOS 的 Conditional AA 为 0.8449。"),
        ]
        paragraph = (
            "在默认配置的 Table 3 中，MemOS 的 Static AA 为 0.4375，Conditional AA 为 0.8449。"
            "这些数值分别对应两类冲突，不能把其中一项扩展成所有指标上的整体优势。"
        )
    else:
        quote = case["text"][case["text"].index("Mistral-7B FCP"):
                             case["text"].index("GPT-4o-mini FCP")]
        extra = [
            ("Under Mistral-7B, MemGuide reports JGA of 0.80.",
             "在 Mistral-7B 设置下，MemGuide 的 JGA 为 0.80。"),
            ("Under Mistral-7B, MemGuide reports DTE of 1.21.",
             "在 Mistral-7B 设置下，MemGuide 的 DTE 为 1.21。"),
        ]
        paragraph = (
            "实验使用 MS-TOD 中带有确认型回复标注的会话。Table 3 的 Mistral-7B 设置下，"
            "作者报告 MemGuide 的 JGA 从 0.73 升至 0.80，DTE 从 2.52 降至 1.21。"
            "这组数值对应该模型、方法与任务设置，不是所有模型的统一结果。"
        )
    ids = []
    for i, (english, translated) in enumerate(extra):
        identity = f"table-fact-{i}"
        ids.append(identity)
        response["deep_readings"]["claim_units"].append({
            "claim_id": identity, "section": "experiment", "claim_kind": "fact",
            "text": english, "evidence": [{"quote": quote}], "publishable_default": True,
            "method": None,
        })
        chinese["claims"].append({"claim_id": identity, "text": "Experiment: " + translated})
    if compound:
        assert name == "memguide"
        response["deep_readings"]["claim_units"][-2]["text"] = (
            "Under Mistral-7B, MemGuide reports JGA 0.80 and DTE 1.21.")
        chinese["claims"][-2]["text"] = (
            "Experiment: 在 Mistral-7B 设置下，MemGuide 的 JGA 为 0.80，DTE 为 1.21。")
    return artifact, response, chinese, case, {
        "text": paragraph,
        "supporting_claim_ids": ids + (["e1", "e2"] if name == "memguide" else []),
    }


class EditorialWriting:
    """Return declared Chinese prose, never a simulated claim of new model quality."""

    name = "offline-editorial-control"
    reader_contexts = Reading.reader_contexts

    def __init__(self, chinese: dict, paragraph: dict, order: list[str]) -> None:
        self.chinese, self.paragraph, self.order = chinese, paragraph, order
        self.inputs: list[dict] = []

    def complete(self, messages, *, model):
        payload = json.loads(messages[-1].content.split("FACT-REVIEWED CANDIDATES (JSON):\n")[1])
        self.inputs.append(payload)
        self.order.append("writer")
        expected = {c["claim_id"] for c in payload["candidate_facts"]}
        result = copy.deepcopy(self.chinese)
        result["claims"] = [c for c in result["claims"] if c["claim_id"] in expected]
        if set(self.paragraph["supporting_claim_ids"]) <= expected:
            if self.paragraph["supporting_claim_ids"][-2:] == ["e1", "e2"]:
                result["reader_explanation"]["experiment_interpretation"] = [self.paragraph]
            else:
                result["reader_explanation"]["experiment_interpretation"].append(self.paragraph)
        return ModelResponse(json.dumps(result, ensure_ascii=False), model)


def run_control(
    root: Path, name: str, geometry: bool, monkeypatch, *, artifact=None, page_reader=None,
    compound: bool = False,
):
    """Run the production single-paper path with only ingestion/model boundaries replaced."""
    from research_radar.analysis import figures

    original, response, chinese, case, paragraph = publication_input(name, compound=compound)
    if artifact is None:
        pdf = root / "public-original.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"offline-source-document-identity")
        artifact = replace(original, artifact_path=str(pdf), content_type="application/pdf")
    else:
        artifact = replace(artifact, source=replace(artifact.source, score=1))
    bbox = case["bbox"]
    positioned = PdfPageBbox(bbox["width"], bbox["height"],
                            [PdfTextWord(**w) for w in bbox["words"]])
    actual_reader = page_reader or (
        lambda _path, page: positioned if page == case["physical_page"] else None
    )
    monkeypatch.setattr(figures, "read_pdf_page_bbox",
                        actual_reader if geometry else lambda *_: None)
    monkeypatch.setattr(paper, "ingest_source", lambda *_: artifact)
    order = []
    reviewing = Reviewing(order)
    writing = EditorialWriting(chinese, paragraph, order)
    config = parse_config({"topics": [{"id": "memory", "queries": ["agent memory"]}]})
    result = paper.run_paper(root, config, "memory", artifact.source.url,
        Reading(response, order), model="offline", verifier=reviewing, verifier_model="offline",
        localizer=writing, localization_model="offline", language="zh")
    return result, reviewing, writing, order


@pytest.mark.parametrize("name", ["memconflict", "memguide"])
def test_table_input_and_target_review_reach_final_chinese_report(name, tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No service or credential access is allowed in this replay")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)
    before, _, before_writer, before_order = run_control(
        tmp_path / "before", name, False, monkeypatch,
    )
    after, reviewer, writer, order = run_control(tmp_path / "after", name, True, monkeypatch)
    assert before_order == order == ["reader", "review", "writer", "review"]
    assert not any(c["claim_id"].startswith("table-fact-")
                   for c in before_writer.inputs[0]["candidate_facts"])
    assert {c["claim_id"] for c in writer.inputs[0]["candidate_facts"] if c["source_bindings"]} >= {
        "table-fact-0", "table-fact-1",
    }
    body = (after / "paper.md").read_text().split("## 证据链")[0]
    assert "## 方法与机制" in body and "## 实验与评估" in body and "## 局限与未来工作" in body
    assert "0.4375" in body if name == "memconflict" else "Mistral-7B" in body
    assert "table-fact-" not in body
    raw = json.loads((after / "fact_review.json").read_text())
    raw_decisions = json.loads(raw["structured_review"]["raw_response"])["decisions"]
    assert all("evidence_refs" in row for row in raw_decisions.values())
    context = json.loads(reviewer.requests[0][0][-1].content.split(
        "FULL SOURCE CONTEXT (JSON):\n")[1].split("\nREVIEW TARGETS")[0])
    assert context["table_sources"]
    assert before != after
    assert hashlib.sha256((before / "paper.md").read_bytes()).hexdigest() != hashlib.sha256(
        (after / "paper.md").read_bytes()).hexdigest()


def test_pending_compound_result_reaches_chinese_only_after_exact_target_review(
    tmp_path, monkeypatch,
):
    run, reviewer, writer, order = run_control(tmp_path, "memguide", True, monkeypatch,
                                               compound=True)
    assert order == ["reader", "review", "writer", "review"]
    claims = [json.loads(line) for line in (run / "fact_claims.jsonl").read_text().splitlines()]
    fact, = [c for c in claims if c["metadata"]["paper_reading"]["claim_id"] == "table-fact-0"]
    assert fact["metadata"]["fact_review_admission"]["code"] == "table_semantics"
    assert fact["metadata"]["fact_review"]["status"] == "supported"
    assert "0.80" in (run / "paper.md").read_text()
    assert "1.21" in (run / "paper.md").read_text()
    assert len(reviewer.requests) == 2 and writer.inputs
