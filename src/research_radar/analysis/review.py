"""Claim review helpers."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from research_radar.analysis.prompts import verifier_prompt
from research_radar.analysis.providers import LLMProvider, Message
from research_radar.evidence.policy import enforce_evidence_policy
from research_radar.models import Claim, ClaimStatus, ReviewFinding


def rule_based_review(claims: list[Claim]) -> tuple[list[Claim], list[ReviewFinding]]:
    """Run deterministic evidence policy checks."""

    return enforce_evidence_policy(claims)


def model_review(
    claims: list[Claim],
    provider: LLMProvider,
    *,
    model: str,
    topic_id: str | None = None,
    queries: list[str] | None = None,
) -> tuple[list[Claim], list[ReviewFinding], str]:
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
    return reviewed_claims, findings, raw_feedback


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
        status = _decision_status(decision)
        if status is None:
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message="Model review returned a decision with an invalid status.",
                    claim_text=claim.text,
                    metadata={"kind": "model_review_invalid_status", "decision": decision},
                )
            )
            continue
        reason = str(decision.get("reason") or decision.get("rationale") or "")
        risk = str(decision.get("risk") or "")
        reviewed[index - 1] = replace(
            claim,
            status=status,
            rationale=reason or claim.rationale,
            metadata={
                **claim.metadata,
                "model_review": {
                    "status": status.value,
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


def _parse_decisions(raw_feedback: str) -> list[dict[str, object]] | None:
    raw_feedback = _strip_json_fence(raw_feedback)
    try:
        payload = json.loads(raw_feedback)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        decisions = payload.get("decisions")
    else:
        decisions = payload
    if not isinstance(decisions, list):
        return None
    return [decision for decision in decisions if isinstance(decision, dict)]


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
