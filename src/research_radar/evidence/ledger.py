"""Evidence ledger persistence."""

from __future__ import annotations

from pathlib import Path

from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, dataclass_to_dict
from research_radar.storage.files import read_jsonl, write_jsonl


def write_claims(path: Path, claims: list[Claim]) -> None:
    """Write claims to JSON Lines."""

    write_jsonl(path, claims)


def write_evidence(path: Path, claims: list[Claim]) -> None:
    """Write all claim evidence anchors to JSON Lines."""

    rows = []
    for claim in claims:
        for anchor in claim.evidence:
            row = dataclass_to_dict(anchor)
            row["claim_text"] = claim.text
            rows.append(row)
    write_jsonl(path, rows)


def load_claims(path: Path) -> list[Claim]:
    """Load claims from JSON Lines."""

    claims = []
    for row in read_jsonl(path):
        evidence = [
            EvidenceAnchor(
                source_url=str(item["source_url"]),
                quote=str(item["quote"]),
                location=item.get("location"),
                source_title=item.get("source_title"),
                confidence=float(item.get("confidence", 1.0)),
            )
            for item in row.get("evidence", [])
        ]
        claims.append(
            Claim(
                text=str(row["text"]),
                status=ClaimStatus(str(row.get("status", "needs_review"))),
                evidence=evidence,
                rationale=row.get("rationale"),
                metadata=row.get("metadata", {}),
            )
        )
    return claims
