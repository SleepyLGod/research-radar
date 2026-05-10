from research_radar.evidence.policy import enforce_evidence_policy, publishable_claims
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor


def test_unsupported_claim_is_rejected() -> None:
    claims, findings = enforce_evidence_policy(
        [Claim(text="Unsupported strong claim", status=ClaimStatus.SUPPORTED)]
    )

    assert claims[0].status == ClaimStatus.UNSUPPORTED
    assert findings[0].severity == "error"
    assert publishable_claims(claims) == []


def test_supported_claim_is_publishable() -> None:
    claim = Claim(
        text="Supported claim",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Evidence")],
    )

    claims, findings = enforce_evidence_policy([claim])

    assert not findings
    assert publishable_claims(claims) == [claim]


def test_unsupported_claim_with_evidence_stays_unsupported() -> None:
    claim = Claim(
        text="Model rejected claim",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Evidence")],
    )

    claims, findings = enforce_evidence_policy([claim])

    assert claims[0].status == ClaimStatus.UNSUPPORTED
    assert findings[0].severity == "error"
    assert publishable_claims(claims) == []
