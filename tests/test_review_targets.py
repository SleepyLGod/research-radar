"""A schema-capable reviewer fills a source-bound finite checklist, not free-form indexes."""

import copy
import json
from dataclasses import replace

import pytest
from test_publication_composition import candidates

from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.reader_input import ReaderContextBudget
from research_radar.analysis.review import review_publication_facts
from research_radar.exceptions import AnalysisError


class SchemaReviewer:
    """Explicit editorial decisions, never an adapter for real or unidentified responses."""

    name = "offline-schema"
    supports_response_schema = True
    reader_contexts = {"offline": ReaderContextBudget(1000000, 32768, 8192)}

    def __init__(self, bad: str = "") -> None:
        self.bad = bad
        self.requests = []

    def complete(self, *_args, **_kwargs):
        raise AssertionError("Schema review must not fall back to an unconstrained request")

    def complete_with_schema(self, messages, *, model, response_schema):
        content = messages[-1].content
        manifest = json.loads(content.split("REVIEW TARGETS (JSON):\n")[1])
        if "SHARED SOURCE RECORDS (JSON):\n" in content:
            from test_review_presentation import expand_presentation

            records = json.loads(content.split("SHARED SOURCE RECORDS (JSON):\n")[1].split(
                "\nFULL SOURCE CONTEXT (JSON):\n")[0])
            context = json.loads(content.split("FULL SOURCE CONTEXT (JSON):\n")[1].split(
                "\nREVIEW TARGETS (JSON):\n")[0])
            manifest = expand_presentation({"source_records": records, "source_context": context,
                                            "targets": manifest})["targets"]
        self.requests.append((messages, response_schema, manifest))
        keys = set(manifest)
        decisions_schema = response_schema["properties"]["decisions"]
        assert set(decisions_schema["properties"]) == set(decisions_schema["required"]) == keys
        assert decisions_schema["additionalProperties"] is False
        response = {
            key: {"status": "supported", "reason": "Offline source-bound control."}
            for key in manifest
        }
        for key, target in manifest.items():
            if "direct_evidence" in target:
                shape = decisions_schema["properties"][key]["properties"]
                if "evidence_refs" in shape:
                    response[key]["evidence_refs"] = shape["evidence_refs"]["items"].get("enum", [])
                else:
                    response[key]["evidence_selection"] = dict.fromkeys(
                        target["direct_evidence"], True)
            if target["kind"] == "paragraph":
                response[key]["covered_claim_ids"] = target["supporting_claim_ids"]
            shape = decisions_schema["properties"][key]["properties"]
            if "comparison_checks" in shape:
                response[key]["comparison_checks"] = {ref: item.get("enum") != [False]
                    for ref, item in shape["comparison_checks"]["properties"].items()}
                if not all(response[key]["comparison_checks"].values()):
                    response[key]["status"] = "needs_review"
        if self.bad == "missing":
            response.pop(next(reversed(response)))
        elif self.bad == "unknown":
            response["not-a-target"] = response.pop(next(iter(response)))
        elif self.bad == "state":
            response[next(iter(response))]["status"] = "maybe"
        elif self.bad == "reason":
            response[next(iter(response))]["reason"] = " "
        elif self.bad == "extra":
            response[next(iter(response))]["claim_index"] = 1
        elif self.bad == "duplicate":
            key = next(iter(response))
            row = json.dumps(response[key])
            return ModelResponse(
                '{"decisions":{'
                + json.dumps(key)
                + ":"
                + row
                + ","
                + json.dumps(key)
                + ":"
                + row
                + "}}",
                model,
            )
        return ModelResponse(json.dumps({"decisions": response}), model)


def test_shared_fact_review_uses_exact_required_targets_and_preserves_raw_reply():
    reading, claim = candidates()
    from research_radar.models import Artifact, SourceCandidate, SourceType

    source = SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "fixture")
    provider = SchemaReviewer()
    result = review_publication_facts(
        [claim],
        provider,
        model="offline",
        readings=[reading],
        artifacts=[Artifact(source, claim.evidence[0].quote)],
    )
    assert result.claims[0].metadata["fact_review"]["status"] == "supported"
    assert len(provider.requests) == 1
    payload = json.loads(result.raw_feedback)
    assert json.loads(payload["structured_review"]["raw_response"])["decisions"]


@pytest.mark.parametrize("bad", ["missing", "unknown", "state", "reason", "extra", "duplicate"])
def test_invalid_schema_reply_never_authorizes_facts_or_issues_another_request(bad):
    from research_radar.models import Artifact, SourceCandidate, SourceType

    reading, claim = candidates()
    source = SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "fixture")
    provider = SchemaReviewer(bad)
    with pytest.raises(AnalysisError, match="review|Review"):
        review_publication_facts(
            [claim],
            provider,
            model="offline",
            readings=[reading],
            artifacts=[Artifact(source, claim.evidence[0].quote)],
        )
    assert len(provider.requests) == 1
    assert "fact_review" not in claim.metadata


