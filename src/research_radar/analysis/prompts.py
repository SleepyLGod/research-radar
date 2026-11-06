"""Prompt builders for analysis and review."""

from __future__ import annotations

import json

from research_radar.models import Artifact, Claim

RESEARCH_RADAR_RUNTIME_CONTRACT = (
    "ResearchRadar research contract:\n"
    "- Separate source facts, evidence-backed interpretation, speculation, critique, "
    "and rejected claims.\n"
    "- Do not turn author marketing, claimed novelty, popularity, or framing into a "
    "system conclusion.\n"
    "- No factual, novelty, limitation, or critique claim is publishable without a "
    "source anchor.\n"
    "- Prefer precise, atomic claims over broad multi-part claims.\n"
)


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

    claim_lines = _claim_blocks(claims, include_references=True)
    query_lines = "\n".join(f"- {query}" for query in (queries or [])) or "- Unknown"
    topic_context = topic_id or "Unknown"
    return (
        RESEARCH_RADAR_RUNTIME_CONTRACT
        + "\n"
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
        "  ],\n"
        '  "follow_up_actions": [\n'
        "    {\n"
        '      "action_type": "missing_anchor|needs_primary_source|claim_too_broad|'
        'split_claim|rerun_deep_reading|source_recheck_query",\n'
        '      "claim_index": 1,\n'
        '      "reason": "what must be checked next",\n'
        '      "query": "optional conservative search query",\n'
        '      "source_url": "optional existing source URL"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- claim_index is the one-based position in THIS request, used only for decisions "
        "and follow-up actions. CLAIM REFERENCE gives its stable Reader claim_id and source_urls. "
        "claim_id is source-scoped and does not change when claims are filtered or reordered; "
        "its numeric suffix is NOT claim_index. A null claim_id means none was supplied; "
        "do not invent or renumber IDs.\n"
        "- You may only downgrade, reject, or keep claims; do not create new publishable claims.\n"
        "- Check support for the entire assertion, not just whether its words or numbers "
        "occur in an excerpt. Verify method/model, baseline, metric, evaluation conditions, "
        "aggregation and outcome stage where relevant.\n"
        "- Read all supplied source excerpts for the claim together. Table binding labels "
        "describe literal extraction, not semantic approval or a guarantee of complete evidence. "
        "Unresolved layout or missing comparison context requires needs_review.\n"
        "- Contradictory supplied evidence requires needs_review; cite the disagreement in "
        "reason, do not silently choose prose over a table or figure. Author attribution "
        "does not make the disputed result unconditionally supported.\n"
        "- Do not infer paper-wide absence from missing excerpts. Keep input coverage "
        "limitations separate from limitations actually stated by the authors.\n"
        "- Use follow_up_actions for missing evidence, too-broad claims, or "
        "primary-source checks.\n"
        "- Follow-up actions are audit tasks only; they are not article content.\n\n"
        + claim_lines
    )


def _claim_blocks(claims: list[Claim], *, include_references: bool = False) -> str:
    claim_lines = []
    for index, claim in enumerate(claims, start=1):
        evidence = "\n".join(
            f"- {anchor.source_url} {anchor.location or ''}: {anchor.quote}"
            for anchor in claim.evidence
        )
        resolution = claim.metadata.get("anchor_resolution", {})
        contexts = resolution.get("evidence_contexts", []) if isinstance(resolution, dict) else []
        if (
            isinstance(resolution, dict) and resolution.get("status") == "matched"
            and isinstance(contexts, list)
        ):
            for context in contexts:
                if not isinstance(context, dict):
                    continue
                if any(
                    context.get("source_url") == anchor.source_url
                    and context.get("quote") == anchor.quote
                    for anchor in claim.evidence
                ):
                    evidence += f"\nMatched source context: {context.get('text', '')}"
                    if context.get("binding"):
                        evidence += f"\nTable binding: {context['binding']}"
                        evidence += f"\nLiteral column labels: {context.get('columns', [])}"
        original_text = claim.metadata.get("localization", {}).get("original_text")
        original = f"\nORIGINAL ANALYSIS: {original_text}" if isinstance(original_text, str) else ""
        reference = ""
        if include_references:
            claim_id = claim.metadata.get("paper_reading", {}).get("claim_id")
            reference = "\nCLAIM REFERENCE: " + json.dumps({
                "claim_index": index,
                "claim_id": claim_id if isinstance(claim_id, str) and claim_id.strip() else None,
                "source_urls": list(dict.fromkeys(anchor.source_url for anchor in claim.evidence)),
            }, ensure_ascii=False)
        claim_lines.append(
            f"{index}. CLAIM: {claim.text}{reference}"
            f"{original}\nEVIDENCE:\n{evidence or '- NONE'}"
        )
    return "\n\n".join(claim_lines) or "No claims provided."
