from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import (
    apply_model_review_decisions,
    extract_verification_actions,
    model_review_publishable_claims,
)
from research_radar.evidence.policy import enforce_evidence_policy, publishable_claims
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor


class CapturingProvider:
    name = "reviewer"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[list[Message]] = []

    def complete(self, messages: list[Message], *, model: str) -> ModelResponse:
        self.messages.append(messages)
        return ModelResponse(content=self.content, model=model)


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


def test_model_review_cannot_promote_non_publishable_claim() -> None:
    claim = Claim(
        text="Unsupported claim",
        status=ClaimStatus.UNSUPPORTED,
        evidence=[],
    )
    raw = """
    {
      "decisions": [
        {"claim_index": 1, "status": "supported", "risk": "low", "reason": "looks okay"}
      ]
    }
    """

    reviewed, findings = apply_model_review_decisions([claim], raw)

    assert reviewed[0].status == ClaimStatus.UNSUPPORTED
    assert reviewed[0].metadata["model_review"]["requested_status"] == "supported"
    assert "cannot promote" in (reviewed[0].rationale or "")
    assert findings[0].metadata["status"] == "unsupported"


def test_model_review_accepts_fenced_json() -> None:
    claim = Claim(
        text="A paper is relevant to agent memory.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Evidence")],
    )
    raw = """
    ```json
    {
      "decisions": [
        {
          "claim_index": 1,
          "status": "needs_review",
          "risk": "medium",
          "reason": "partially grounded"
        }
      ]
    }
    ```
    """

    reviewed, findings = apply_model_review_decisions([claim], raw)

    assert reviewed[0].status == ClaimStatus.NEEDS_REVIEW
    assert findings[0].metadata["status"] == "needs_review"


def test_model_review_extracts_fenced_follow_up_actions() -> None:
    claim = Claim(
        text="Problem: A broad claim mixes problem and result.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com", quote="Evidence")],
    )
    raw = """
    ```json
    {
      "decisions": [
        {"claim_index": 1, "status": "needs_review", "risk": "medium", "reason": "too broad"}
      ],
      "follow_up_actions": [
        {
          "action_type": "split_claim",
          "claim_index": 1,
          "reason": "Split the problem statement from the result claim.",
          "query": "agent memory benchmark grounded answerability",
          "source_url": "https://example.com"
        }
      ]
    }
    ```
    """

    actions = extract_verification_actions(raw, [claim])

    assert len(actions) == 1
    assert actions[0].action_type == "split_claim"
    assert actions[0].claim_index == 1
    assert actions[0].claim_text == claim.text
    assert actions[0].query == "agent memory benchmark grounded answerability"


def test_model_review_publishable_claims_skips_non_publishable_claims() -> None:
    claims = [
        Claim(
            text="Supported claim",
            status=ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url="https://example.com/1", quote="Evidence 1")],
        ),
        Claim(
            text="Needs-review claim",
            status=ClaimStatus.NEEDS_REVIEW,
            evidence=[EvidenceAnchor(source_url="https://example.com/2", quote="Evidence 2")],
            metadata={"paper_reading": {"status_reason": "claim too broad; split setup facets"}},
        ),
        Claim(text="Unsupported claim", status=ClaimStatus.UNSUPPORTED, evidence=[]),
    ]
    provider = CapturingProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "needs_review", "risk": "medium", "reason": "weak"}
          ],
          "follow_up_actions": [
            {"claim_index": 1, "action_type": "split_claim", "reason": "Narrow it."}
          ]
        }
        """
    )

    result = model_review_publishable_claims(
        claims,
        provider,
        model="fake-reviewer",
        topic_id="agent-memory",
        queries=["agent memory"],
    )

    assert len(provider.messages) == 1
    prompt = provider.messages[0][1].content
    assert "Supported claim" in prompt
    assert "Needs-review claim" not in prompt
    assert result.reviewed_count == 1
    assert result.skipped_count == 2
    assert result.claims[0].status == ClaimStatus.NEEDS_REVIEW
    assert result.claims[1].status == ClaimStatus.NEEDS_REVIEW
    assert result.claims[2].status == ClaimStatus.UNSUPPORTED
    assert result.actions[0].claim_index == 1
    assert any(
        finding.metadata.get("kind") == "model_review_skipped_claims"
        for finding in result.findings
    )


def test_model_review_publishable_claims_remaps_subset_action_indexes() -> None:
    claims = [
        Claim(text="Skipped", status=ClaimStatus.UNSUPPORTED, evidence=[]),
        Claim(
            text="Reviewed",
            status=ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url="https://example.com", quote="Evidence")],
        ),
    ]
    provider = CapturingProvider(
        """
        {
          "decisions": [
            {"claim_index": 1, "status": "supported", "risk": "low", "reason": "grounded"}
          ],
          "follow_up_actions": [
            {"claim_index": 1, "action_type": "needs_primary_source", "reason": "Check."}
          ]
        }
        """
    )

    result = model_review_publishable_claims(claims, provider, model="fake-reviewer")

    assert result.actions[0].claim_index == 2
    assert result.actions[0].claim_text == "Reviewed"