def test_target_identity_binds_source_assertion_and_evidence_not_list_position():
    from research_radar.analysis.review_targets import build_review_targets

    reading, claim = candidates()
    contract = build_review_targets([claim], "")
    changed = replace(claim, text=claim.text + " Different qualifier.")
    assert contract.targets.keys() != build_review_targets([changed], "").targets.keys()
    foreign = replace(claim, evidence=[replace(claim.evidence[0], source_url="https://other.test")])
    assert contract.targets.keys() != build_review_targets([foreign], "").targets.keys()
    assert contract.targets == copy.deepcopy(contract.targets)


def test_original_actual_47_decisions_cannot_be_reinterpreted_as_a_complete_manifest():
    from pathlib import Path

    from research_radar.analysis.review_targets import build_review_targets

    path = Path(__file__).parent / "fixtures/method_flow/incomplete_fact_review.json"
    saved = json.loads(path.read_text())
    reading, claim = candidates()
    claims = [
        replace(
            claim, text=item["text"], metadata={"paper_reading": {"claim_id": item["claim_id"]}}
        )
        for item in saved["requested_facts"]
    ]
    contract = build_review_targets(claims, "")
    assert len(contract.targets) == 48
    with pytest.raises(AnalysisError):
        contract.normalize(saved["raw_response"])


@pytest.mark.parametrize("bad", ["missing", "duplicate", "unknown"])
def test_invalid_constrained_review_never_enters_model_cache(tmp_path, bad):
    from research_radar.analysis.model_cache import CachedLLMProvider

    reading, claim = candidates()
    from research_radar.models import Artifact, SourceCandidate, SourceType

    source = SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "fixture")
    provider = SchemaReviewer(bad)
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="review")
    with pytest.raises(AnalysisError):
        review_publication_facts(
            [claim],
            cached,
            model="offline",
            readings=[reading],
            artifacts=[Artifact(source, claim.evidence[0].quote)],
        )
    assert not list(tmp_path.glob("*.json"))
    assert len(provider.requests) == 1


def test_valid_review_cache_is_bound_to_exact_target_set(tmp_path):
    from research_radar.analysis.model_cache import CachedLLMProvider
    from research_radar.models import Artifact, SourceCandidate, SourceType

    reading, claim = candidates()
    source = SourceCandidate("Offline", reading.source_url, SourceType.PAPER, "fixture")
    provider = SchemaReviewer()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, task_name="review")
    for candidate in (claim, claim, replace(claim, text=claim.text + " Same setup.")):
        review_publication_facts(
            [candidate],
            cached,
            model="offline",
            readings=[reading],
            artifacts=[Artifact(source, claim.evidence[0].quote)],
        )
    assert len(provider.requests) == 2 and cached.hit_count == 1


def test_48_required_targets_cannot_be_completed_by_47_editorial_decisions():
    from pathlib import Path

    from research_radar.analysis.review_targets import build_review_targets

    saved = json.loads(
        (Path(__file__).parent / "fixtures/method_flow/incomplete_fact_review.json").read_text()
    )
    _, base = candidates()
    claims = [
        replace(base, text=item["text"], metadata={"paper_reading": {"claim_id": item["claim_id"]}})
        for item in saved["requested_facts"]
    ]
    contract = build_review_targets(claims, "")
    decisions = {
        key: {"status": "supported", "reason": "Explicit offline control."}
        for key in contract.targets
    }
    last = next(reversed(decisions))
    decisions.pop(last)
    with pytest.raises(AnalysisError) as error:
        contract.normalize(json.dumps({"decisions": decisions}))
    assert error.value.diagnostics["missing"] == [last]


def test_same_local_claim_id_in_two_papers_is_two_distinct_targets():
    from research_radar.analysis.review_targets import build_review_targets

    _, claim = candidates()
    foreign = replace(claim, evidence=[replace(claim.evidence[0], source_url="https://other.test")])
    left = build_review_targets([claim, foreign], "")
    right = build_review_targets([foreign, claim], "")
    assert len(left.targets) == 2 and left.targets.keys() == right.targets.keys()


def test_explicit_fact_recheck_does_not_skip_previously_approved_method_targets():
    from method_contract_controls import control

    from research_radar.analysis.anchor_repair import apply_anchor_repair
    from research_radar.analysis.method_flow import reviewed_method_flow
    from research_radar.analysis.paper_reading import parse_paper_reading, validate_paper_reading

    artifact, response, _ = control("memguide")
    reading = parse_paper_reading(json.dumps(response), artifact)
    claims, _ = validate_paper_reading(reading, artifact, include_context_claims=True)
    claims, _, _, _ = apply_anchor_repair(claims, artifact, None, model=None)
    provider = SchemaReviewer()
    first = review_publication_facts(claims, provider, model="offline", readings=[reading],
                                     artifacts=[artifact])
    second = review_publication_facts(first.claims, provider, model="offline",
                                      readings=first.readings, artifacts=[artifact])
    for request in provider.requests:
        assert sum(t["kind"] == "operation" for t in request[2].values()) == 3
        assert sum(t["kind"] == "link" for t in request[2].values()) == 2
    assert reviewed_method_flow(second.readings[0].method_flow, second.claims,
                                source_url=artifact.source.url)
