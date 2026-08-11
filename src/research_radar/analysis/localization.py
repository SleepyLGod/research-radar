"""Report localization after evidence verification."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from research_radar.analysis.paper_reading import (
    AreaContext,
    CriticalAssessment,
    LimitationAssessment,
    PaperReading,
    ProblemSolution,
    ReaderExplanation,
    ReaderExplanationParagraph,
    RelatedWorkAssessment,
)
from research_radar.analysis.providers import LLMProvider, Message
from research_radar.analysis.public_style import LOCALIZATION_PUBLIC_WRITING_STYLE_CONTRACT
from research_radar.evidence.policy import publishable_claims
from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, ReviewFinding, SourceCandidate
from research_radar.security.redaction import redact_text

CANONICAL_CLAIM_PREFIXES = (
    "Problem:",
    "Solution:",
    "Related work:",
    "Experiment:",
    "Limitations:",
    "Critical assessment:",
    "Essence:",
)


@dataclass(frozen=True)
class LocalizationAttempt:
    """One attempt to localize verified report content."""

    provider: str
    model: str
    language: str
    status: str
    scope: str = "report"
    index: int | None = None
    error_message: str | None = None
    response_excerpt: str = ""


@dataclass(frozen=True)
class ReportLocalizationResult:
    """Localized display copies plus audit records."""

    readings: list[PaperReading]
    claims: list[Claim]
    sources: list[SourceCandidate]
    figures_by_source_url: dict[str, list[dict[str, object]]]
    attempts: list[LocalizationAttempt]
    findings: list[ReviewFinding]
    status: str = "succeeded"


def localization_body_failed(result: ReportLocalizationResult) -> bool:
    """Return whether a deep-read body localization chunk failed."""

    return any(
        attempt.scope == "reading" and attempt.status == "failed"
        for attempt in result.attempts
    )


def localization_failed(result: ReportLocalizationResult) -> bool:
    """Return whether any localization chunk failed."""

    return any(attempt.status == "failed" for attempt in result.attempts)


def localize_report_content(
    *,
    readings: list[PaperReading],
    claims: list[Claim],
    sources: list[SourceCandidate],
    figures_by_source_url: dict[str, list[dict[str, object]]] | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    language: str = "en",
) -> ReportLocalizationResult:
    """Return localized display copies without changing evidence objects."""

    figures = figures_by_source_url or {}
    if language != "zh":
        return ReportLocalizationResult(
            readings,
            claims,
            sources,
            figures,
            [],
            [],
            status="not_needed",
        )
    if provider is None or model is None:
        return ReportLocalizationResult(
            readings,
            claims,
            sources,
            figures,
            [
                LocalizationAttempt(
                    provider="local",
                    model="local",
                    language=language,
                    status="skipped",
                    error_message="No report localization provider configured.",
                )
            ],
            [
                ReviewFinding(
                    severity="info",
                    message="Report localization skipped; no provider was configured.",
                    metadata={"kind": "report_localization_skipped", "language": language},
                )
            ],
            status="skipped",
        )

    localized_readings = list(readings)
    localized_claims = list(claims)
    localized_sources = list(sources)
    localized_figures = {
        source_url: [dict(figure) for figure in source_figures]
        for source_url, source_figures in figures.items()
    }
    attempts: list[LocalizationAttempt] = []
    findings: list[ReviewFinding] = []

    for index, reading in enumerate(readings):
        payload, attempt = _localization_payload(
            provider,
            model,
            language,
            readings=[reading],
            claims=[],
            sources=[],
            figures_by_source_url={},
            scope="reading",
            index=index,
        )
        attempts.append(attempt)
        if payload is None:
            findings.append(_localization_failure_finding(attempt))
            continue
        localized_reading, changed_id_count = _localized_reading(
            reading,
            _entries_by_index(payload.get("readings")).get(0, {}),
        )
        localized_readings[index] = localized_reading
        if changed_id_count:
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message=(
                        "Localized explanation paragraphs were dropped because their "
                        "supporting claim ids were missing or changed."
                    ),
                    metadata={
                        "kind": "report_localization_claim_ids_changed",
                        "reading_index": index,
                        "dropped_paragraph_count": changed_id_count,
                    },
                )
            )

    if claims or sources or figures:
        payload, attempt = _localization_payload(
            provider,
            model,
            language,
            readings=[],
            claims=publishable_claims(claims),
            sources=sources,
            figures_by_source_url=figures,
            scope="display",
            index=None,
        )
        attempts.append(attempt)
        if payload is None:
            findings.append(_localization_failure_finding(attempt))
        else:
            localized_claims = _localized_claims(claims, payload.get("claims"))
            localized_sources = _localized_sources(sources, payload.get("sources"))
            localized_figures = _localized_figures(figures, payload.get("figures"))

    return ReportLocalizationResult(
        localized_readings,
        localized_claims,
        localized_sources,
        localized_figures,
        attempts,
        findings,
        status=localization_status_from_attempts(attempts),
    )


def report_localization_prompt(
    *,
    readings: list[PaperReading],
    claims: list[Claim],
    sources: list[SourceCandidate],
    figures_by_source_url: dict[str, list[dict[str, object]]] | None = None,
) -> str:
    """Build the localization prompt for verified report content."""

    payload = {
        "readings": [_reading_payload(index, reading) for index, reading in enumerate(readings)],
        "claims": [
            {"index": index, "text": claim.text}
            for index, claim in enumerate(claims)
            if claim.is_publishable()
        ],
        "sources": [_source_payload(source) for source in sources],
        "figures": _figure_payloads(figures_by_source_url or {}),
    }
    return f"""Translate verified ResearchRadar display text into Simplified Chinese.

