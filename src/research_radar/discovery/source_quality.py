"""Deterministic source authority and quality scoring."""

from __future__ import annotations

from dataclasses import replace

from research_radar.models import SourceCandidate

ROLE_BASE_SCORES = {
    "primary_paper": 0.82,
    "benchmark_paper": 0.86,
    "implementation_repo": 0.55,
    "blog_or_web": 0.45,
    "survey_or_list": 0.25,
    "noise": 0.0,
}


def score_source_quality(candidate: SourceCandidate) -> SourceCandidate:
    """Attach a simple authority score for audit and ranking diagnostics."""

    role = str(candidate.metadata.get("source_role", {}).get("role", "noise"))
    score = ROLE_BASE_SCORES.get(role, 0.0)
    reasons = [f"role={role}"]
    trusted_domain = candidate.metadata.get("trusted_domain_match")
    if trusted_domain:
        score += 0.08
        reasons.append(f"trusted_domain={trusted_domain}")
    if candidate.source_name in {"arxiv", "semantic_scholar"}:
        score += 0.05
        reasons.append(f"primary_connector={candidate.source_name}")
    stars = _star_count(candidate)
    if stars >= 1000:
        score += 0.12
        reasons.append("repository_stars>=1000")
    elif stars >= 100:
        score += 0.08
        reasons.append("repository_stars>=100")
    elif stars > 0:
        score += 0.03
        reasons.append("repository_has_stars")
    if role == "survey_or_list":
        score = min(score, 0.35)
        reasons.append("list_capped")
    return replace(
        candidate,
        metadata={
            **candidate.metadata,
            "source_quality": {
                "score": round(min(score, 1.0), 3),
                "reason": ", ".join(reasons),
            },
        },
    )


def paper_coverage_diagnostics(
    candidates: list[SourceCandidate],
    *,
    source_intent: str,
) -> dict[str, object]:
    """Return paper coverage diagnostics for a research run."""

    paper_candidates = [
        candidate
        for candidate in candidates
        if candidate.metadata.get("source_role", {}).get("role")
        in {"primary_paper", "benchmark_paper"}
    ]
    relevant_papers = [
        candidate
        for candidate in paper_candidates
        if candidate.metadata.get("relevance", {}).get("status") == "relevant"
    ]
    viable_papers = [
        candidate
        for candidate in relevant_papers
        if float(candidate.metadata.get("relevance", {}).get("score", 0.0)) >= 0.6
    ]
    status = "pass"
    reason = "viable paper found"
    if source_intent == "research_brief" and not relevant_papers:
        status = "degraded"
        reason = "no relevant paper found for research brief"
    elif source_intent == "research_brief" and not viable_papers:
        status = "degraded"
        reason = "relevant papers found but none passed viability threshold"
    return {
        "status": status,
        "reason": reason,
        "paper_candidate_count": len(paper_candidates),
        "relevant_paper_count": len(relevant_papers),
        "viable_paper_count": len(viable_papers),
    }


def _star_count(candidate: SourceCandidate) -> int:
    value = candidate.metadata.get("stars")
    return value if isinstance(value, int) else 0
