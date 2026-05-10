"""Prompt builders for analysis and review."""

from __future__ import annotations

from research_radar.models import Artifact, Claim


def research_planner_prompt(topic_id: str, queries: list[str]) -> str:
    """Build a prompt for conservative topic planning before discovery."""

    query_lines = "\n".join(f"- {query}" for query in queries) or "- No seed queries provided."
    return (
        "Plan a ResearchRadar run before any article writing.\n"
        "Conservatively expand the user topic into neutral research scope. "
        "Do not assume a conclusion.\n\n"
        f"TOPIC ID: {topic_id}\n"
        f"SEED QUERIES:\n{query_lines}\n\n"
        "Return structured JSON with:\n"
        "- research_plan: neutral_scope, explicit_exclusions, research_questions, "
        "source_priorities, risk_checks\n"
        "- wide_scan_plan: source types to inspect, clustering dimensions, ranking criteria\n"
        "- deep_reading_plan: criteria for selecting papers, blogs, "
        "or repositories to read deeply\n"
        "- unsupported_or_rejected_claims: claims the planner refuses to assume\n\n"
        "Rules:\n"
        "- Research questions should collectively form a balanced view of the topic.\n"
        "- Include recency, source-bias, hallucination, and overclaiming risks.\n"
        "- Do not recommend adding runtime dependencies or external backends.\n"
    )


def triage_prompt(artifacts: list[Artifact]) -> str:
    """Build a prompt for wide-scan triage and source ranking."""

    sections = []
    for artifact in artifacts:
        text = artifact.text[:4000]
        sections.append(
            f"TITLE: {artifact.source.title}\n"
            f"URL: {artifact.source.url}\n"
            f"TEXT:\n{text}"
        )
    return (
        "You are running the wide-scan stage for a ResearchRadar brief.\n"
        "Cluster the supplied materials, rank source value, and select deep-reading candidates. "
        "Separate facts from interpretation and speculation.\n\n"
        "Return structured JSON with:\n"
        "- wide_scan: clusters, ranked_sources, trends, outliers, contradictions, "
        "deep_reading_candidates\n"
        "- evidence_index: source URL or paper id, page or section when available, "
        "and a short quote or paraphrased anchor\n"
        "- unsupported_or_rejected_claims: unsupported, marketing-like, or overbroad claims\n\n"
        "Rules:\n"
        "- Return only claims directly supported by the provided material.\n"
        "- Prefer primary papers, official docs, primary blogs, and repository evidence.\n"
        "- Do not treat popularity, author framing, or graph clusters as proof.\n\n"
        + "\n\n---\n\n".join(sections)
    )


def synthesis_outline_prompt(topic_id: str, claims: list[Claim]) -> str:
    """Build a prompt for outline-first synthesis from verified claims."""

    claim_lines = _claim_blocks(claims)
    return (
        "Build a ResearchRadar synthesis outline before article drafting.\n"
        "Use STORM-like perspective questions, but write only from verified evidence.\n\n"
        f"TOPIC ID: {topic_id}\n\n"
        "VERIFIED CLAIMS:\n"
        f"{claim_lines}\n\n"
        "Return structured JSON with:\n"
        "- synthesis_outline: title, thesis, sections, section_claim_ids, missing_evidence\n"
        "- perspective_questions: questions from researcher, builder, evaluator, "
        "and skeptic views\n"
        "- article_draft_notes: lede angle, caveats, examples to use, examples to avoid\n"
        "- evidence_index: source anchors used by each outline section\n"
        "- unsupported_or_rejected_claims: attractive claims that should not be published\n\n"
        "Rules:\n"
        "- Outline first; do not write the finished article.\n"
        "- Every factual, novelty, limitation, or critique claim needs an evidence anchor.\n"
        "- Watch for red herrings, source-bias transfer, and shaky cross-source links.\n"
    )


def verifier_prompt(
    claims: list[Claim],
    *,
    topic_id: str | None = None,
    queries: list[str] | None = None,
) -> str:
    """Build a prompt for unsupported-claim review."""

    claim_lines = _claim_blocks(claims)
    query_lines = "\n".join(f"- {query}" for query in (queries or [])) or "- Unknown"
    topic_context = topic_id or "Unknown"
    return (
        "Review these claims for hallucination risk. "
        "Flag claims that are not supported by evidence, overstate novelty, "
        "convert speculation into fact, or make unsupported critique.\n"
        "No factual, novelty, limitation, or critique claim is publishable without "
        "a source anchor.\n\n"
        f"MONITORED TOPIC: {topic_context}\n"
        f"TOPIC QUERIES:\n{query_lines}\n\n"
        "Return JSON only with this shape:\n"
        "{\n"
        '  "decisions": [\n'
        "    {\n"
        '      "claim_index": 1,\n'
        '      "status": "supported|unsupported|needs_review|speculative",\n'
        '      "risk": "low|medium|high",\n'
        '      "reason": "short evidence-grounded rationale"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        + claim_lines
    )


def _claim_blocks(claims: list[Claim]) -> str:
    claim_lines = []
    for index, claim in enumerate(claims, start=1):
        evidence = "\n".join(
            f"- {anchor.source_url} {anchor.location or ''}: {anchor.quote}"
            for anchor in claim.evidence
        )
        claim_lines.append(f"{index}. CLAIM: {claim.text}\nEVIDENCE:\n{evidence or '- NONE'}")
    return "\n\n".join(claim_lines) or "No claims provided."