Rules:
- Preserve the original meaning. Do not add facts, claims, critique, rankings, or URLs.
- Keep technical terms, method names, model names, benchmark names, dataset names, metric
  names, formulas, code/package names, and paper titles in English.
- Examples of terms that must stay English: LOCOMO, LongMemEval, BM25, nDCG, RAG,
  SuperLocalMemory, FRQAD, TIAP, Raw, Source, Canonical.
- Keep all numbers, percentages, model names, benchmark names, and comparison direction
  unchanged.
- Keep claim prefixes exactly as provided, for example "Problem:" and "Solution:".
  Translate only the body after the prefix.
- In reader_explanation, translate only each paragraph's text. Return every
  supporting_claim_ids array unchanged and in the same paragraph position.
- For figures, translate caption into localized_caption and translate explanation into
  Chinese display prose while preserving figure labels, model names, metrics, formulas,
  and numbers. Keep the original caption unchanged in the input; do not put extra
  interpretation into localized_caption or explanation.
- Do not translate evidence quotes. This payload does not include evidence quotes; if any
  quote-like exact source text appears, copy it unchanged.
- Use natural Chinese where possible, but accuracy is more important than fluency.
- If a sentence says "the authors report" or "the paper claims", keep that attribution.
- Follow this public writing style contract for display text:
{LOCALIZATION_PUBLIC_WRITING_STYLE_CONTRACT}

