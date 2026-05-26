"""Claim review helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from research_radar.analysis.prompts import verifier_prompt
from research_radar.analysis.providers import LLMProvider, Message
from research_radar.evidence.policy import enforce_evidence_policy
from research_radar.models import Claim, ClaimStatus, ReviewFinding, VerificationAction


def rule_based_review(claims: list[Claim]) -> tuple[list[Claim], list[ReviewFinding]]:
    """Run deterministic evidence policy checks."""

    return enforce_evidence_policy(claims)


@dataclass(frozen=True)
class ModelReviewResult:
    """Result of a model review pass."""

    claims: list[Claim]
    findings: list[ReviewFinding]
    raw_feedback: str | None
    actions: list[VerificationAction]
    reviewed_count: int
    skipped_count: int


def model_review(
    claims: list[Claim],
    provider: LLMProvider,
    *,
    model: str,
    topic_id: str | None = None,
    queries: list[str] | None = None,
) -> tuple[list[Claim], list[ReviewFinding], str, list[VerificationAction]]:
    """Run a model review pass and apply structured claim decisions."""

    messages = [
        Message(role="system", content="You are a strict factuality reviewer."),
        Message(
            role="user",
            content=verifier_prompt(claims, topic_id=topic_id, queries=queries),
        ),
    ]
    raw_feedback = provider.complete(messages, model=model).content
    reviewed_claims, findings = apply_model_review_decisions(claims, raw_feedback)
    actions = extract_verification_actions(raw_feedback, claims)
    return reviewed_claims, findings, raw_feedback, actions


def model_review_publishable_claims(
    claims: list[Claim],
    provider: LLMProvider,
    *,
    model: str,
    topic_id: str | None = None,
    queries: list[str] | None = None,
) -> ModelReviewResult:
    """Review only claims that remain publishable after deterministic gates."""

    review_indexes = [index for index, claim in enumerate(claims) if claim.is_publishable()]
    skipped_count = len(claims) - len(review_indexes)
    findings: list[ReviewFinding] = []
    if skipped_count:
        findings.append(_skipped_review_finding(claims, review_indexes))
    if not review_indexes:
        return ModelReviewResult(
            claims=claims,
            findings=findings,
            raw_feedback=None,
            actions=[],
            reviewed_count=0,
            skipped_count=skipped_count,
        )

    review_claims = [claims[index] for index in review_indexes]
    reviewed_subset, model_findings, raw_feedback, actions = model_review(
        review_claims,
        provider,
        model=model,
        topic_id=topic_id,
        queries=queries,
    )
    reviewed = list(claims)
    for subset_index, original_index in enumerate(review_indexes):
        reviewed[original_index] = reviewed_subset[subset_index]
    return ModelReviewResult(
        claims=reviewed,
        findings=[*findings, *model_findings],
        raw_feedback=raw_feedback,
        actions=_remap_actions(actions, review_indexes, claims),
        reviewed_count=len(review_indexes),
        skipped_count=skipped_count,
    )


def apply_model_review_decisions(
    claims: list[Claim],
    raw_feedback: str,
) -> tuple[list[Claim], list[ReviewFinding]]:
    """Apply structured model-review JSON decisions to claims."""

    decisions = _parse_decisions(raw_feedback)
    if decisions is None:
        return claims, [
            ReviewFinding(
                severity="warning",
                message="Model review did not return structured JSON decisions.",
                metadata={"kind": "model_review_parse_error"},
            )
        ]

    reviewed = list(claims)
    findings: list[ReviewFinding] = []
    reviewed_indexes: set[int] = set()
    for decision in decisions:
        index = _decision_index(decision)
        if index is None or index < 1 or index > len(reviewed):
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message="Model review returned a decision with an invalid claim index.",
                    metadata={"kind": "model_review_invalid_index", "decision": decision},
                )
            )
            continue
        reviewed_indexes.add(index)
        claim = reviewed[index - 1]
        requested_status = _decision_status(decision)
        if requested_status is None:
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message="Model review returned a decision with an invalid status.",
                    claim_text=claim.text,
                    metadata={"kind": "model_review_invalid_status", "decision": decision},
                )
            )
            continue
        status = _non_promoting_status(claim.status, requested_status)
        reason = str(decision.get("reason") or decision.get("rationale") or "")
        risk = str(decision.get("risk") or "")
        if status != requested_status:
            reason = (
                f"{reason} Verifier requested {requested_status.value}, but review "
                f"cannot promote an existing {claim.status.value} claim."
            ).strip()
        reviewed[index - 1] = replace(
            claim,
            status=status,
            rationale=reason or claim.rationale,
            metadata={
                **claim.metadata,
                "model_review": {
                    "status": status.value,
                    "requested_status": requested_status.value,
                    "risk": risk,
                    "reason": reason,
                },
            },
        )
        if status != ClaimStatus.SUPPORTED:
            findings.append(
                ReviewFinding(
                    severity="error" if status == ClaimStatus.UNSUPPORTED else "warning",
                    message=f"Model review marked claim as {status.value}: {reason}",
                    claim_text=claim.text,
                    metadata={
                        "kind": "model_review_decision",
                        "status": status.value,
                        "risk": risk,
                    },
                )
            )
    for index, claim in enumerate(reviewed, start=1):
        if index in reviewed_indexes:
            continue
        reviewed[index - 1] = replace(
            claim,
            status=ClaimStatus.NEEDS_REVIEW,
            metadata={
                **claim.metadata,
                "model_review": {
                    "status": ClaimStatus.NEEDS_REVIEW.value,
                    "risk": "unknown",
                    "reason": "Model review omitted this claim.",
                },
            },
        )
        findings.append(
            ReviewFinding(
                severity="warning",
                message="Model review omitted this claim; marking it needs_review.",
                claim_text=claim.text,
                metadata={
                    "kind": "model_review_missing_decision",
                    "status": ClaimStatus.NEEDS_REVIEW.value,
                },
            )
        )
    return reviewed, findings


def extract_verification_actions(
    raw_feedback: str,
    claims: list[Claim],
) -> list[VerificationAction]:
    """Extract non-mutating follow-up verification actions from model feedback."""

    payload = _parse_payload(raw_feedback)
    if payload is None or not isinstance(payload, dict):
        return []
    raw_actions = payload.get("follow_up_actions", [])
    if not isinstance(raw_actions, list):
        return []
    actions = []
    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            continue
        action_type = str(
            raw_action.get("action_type")
            or raw_action.get("type")
            or raw_action.get("action")
            or ""
        ).strip()
        reason = str(raw_action.get("reason") or raw_action.get("rationale") or "").strip()
        if not action_type or not reason:
            continue
        claim_index = _decision_index(raw_action)
        claim_text = None
        if claim_index is not None and 1 <= claim_index <= len(claims):
            claim_text = claims[claim_index - 1].text
        actions.append(
            VerificationAction(
                action_type=action_type,
                reason=reason,
                claim_index=claim_index,
                claim_text=claim_text,
                query=_optional_string(raw_action.get("query")),
                source_url=_optional_string(raw_action.get("source_url")),
                metadata={
                    "provider_payload": {
                        key: value
                        for key, value in raw_action.items()
                        if key
                        not in {
                            "action_type",
                            "type",
                            "action",
                            "reason",
                            "rationale",
                            "claim_index",
                            "index",
                            "query",
                            "source_url",
                        }
                    }
                },
            )
        )
    return actions


def _parse_decisions(raw_feedback: str) -> list[dict[str, object]] | None:
    payload = _parse_payload(raw_feedback)
    if payload is None:
        return None
    if isinstance(payload, dict):
        decisions = payload.get("decisions")
    else:
        decisions = payload
    if not isinstance(decisions, list):
        return None
    return [decision for decision in decisions if isinstance(decision, dict)]


def _parse_payload(raw_feedback: str) -> object | None:
    raw_feedback = _strip_json_fence(raw_feedback)
    try:
        return json.loads(raw_feedback)
    except json.JSONDecodeError:
        return None


def _strip_json_fence(raw_feedback: str) -> str:
    stripped = raw_feedback.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match is None:
        return stripped
    return match.group(1).strip()


def _decision_index(decision: dict[str, object]) -> int | None:
    value = decision.get("claim_index", decision.get("index"))
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _decision_status(decision: dict[str, object]) -> ClaimStatus | None:
    value = decision.get("status")
    if not isinstance(value, str):
        return None
    try:
        return ClaimStatus(value)
    except ValueError:
        return None


def _non_promoting_status(current: ClaimStatus, requested: ClaimStatus) -> ClaimStatus:
    rank = {
        ClaimStatus.UNSUPPORTED: 0,
        ClaimStatus.SPECULATIVE: 1,
        ClaimStatus.NEEDS_REVIEW: 2,
        ClaimStatus.SUPPORTED: 3,
    }
    return requested if rank[requested] <= rank[current] else current


def _skipped_review_finding(
    claims: list[Claim],
    review_indexes: list[int],
) -> ReviewFinding:
    review_index_set = set(review_indexes)
    reason_counts: dict[str, int] = {}
    for index, claim in enumerate(claims):
        if index in review_index_set:
            continue
        reason = _review_skip_reason(claim)
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return ReviewFinding(
        severity="info",
        message="Model review skipped non-publishable claims.",
        metadata={
            "kind": "model_review_skipped_claims",
            "reviewed_count": len(review_indexes),
            "skipped_count": len(claims) - len(review_indexes),
            "reasons": reason_counts,
        },
    )


def _review_skip_reason(claim: Claim) -> str:
    paper_reason = claim.metadata.get("paper_reading", {}).get("status_reason")
    anchor_reason = claim.metadata.get("anchor_resolution", {}).get("reason")
    if claim.status != ClaimStatus.SUPPORTED and isinstance(anchor_reason, str) and anchor_reason:
        return anchor_reason
    if isinstance(paper_reason, str) and paper_reason:
        return paper_reason
    if isinstance(anchor_reason, str) and anchor_reason:
        return anchor_reason
    if not claim.evidence:
        return "missing evidence"
    return f"status={claim.status.value}"


def _remap_actions(
    actions: list[VerificationAction],
    review_indexes: list[int],
    claims: list[Claim],
) -> list[VerificationAction]:
    remapped: list[VerificationAction] = []
    for action in actions:
        if action.claim_index is None:
            remapped.append(action)
            continue
        subset_index = action.claim_index - 1
        if subset_index < 0 or subset_index >= len(review_indexes):
            remapped.append(action)
            continue
        original_index = review_indexes[subset_index] + 1
        remapped.append(
            replace(
                action,
                claim_index=original_index,
                claim_text=claims[original_index - 1].text,
            )
        )
    return remapped


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
