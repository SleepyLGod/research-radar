"""Experimental proposals bind literal cells and exact assertions, never approval."""

import copy
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from reader_fixtures import current_source_anchors
from test_experimental_results_contract import fixture
from test_method_review_catalog import BoundaryReviewer, score_reading
from test_saved_memguide_evidence import DATA, resolved_table, saved_pdf

from research_radar.analysis.experimental_results import (
    bind_experimental_results,
    parse_experimental_results,
)
from research_radar.analysis.paper_reading import parse_paper_reading
from research_radar.analysis.reading_review import build_reading_review_context
from research_radar.analysis.review import fact_is_reviewed, review_publication_facts
from research_radar.analysis.review_targets import build_review_targets
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, ClaimStatus, dataclass_to_dict
from research_radar.security.secrets import KeychainSecretBackend


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("Experimental bindings must not use network or credentials")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


def saved_result(tmp_path: Path) -> tuple:
    """Retain r22/c51, but address their exact unchanged blocks in this excerpt fixture."""
    artifact = saved_pdf(tmp_path)
    case = next(c for c in DATA["claims"] if c["claim_id"] == "c51")
    claim = Claim(case["text"], ClaimStatus.UNSUPPORTED,
        evidence=current_source_anchors(artifact, case["evidence"]),
        metadata={"paper_reading": {"claim_id": "c51", "source": "claim_units"}})
    result = parse_experimental_results([{
        "result_id": "r22", "question": (
            "What JGA values are reported for the single-session MemGuide* variant?"),
        "conditions": ["MemGuide* is the single-session variant that disables missing-slot "
                       "filtering while retaining QA memory.",
                       "The values are JGA, not multi-session task-success rates."],
        "metric": "JGA", "observations": [
            {"subject": "MemGuide* on SGD", "value": "0.846"},
            {"subject": "MemGuide* on MultiWOZ 2.2", "value": "0.879"}],
        "comparison_scope": ["Single-session DST results for SGD and MultiWOZ 2.2"],
        "uncertainty": ["The supplied table extraction presents the baseline rows but does not "
                        "provide a positioned grid binding; this record reports only the "
                        "explicitly named MemGuide* values."],
        "supporting_claim_ids": ["c51"], "source_kind": "table", "source_label": "Table 5",
        "physical_page": 6, "binding_status": "text_bound",
        "evidence": [{"quote": e.quote, "location": e.location or "Table 5"}
                     for e in claim.evidence],
    }], artifact, claim_ids={"c51"})[0]
    return artifact, result, claim


def test_saved_atomic_observations_bind_both_datasets_without_promoting_claim(
    tmp_path: Path,
) -> None:
    artifact, result, claim = saved_result(tmp_path)
    before = copy.deepcopy((artifact, result, claim))
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["proposal"] == dataclass_to_dict(result)
    first, second = record["observations"]
    assert first["status"] == second["status"] == "cell_bound"
    assert first["cell"]["row_headers"] == ["SGD", "MemGuide ∗"]
    assert second["cell"]["row_headers"] == ["MultiWOZ 2.2", "MemGuide ∗"]
    assert first["cell"]["value"] == "0.846"
    assert second["cell"]["value"] == "0.879"
    assertion, = record["assertions"]
    assert assertion["text"] == claim.text
    assert assertion["claim_status"] == "unsupported"
    assert assertion["status"] == "pending_review"
    assert assertion["cell_ids"] == [first["cell"]["cell_id"], second["cell"]["cell_id"]]
    assert (artifact, result, claim) == before
    assert not claim.is_publishable()


@pytest.mark.parametrize(("subject", "value", "metric"), [
    ("MemGuide* on SGD", "0.879", "JGA"),  # cannot pick by a number in a different dataset
    ("MemGuide on SGD", "0.846", "JGA"),  # variant marker is identity, not decoration
    ("MemGuide* on SGD and MultiWOZ 2.2", "0.846", "JGA"),
    ("MemGuide* on SGD", "0.846 to 0.879", "JGA"),
    ("MemGuide* on SGD", "84.6%", "JGA"),
    ("MemGuide* on SGD", "0.846", "Joint goal accuracy"),
])
def test_ambiguous_pairs_variants_metrics_or_values_are_not_guessed(
    tmp_path: Path, subject: str, value: str, metric: str,
) -> None:
    artifact, result, claim = saved_result(tmp_path)
    result = replace(result, metric=metric,
                     observations=[replace(result.observations[0], subject=subject, value=value)])
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["observations"][0]["status"] == "unresolved"
    assert record["observations"][0]["cell"] is None