Return JSON only with this shape:
{{
  "readings": [
    {{
      "index": 0,
      "area_context": {{"background": "...", "active_questions": [], "common_baselines": []}},
      "problem_solution": {{"problem": "...", "why_it_matters": "...",
        "hidden_assumptions": [], "solution": "...", "mechanism": "..."}},
      "related_work": {{"prior_work": [], "novelty": "...", "repackaging_risk": "..."}},
      "experiments": {{"summary": "..."}},
      "limitations": {{"explicit_limitations": [], "inferred_weaknesses": [], "future_work": []}},
      "critical_assessment": {{"overclaiming_risk": "...", "weak_evaluations": [],
        "missing_ablations": [], "bottom_line": "..."}},
      "essence": "...",
      "plain_language_example": "...",
      "reader_explanation": {{
        "opening_context": [{{"text": "...", "supporting_claim_ids": ["c1"]}}],
        "core_thesis": [{{"text": "...", "supporting_claim_ids": ["c1"]}}],
        "problem_walkthrough": [{{"text": "...", "supporting_claim_ids": ["c1"]}}],
        "solution_walkthrough": [{{"text": "...", "supporting_claim_ids": ["c2"]}}],
        "experiment_interpretation": [{{"text": "...", "supporting_claim_ids": ["c3"]}}],
        "related_work_context": [{{"text": "...", "supporting_claim_ids": ["c4"]}}],
        "limitations_discussion": [{{"text": "...", "supporting_claim_ids": ["c5"]}}],
        "plain_language_story": [{{"text": "...", "supporting_claim_ids": ["c2"]}}],
        "reader_takeaway": [{{"text": "...", "supporting_claim_ids": ["c1"]}}]
      }}
    }}
  ],
  "claims": [{{"index": 0, "text": "Problem: ..."}}],
  "sources": [{{"url": "https://...", "gist": "..."}}],
  "figures": [
    {{"source_url": "https://...", "title": "...", "localized_caption": "...",
      "explanation": "..."}}
  ]
}}

Only return entries for the payload items you received. If the payload has no readings,
return an empty "readings" array. Do not return patch/diff JSON.

Verified display payload:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def _localization_payload(
    provider: LLMProvider,
    model: str,
    language: str,
    *,
    readings: list[PaperReading],
    claims: list[Claim],
    sources: list[SourceCandidate],
    figures_by_source_url: dict[str, list[dict[str, object]]],
    scope: str,
    index: int | None,
) -> tuple[dict[str, object] | None, LocalizationAttempt]:
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    prompt = report_localization_prompt(
        readings=readings,
        claims=claims,
        sources=sources,
        figures_by_source_url=figures_by_source_url,
    )
    response_content = ""
    try:
        response = provider.complete(
            [
                Message(
                    role="system",
                    content=(
                        "You localize verified research report text for publication. "
                        "Return strict JSON only."
                    ),
                ),
                Message(role="user", content=prompt),
            ],
            model=model,
        )
        response_content = response.content
        payload = _load_json_object(response.content)
    except AnalysisError as exc:
        return None, LocalizationAttempt(
            provider=provider_name,
            model=model,
            language=language,
            status="failed",
            scope=scope,
            index=index,
            error_message=str(exc),
            response_excerpt=_response_excerpt(response_content),
        )
    return payload, LocalizationAttempt(
        provider=provider_name,
        model=model,
        language=language,
        status="succeeded",
        scope=scope,
        index=index,
        response_excerpt=_response_excerpt(response_content),
    )


def _localization_failure_finding(attempt: LocalizationAttempt) -> ReviewFinding:
    suffix = f" ({attempt.scope}"
    if attempt.index is not None:
        suffix += f" #{attempt.index}"
    suffix += ")"
    return ReviewFinding(
        severity="warning",
        message=f"Report localization failed{suffix}: {attempt.error_message}",
        metadata={
            "kind": "report_localization_failed",
            "language": attempt.language,
            "scope": attempt.scope,
            "index": attempt.index,
        },
    )


def localization_status_from_attempts(attempts: list[object]) -> str:
    """Summarize localization attempts for manifest/runtime metadata."""

    if not attempts:
        return "not_needed"
    statuses = {getattr(attempt, "status", "") for attempt in attempts}
    if statuses == {"succeeded"}:
        return "succeeded"
    if "succeeded" in statuses and "failed" in statuses:
        return "partial_failed"
    if "failed" in statuses:
        return "failed"
    if statuses == {"skipped"}:
        return "skipped"
    return "partial_failed"


