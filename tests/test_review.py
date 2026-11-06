import json

import pytest

from research_radar.analysis.providers import Message, ModelResponse
from research_radar.analysis.review import (
    apply_model_review_decisions,
    extract_verification_actions,
    model_review_publishable_claims,
)
from research_radar.compose.draft import build_daily_draft
from research_radar.compose.wechat import render_wechat_html
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


@pytest.mark.parametrize("index", ["²", "9" * 5000])
def test_invalid_unicode_or_oversized_review_index_cannot_abort_review(index: str) -> None:
    claim = Claim(
        text="Experiment: A locally anchored claim.", status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote="A result.")],
    )
    feedback = json.dumps({
        "decisions": [{"claim_index": index, "status": "supported"}],
        "follow_up_actions": [{"claim_index": index, "action": "inspect", "reason": "Check."}],
    })
    result = model_review_publishable_claims([claim], CapturingProvider(feedback), model="offline")

    assert result.reviewed_count == 0
    assert not result.claims[0].is_publishable()
    assert all(action.claim_index is None for action in result.actions)


@pytest.mark.parametrize(
    "feedback",
    [
        "not JSON",
        '{}',
        '{"decisions": []}',
        '{"decisions": [{"claim_index": 1, "status": "maybe"}]}',
        '{"decisions": [{"claim_index": true, "status": "supported"}]}',
    ],
)
def test_invalid_review_cannot_reach_public_draft(feedback: str) -> None:
    claim = Claim(
        text="Experiment: An unverified result must not be public.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote="A result.")],
        metadata={"paper_reading": {"claim_id": "c1"}},
    )
    provider = CapturingProvider(feedback)

    result = model_review_publishable_claims([claim], provider, model="offline")
    checked, _ = enforce_evidence_policy(result.claims)
    draft = build_daily_draft("offline", [], checked)

    assert result.reviewed_count == 0
    assert not result.claims[0].is_publishable()
    assert result.claims[0].metadata["paper_reading"]["claim_id"] == "c1"
    assert draft.publishable_claims() == []
    assert claim.text not in render_wechat_html(draft)
    assert len(provider.messages) == 1


def test_review_counts_only_valid_decisions_and_keeps_rejections() -> None:
    claims = [
        Claim(
            text=f"Result {index}",
            status=ClaimStatus.SUPPORTED,
            evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote="A result.")],
        )
        for index in range(4)
    ]
    provider = CapturingProvider(json.dumps({"decisions": [
        {"claim_index": 1, "status": "supported"},
        {"claim_index": 2, "status": "unsupported"},
        {"claim_index": 3, "status": "maybe"},
    ]}))

    result = model_review_publishable_claims(claims, provider, model="offline")

    assert result.reviewed_count == 2
    assert [claim.status for claim in result.claims] == [
        ClaimStatus.SUPPORTED, ClaimStatus.UNSUPPORTED,
        ClaimStatus.NEEDS_REVIEW, ClaimStatus.NEEDS_REVIEW,
    ]


def test_malformed_review_does_not_promote_or_reuse_previous_decisions() -> None:
    claim = Claim(
        text="Previously reviewed claim", status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url="https://example.com/paper", quote="A result.")],
        metadata={"model_review": {"requested_status": "supported", "status": "supported"}},
    )
    result = model_review_publishable_claims(
        [claim], CapturingProvider("not JSON"), model="offline",
    )
    rejected, _ = apply_model_review_decisions(
        [Claim(text="Already rejected", status=ClaimStatus.UNSUPPORTED)], "not JSON",
    )

    assert result.reviewed_count == 0
    assert not result.claims[0].is_publishable()
    assert rejected[0].status == ClaimStatus.UNSUPPORTED
    assert rejected[0].metadata["model_review"]["status"] == "unsupported"


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
