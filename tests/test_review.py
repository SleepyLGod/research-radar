from research_radar.analysis.review import apply_model_review_decisions
from research_radar.evidence.policy import enforce_evidence_policy, publishable_claims
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor


def test_model_review_decision_downgrades_supported_claim() -> None:
    claim = Claim(
        text="A paper is relevant to agent memory.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Evidence")],
    )
    raw = """
    {
      "decisions": [
        {
          "claim_index": 1,
          "status": "unsupported",
          "risk": "high",
          "reason": "topic mismatch"
        }
      ]
    }
    """

    reviewed, findings = apply_model_review_decisions([claim], raw)
    checked, policy_findings = enforce_evidence_policy(reviewed)

    assert checked[0].status == ClaimStatus.UNSUPPORTED
    assert publishable_claims(checked) == []
    assert findings[0].metadata["status"] == "unsupported"
    assert policy_findings[0].severity == "error"


def test_model_review_missing_decision_marks_claim_needs_review() -> None:
    claims = [
        Claim(
            text="Reviewed claim",
            status=ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url="https://example.com/1", quote="Evidence")],
        ),
        Claim(
            text="Omitted claim",
            status=ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url="https://example.com/2", quote="Evidence")],
        ),
    ]
    raw = """
    {
      "decisions": [
        {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"}
      ]
    }
    """

    reviewed, findings = apply_model_review_decisions(claims, raw)

    assert reviewed[0].status == ClaimStatus.SUPPORTED
    assert reviewed[1].status == ClaimStatus.NEEDS_REVIEW
    assert findings[0].metadata["kind"] == "model_review_missing_decision"