def _reading_payload(index: int, reading: PaperReading) -> dict[str, object]:
    return {
        "index": index,
        "title": reading.title,
        "area_context": {
            "background": reading.area_context.background,
            "active_questions": reading.area_context.active_questions,
            "common_baselines": reading.area_context.common_baselines,
        },
        "problem_solution": {
            "problem": reading.problem_solution.problem,
            "why_it_matters": reading.problem_solution.why_it_matters,
            "hidden_assumptions": reading.problem_solution.hidden_assumptions,
            "solution": reading.problem_solution.solution,
            "mechanism": reading.problem_solution.mechanism,
        },
        "related_work": {
            "prior_work": reading.related_work.prior_work,
            "novelty": reading.related_work.novelty,
            "repackaging_risk": reading.related_work.repackaging_risk,
        },
        "experiments": {"summary": reading.experiment_summary},
        "limitations": {
            "explicit_limitations": reading.limitations.explicit_limitations,
            "inferred_weaknesses": reading.limitations.inferred_weaknesses,
            "future_work": reading.limitations.future_work,
        },
        "critical_assessment": {
            "overclaiming_risk": reading.critical_assessment.overclaiming_risk,
            "weak_evaluations": reading.critical_assessment.weak_evaluations,
            "missing_ablations": reading.critical_assessment.missing_ablations,
            "bottom_line": reading.critical_assessment.bottom_line,
        },
        "essence": reading.essence,
        "plain_language_example": reading.plain_language_example,
        "reader_explanation": _reader_explanation_payload(reading.reader_explanation),
    }


def _reader_explanation_payload(explanation: ReaderExplanation) -> dict[str, object]:
    return {
        key: [
            {
                "text": paragraph.text,
                "supporting_claim_ids": paragraph.supporting_claim_ids,
            }
            for paragraph in getattr(explanation, key)
        ]
        for key in (
            "opening_context",
            "core_thesis",
            "problem_walkthrough",
            "solution_walkthrough",
            "experiment_interpretation",
            "related_work_context",
            "limitations_discussion",
            "plain_language_story",
            "reader_takeaway",
        )
    }


def _source_payload(source: SourceCandidate) -> dict[str, object]:
    gist = source.metadata.get("source_gist", {})
    return {
        "url": source.url,
        "title": source.title,
        "gist": str(gist.get("text") or ""),
    }