@pytest.mark.parametrize("change", ["page", "table", "foreign", "stale", "unquoted", "duplicate"])
def test_only_declared_quoted_unique_source_cells_are_available(
    tmp_path: Path, change: str,
) -> None:
    artifact, result, claim = saved_result(tmp_path)
    if change == "page":
        result = replace(result, physical_page=12)
    elif change == "table":
        result = replace(result, source_label="Table 3")
    elif change == "foreign":
        result = replace(result, evidence=[replace(e, source_url="https://example.org/other")
                                          for e in result.evidence])
    elif change == "stale":
        artifact = replace(artifact, text=artifact.text + "\nChanged source")
    elif change == "unquoted":
        table = resolved_table(artifact, "Table 5")
        row = next(r for r in table["source_rows"] if r["row_headers"] == ["SGD", "MemGuide ∗"])
        result = replace(result, evidence=[replace(result.evidence[0], quote=row["text"])])
    else:
        table = resolved_table(artifact, "Table 5")
        target = next(c for c in table["cells"] if c["row_headers"] == ["SGD", "MemGuide ∗"]
                      and c["column_headers"] == ["JGA"])
        table["cells"].append({**target, "cell_id": "duplicate"})
        row = next(r for r in table["source_rows"] if target["cell_id"] in r["cell_ids"])
        row["cell_ids"].append("duplicate")
    record, = bind_experimental_results([result], artifact, [claim])
    index = 1 if change == "unquoted" else 0
    assert record["observations"][index]["status"] == "unresolved"


@pytest.mark.parametrize("change", ["missing", "duplicate", "foreign", "disjoint"])
def test_assertion_identity_and_own_evidence_are_mandatory(tmp_path: Path, change: str) -> None:
    artifact, result, claim = saved_result(tmp_path)
    claims = [claim]
    if change == "missing":
        claims = []
    elif change == "duplicate":
        claims.append(replace(claim, text="A different assertion with the same id"))
    elif change == "foreign":
        claims = [replace(claim, evidence=[replace(e, source_url="https://example.org/other")
                                          for e in claim.evidence])]
    else:
        claims = [replace(claim, evidence=[replace(claim.evidence[0], quote="Unrelated text")])]
    record, = bind_experimental_results([result], artifact, claims)
    assert record["assertions"][0]["status"] != "pending_review"
    assert record["assertions"][0]["cell_ids"] == []


