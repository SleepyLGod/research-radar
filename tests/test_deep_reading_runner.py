from research_radar.analysis.deep_reading import run_artifact_deep_reading
from research_radar.analysis.providers import StaticProvider
from research_radar.models import Artifact, ClaimStatus, SourceCandidate, SourceType


def test_deep_reading_runner_repairs_anchor_and_filters_stale_findings() -> None:
    table_quote = "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"
    artifact = Artifact(
        source=SourceCandidate(
            title="Memory Methods",
            url="https://example.com/paper",
            source_type=SourceType.PAPER,
            source_name="fixture",
        ),
        text=f"[page 12]\n{table_quote}",
    )
    reader = StaticProvider(_reading_json("Ours reaches 38.79 overall F1 in Table 7."))
    repair = StaticProvider(
        f"""
        {{
          "repairs": [
            {{
              "claim_index": 1,
              "quote": "{table_quote}",
              "location": "page 12, Table 7",
              "reason": "Exact table row supports the numeric claim."
            }}
          ]
        }}
        """
    )

    result = run_artifact_deep_reading(
        artifact,
        reader,
        model="fake-reader",
        anchor_repair_provider=repair,
        anchor_repair_model="fake-repair",
    )

    assert result.claims[0].status == ClaimStatus.SUPPORTED
    assert result.anchor_repairs[0].status == "accepted"
    assert result.reader_attempts[0].status == "succeeded"
    assert not any(
        finding.metadata.get("kind") == "evidence_anchor_unmatched"
        and finding.claim_text == result.claims[0].text
        for finding in result.findings
    )


def _reading_json(claim_text: str) -> str:
    return f"""
    {{
      "deep_readings": {{
        "area_context": {{
          "background": "Table 7 compares memory methods.",
          "evidence": [{{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}}]
        }},
        "problem_solution": {{
          "problem": "Table 7 compares memory methods.",
          "why_it_matters": "The table reports method performance.",
          "hidden_assumptions": [],
          "solution": "Table 7 compares memory methods.",
          "mechanism": "Table 7 compares memory methods.",
          "evidence": [{{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}}]
        }},
        "related_work": {{
          "prior_work": ["unknown"],
          "novelty": "unknown",
          "repackaging_risk": "unknown",
          "evidence": [{{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}}]
        }},
        "limitations": {{
          "explicit_limitations": [],
          "inferred_weaknesses": [],
          "evidence": [{{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}}]
        }},
        "critical_assessment": {{
          "overclaiming_risk": "Low",
          "weak_evaluations": [],
          "missing_ablations": [],
          "bottom_line": "The table supports only a narrow numeric claim.",
          "evidence": [{{"quote": "Table 7 Overall F1 A-MEM 25.53 MemTree 36.92 Ours 38.79"}}]
        }},
        "plain_language_example": "A table row compares methods.",
        "essence": "The paper compares memory methods.",
        "claim_units": [
          {{
            "section": "experiment",
            "claim_kind": "fact",
            "text": "{claim_text}",
            "evidence": [],
            "publishable_default": true
          }}
        ],
        "unsupported_or_rejected_claims": []
      }}
    }}
    """