def _figure_payloads(
    figures_by_source_url: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    payloads = []
    for source_url, figures in figures_by_source_url.items():
        for figure in figures:
            payloads.append(
                {
                    "source_url": source_url,
                    "title": str(figure.get("title") or ""),
                    "caption": str(figure.get("caption") or ""),
                    "explanation": str(figure.get("explanation") or ""),
                }
            )
    return payloads


def _localized_readings(readings: list[PaperReading], raw: object) -> list[PaperReading]:
    entries = _entries_by_index(raw)
    return [
        _localized_reading(reading, entries.get(index, {}))[0]
        for index, reading in enumerate(readings)
    ]


def _localized_reading(
    reading: PaperReading,
    data: dict[str, object],
) -> tuple[PaperReading, int]:
    area = _mapping(data.get("area_context"))
    problem = _mapping(data.get("problem_solution"))
    related = _mapping(data.get("related_work"))
    experiments = _mapping(data.get("experiments"))
    limitations = _mapping(data.get("limitations"))
    critical = _mapping(data.get("critical_assessment"))
    reader_explanation = _mapping(data.get("reader_explanation"))
    localized_explanation, changed_id_count = _localized_reader_explanation(
        reading.reader_explanation,
        reader_explanation,
    )
    localized = replace(
        reading,
        area_context=AreaContext(
            background=_string(area, "background", reading.area_context.background),
            active_questions=_string_list(
                area,
                "active_questions",
                reading.area_context.active_questions,
            ),
            common_baselines=_string_list(
                area,
                "common_baselines",
                reading.area_context.common_baselines,
            ),
            evidence=reading.area_context.evidence,
        ),
        problem_solution=ProblemSolution(
            problem=_string(problem, "problem", reading.problem_solution.problem),
            why_it_matters=_string(
                problem,
                "why_it_matters",
                reading.problem_solution.why_it_matters,
            ),
            hidden_assumptions=_string_list(
                problem,
                "hidden_assumptions",
                reading.problem_solution.hidden_assumptions,
            ),
            solution=_string(problem, "solution", reading.problem_solution.solution),
            mechanism=_string(problem, "mechanism", reading.problem_solution.mechanism),
            evidence=reading.problem_solution.evidence,
        ),
        related_work=RelatedWorkAssessment(
            prior_work=_string_list(related, "prior_work", reading.related_work.prior_work),
            novelty=_string(related, "novelty", reading.related_work.novelty),
            repackaging_risk=_string(
                related,
                "repackaging_risk",
                reading.related_work.repackaging_risk,
            ),
            evidence=reading.related_work.evidence,
        ),
        limitations=LimitationAssessment(
            explicit_limitations=_string_list(
                limitations,
                "explicit_limitations",
                reading.limitations.explicit_limitations,
            ),
            inferred_weaknesses=_string_list(
                limitations,
                "inferred_weaknesses",
                reading.limitations.inferred_weaknesses,
            ),
            future_work=_string_list(
                limitations,
                "future_work",
                reading.limitations.future_work,
            ),
            evidence=reading.limitations.evidence,
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk=_string(
                critical,
                "overclaiming_risk",
                reading.critical_assessment.overclaiming_risk,
            ),
            weak_evaluations=_string_list(
                critical,
                "weak_evaluations",
                reading.critical_assessment.weak_evaluations,
            ),
            missing_ablations=_string_list(
                critical,
                "missing_ablations",
                reading.critical_assessment.missing_ablations,
            ),
            bottom_line=_string(
                critical,
                "bottom_line",
                reading.critical_assessment.bottom_line,
            ),
            evidence=reading.critical_assessment.evidence,
        ),
        essence=_string(data, "essence", reading.essence),
        plain_language_example=_string(
            data,
            "plain_language_example",
            reading.plain_language_example,
        ),
        experiment_summary=_string(
            experiments,
            "summary",
            reading.experiment_summary,
        ),
        reader_explanation=localized_explanation,
    )
    return localized, changed_id_count


def _localized_reader_explanation(
    original: ReaderExplanation,
    raw: dict[str, object],
) -> tuple[ReaderExplanation, int]:
    values: dict[str, list[ReaderExplanationParagraph]] = {}
    dropped_count = 0
    for key in (
        "opening_context",
        "core_thesis",
        "problem_walkthrough",
        "solution_walkthrough",
        "experiment_interpretation",
        "related_work_context",
        "limitations_discussion",
        "plain_language_story",
        "reader_takeaway",
    ):
        original_paragraphs = getattr(original, key)
        localized_items = raw.get(key)
        localized_items = localized_items if isinstance(localized_items, list) else []
        kept: list[ReaderExplanationParagraph] = []
        for index, paragraph in enumerate(original_paragraphs):
            item = localized_items[index] if index < len(localized_items) else None
            if not isinstance(item, dict):
                dropped_count += 1
                continue
            text = str(item.get("text") or "").strip()
            claim_ids = item.get("supporting_claim_ids")
            normalized_ids = (
                [str(claim_id).strip() for claim_id in claim_ids]
                if isinstance(claim_ids, list)
                else []
            )
            if not text or normalized_ids != paragraph.supporting_claim_ids:
                dropped_count += 1
                continue
            kept.append(
                ReaderExplanationParagraph(
                    text=text,
                    supporting_claim_ids=list(paragraph.supporting_claim_ids),
                )
            )
        values[key] = kept
    return ReaderExplanation(**values), dropped_count


def _localized_claims(claims: list[Claim], raw: object) -> list[Claim]:
    entries = _entries_by_index(raw)
    publishable_positions = [
        index for index, claim in enumerate(claims) if claim.is_publishable()
    ]
    localized_by_position = {}
    for output_index, claim_index in enumerate(publishable_positions):
        claim = claims[claim_index]
        text = _string(entries.get(output_index, {}), "text", claim.text)
        localized_by_position[claim_index] = replace(
            claim,
            text=_preserve_claim_prefix(claim.text, text),
        )
    return [localized_by_position.get(index, claim) for index, claim in enumerate(claims)]


def _localized_sources(sources: list[SourceCandidate], raw: object) -> list[SourceCandidate]:
    raw_items = raw if isinstance(raw, list) else []
    by_url = {str(item.get("url")): item for item in raw_items if isinstance(item, dict)}
    localized = []
    for source in sources:
        data = by_url.get(source.url, {})
        gist = _string(data, "gist", "")
        if not gist:
            localized.append(source)
            continue
        metadata = dict(source.metadata)
        metadata["source_gist"] = {**_mapping(metadata.get("source_gist")), "text": gist}
        localized.append(replace(source, metadata=metadata))
    return localized


def _localized_figures(
    figures_by_source_url: dict[str, list[dict[str, object]]],
    raw: object,
) -> dict[str, list[dict[str, object]]]:
    raw_items = raw if isinstance(raw, list) else []
    by_key = {
        (str(item.get("source_url") or ""), str(item.get("title") or "")): item
        for item in raw_items
        if isinstance(item, dict)
    }
    localized: dict[str, list[dict[str, object]]] = {}
    for source_url, figures in figures_by_source_url.items():
        localized[source_url] = []
        for figure in figures:
            copied = dict(figure)
            match = by_key.get((source_url, str(figure.get("title") or "")), {})
            localized_caption = _string(match, "localized_caption", "")
            if not localized_caption:
                localized_caption = _string(match, "caption", "")
            if localized_caption:
                copied["localized_caption"] = localized_caption
            explanation = _string(match, "explanation", "")
            if explanation:
                copied["explanation"] = explanation
            localized[source_url].append(copied)
    return localized


def _preserve_claim_prefix(original: str, localized: str) -> str:
    prefix = _claim_prefix(original)
    if not prefix:
        return localized or original
    if localized.startswith(prefix):
        return localized
    for known_prefix in CANONICAL_CLAIM_PREFIXES:
        if localized.startswith(known_prefix):
            return prefix + localized[len(known_prefix) :].lstrip()
    return f"{prefix} {localized}".strip()


def _claim_prefix(value: str) -> str:
    for prefix in CANONICAL_CLAIM_PREFIXES:
        if value.startswith(prefix):
            return prefix
    return ""


def _entries_by_index(raw: object) -> dict[int, dict[str, object]]:
    if not isinstance(raw, list):
        return {}
    entries: dict[int, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if isinstance(index, int):
            entries[index] = item
    return entries


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string(data: dict[str, object], key: str, fallback: str) -> str:
    value = data.get(key)
    return str(value).strip() if isinstance(value, str) and value.strip() else fallback


def _string_list(data: dict[str, object], key: str, fallback: list[str]) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return fallback
    items = [str(item).strip() for item in value if str(item).strip()]
    return items or fallback


def _load_json_object(raw_json: str) -> dict[str, object]:
    text = raw_json.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    text = _extract_json_object_text(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError("Report localization response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise AnalysisError("Report localization JSON must be an object.")
    return payload


def _extract_json_object_text(text: str) -> str:
    if text.startswith("{"):
        return text
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


def _response_excerpt(value: str, *, limit: int = 800) -> str:
    excerpt = redact_text(value.strip())
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[:limit].rstrip() + "..."