def test_source_conflict_and_original_uncertainty_are_not_resolved(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    result = replace(result, binding_status="source_conflict",
                     uncertainty=["Table: 0.846. Accompanying prose: 0.879."])
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["proposal"]["binding_status"] == "source_conflict"
    assert record["proposal"]["uncertainty"] == result.uncertainty
    assert record["assertions"][0]["status"] == "source_conflict"
    assert not claim.is_publishable()


def test_materialized_source_block_newlines_do_not_break_the_same_quote_binding(
    tmp_path: Path,
) -> None:
    artifact, result, claim = saved_result(tmp_path)
    # Saved result anchors retain the block's final newline; Claim anchors are already stripped.
    result = replace(result, evidence=[replace(e, quote=e.quote + "\n") for e in result.evidence])
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["assertions"][0]["status"] == "pending_review"
    assert len(record["assertions"][0]["cells"]) == 2
    assert record["proposal"]["evidence"][0]["quote"].endswith("\n")
    assert record["assertions"][0]["cells"][0]["anchors"][0]["quote"] == claim.evidence[0].quote


def test_review_context_retains_pending_assertions_and_exact_target_associations(
    tmp_path: Path,
) -> None:
    artifact, result, claim = saved_result(tmp_path)
    base, payload = fixture()
    reading = replace(parse_paper_reading(json.dumps(payload), base),
                      source_url=artifact.source.url, experimental_results=[result])
    context, _ = build_reading_review_context([reading], [], [artifact], source_claims=[claim])
    proposal = json.loads(context)["experimental_result_proposals"][0]
    assert proposal["results"] == [dataclass_to_dict(result)]
    record = proposal["bindings"][0]
    assert "proposal" not in record  # Original records occur once, referenced by result_id.
    assert record["assertions"][0]["text"] == claim.text
    assert record["assertions"][0]["claim_status"] == "unsupported"
    eligible = replace(claim, status=ClaimStatus.SUPPORTED)
    context, _ = build_reading_review_context([reading], [eligible], [artifact],
                                             source_claims=[eligible])
    target, = build_review_targets([eligible], context, method_sources=set()).targets.values()
    assert target["experimental_results"][0]["result_id"] == "r22"
    cells = [e for e in target["direct_evidence"].values() if e.get("cell_id")]
    assert {e["value"] for e in cells} == {"0.846", "0.879"}
    assert all(e["column_headers"] == ["JGA"] for e in cells)
    changed = replace(eligible, text=eligible.text + " Altered assertion.")
    with pytest.raises(AnalysisError, match="Experimental.*assertion"):
        build_review_targets([changed], context, method_sources=set())


def test_unreported_metric_stays_a_missing_value_not_a_result(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    result = replace(result, metric="AGA", observations=[
        replace(result.observations[0], subject="TRADE on MultiWOZ 2.2", value="-")])
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["observations"][0]["reason"] == "value_not_reported"
    assert record["proposal"]["observations"][0]["value"] == "-"


def test_changed_assertion_or_observations_changes_the_audit_identity(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    record, = bind_experimental_results([result], artifact, [claim])
    for changed_result, changed_claim in [
        (result, replace(claim, text="SGD and MultiWOZ results swapped.")),
        (replace(result, observations=list(reversed(result.observations))), claim),
        (replace(result, conditions=["Different experimental condition"]), claim),
        (result, replace(claim, status=ClaimStatus.SUPPORTED)),
    ]:
        changed, = bind_experimental_results([changed_result], artifact, [changed_claim])
        assert changed["binding_sha256"] != record["binding_sha256"]


def test_existing_factual_review_sees_bindings_but_cannot_promote_blocked_prose(
    tmp_path: Path,
) -> None:
    artifact, result, blocked = saved_result(tmp_path)
    base, payload = fixture()
    reading = replace(parse_paper_reading(json.dumps(payload), base),
                      source_url=artifact.source.url, experimental_results=[result])
    eligible = replace(blocked, text="Offline eligible control, not a real approval.",
        status=ClaimStatus.SUPPORTED, metadata={"paper_reading": {"claim_id": "control"}})
    reviewer = BoundaryReviewer()
    checked = review_publication_facts([eligible, blocked], reviewer, model="offline",
                                       readings=[reading], artifacts=[artifact])
    assert len(reviewer.requests) == 1
    assert not fact_is_reviewed(checked.claims[1])
    assert checked.claims[1] == blocked
    context = reviewer.contexts[0]
    pending = context["experimental_result_proposals"][0]["bindings"][0]["assertions"][0]
    assert pending["claim_status"] == "unsupported" and len(pending["cells"]) == 2
    assert all(t.get("claim_id") != "c51" for t in reviewer.requests[0][0].values())


def test_only_own_quote_cells_are_added_to_a_review_target(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    table = resolved_table(artifact, "Table 5")
    row = next(r for r in table["source_rows"] if r["row_headers"] == ["SGD", "MemGuide ∗"])
    result = replace(result, evidence=[replace(result.evidence[0], quote=row["text"])])
    record, = bind_experimental_results([result], artifact, [claim])
    assert record["assertions"][0]["cell_ids"] == []  # different quotation, never borrowed


def test_new_bindings_change_targets_without_changing_response_schema(tmp_path: Path) -> None:
    artifact, result, claim = saved_result(tmp_path)
    claim = replace(claim, status=ClaimStatus.SUPPORTED)
    base, payload = fixture()
    reading = replace(parse_paper_reading(json.dumps(payload), base),
                      source_url=artifact.source.url, experimental_results=[result])
    context, _ = build_reading_review_context([reading], [claim], [artifact])
    with_bindings = build_review_targets([claim], context, method_sources=set())
    legacy = build_review_targets([claim], "", method_sources=set())
    assert set(with_bindings.targets) != set(legacy.targets)
    assert with_bindings.schema["$id"] == legacy.schema["$id"]


def test_experimental_catalog_coexists_with_operation_and_relation_targets(tmp_path: Path) -> None:
    _, result, _ = saved_result(tmp_path)
    artifact, reading, claims = score_reading()
    reading = replace(reading, experimental_results=[result])
    context, _ = build_reading_review_context([reading], claims, [artifact], source_claims=claims)
    targets = build_review_targets(claims, context, source_claims=claims)
    assert {t["kind"] for t in targets.targets.values()} == {"fact", "operation", "link"}
