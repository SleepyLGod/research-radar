"""Evidence validation policy."""

from __future__ import annotations

from dataclasses import replace

from research_radar.models import Claim, ClaimStatus, ReviewFinding


def enforce_evidence_policy(claims: list[Claim]) -> tuple[list[Claim], list[ReviewFinding]]:
    """Reject or downgrade claims that lack support."""

    checked: list[Claim] = []
    findings: list[ReviewFinding] = []
    for claim in claims:
        if claim.status == ClaimStatus.SUPPORTED and claim.evidence:
            checked.append(claim)
            continue
        if claim.status == ClaimStatus.UNSUPPORTED:
            checked.append(claim)
            findings.append(
                ReviewFinding(
                    severity="error",
                    message="Claim is marked unsupported and cannot be published.",
                    claim_text=claim.text,
                )
            )
            continue
        if not claim.evidence:
            checked.append(replace(claim, status=ClaimStatus.UNSUPPORTED))
            findings.append(
                ReviewFinding(
                    severity="error",
                    message="Claim has no evidence anchors and cannot be published.",
                    claim_text=claim.text,
                )
            )
            continue
        checked.append(claim)
        findings.append(
            ReviewFinding(
                severity="warning",
                message="Claim has evidence but was not marked supported.",
                claim_text=claim.text,
            )
        )
    return checked, findings


def publishable_claims(claims: list[Claim]) -> list[Claim]:
    """Return claims that are safe for factual article content."""

    return [claim for claim in claims if claim.is_publishable()]
