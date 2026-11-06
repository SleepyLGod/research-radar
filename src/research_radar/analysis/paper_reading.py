"""Researcher-grade paper reading structures and validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, replace

from research_radar.analysis.experimental_results import (
    ExperimentalResult,
    parse_experimental_results,
)
from research_radar.analysis.method_flow import (
    MethodAssertion,
    MethodFlow,
    method_claim_ids,
    parse_method_assertion,
    parse_method_flow,
    validate_method_assertions,
)
from research_radar.analysis.model_cache import CachedLLMProvider
from research_radar.analysis.paper_sections import (
    PaperReadingPacket,
    build_reading_packet,
    render_reading_packet,
)
from research_radar.analysis.prompts import RESEARCH_RADAR_RUNTIME_CONTRACT
from research_radar.analysis.providers import LLMProvider, Message
from research_radar.analysis.public_style import READER_PUBLIC_WRITING_STYLE_CONTRACT
from research_radar.analysis.reader_input import ReaderInputError, check_reader_input
from research_radar.analysis.reader_schema import paper_reading_response_schema
from research_radar.analysis.source_references import (
    SourceReferenceError,
    build_source_index,
    resolve_reader_evidence,
)
from research_radar.evidence.policy import enforce_evidence_policy
from research_radar.evidence.quotes import find_quote
from research_radar.exceptions import AnalysisError
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    ReviewFinding,
    dataclass_to_dict,
)
from research_radar.security.redaction import redact_text


@dataclass(frozen=True)
class AreaContext:
    """Background context needed before judging a paper."""

    background: str
    active_questions: list[str] = field(default_factory=list)
    common_baselines: list[str] = field(default_factory=list)
    evidence: list[EvidenceAnchor] = field(default_factory=list)


@dataclass(frozen=True)
class ProblemSolution:
    """The paper's problem and actual solution mechanism."""

    problem: str
    why_it_matters: str
    hidden_assumptions: list[str]
    solution: str
    mechanism: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class RelatedWorkAssessment:
    """Assessment of novelty against related work."""

    prior_work: list[str]
    novelty: str
    repackaging_risk: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class LimitationAssessment:
    """Explicit and inferred limitations."""

    explicit_limitations: list[str]
    inferred_weaknesses: list[str]
    evidence: list[EvidenceAnchor]
    future_work: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CriticalAssessment:
    """Neutral, evidence-backed critique."""

    overclaiming_risk: str
    weak_evaluations: list[str]
    missing_ablations: list[str]
    bottom_line: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class ClaimUnit:
    """One atomic, evidence-backed claim emitted by a paper reading."""

    section: str
    claim_kind: str
    text: str
    evidence: list[EvidenceAnchor]
    claim_id: str = ""
    publishable_default: bool = True
    method: MethodAssertion | None = None


@dataclass(frozen=True)
class ParagraphReview:
    """Verifier decision bound to the exact paragraph and its source-bound claims."""

    status: str
    reason: str
    source_url: str
    binding_sha256: str


@dataclass(frozen=True)
class ReaderExplanationParagraph:
    """One reader-facing paragraph bound to atomic claim ids."""

    text: str
    supporting_claim_ids: list[str] = field(default_factory=list)
    review: ParagraphReview | None = None


@dataclass(frozen=True)
class EvaluationContextItem:
    """Reader-proposed evaluation condition with literal source anchors, not approval."""

    text: str
    evidence: list[EvidenceAnchor]


@dataclass(frozen=True)
class EvaluationContext:
    """Conditions needed to interpret an experiment; empty means not extracted."""

    data_construction: list[EvaluationContextItem] = field(default_factory=list)
    available_inputs: list[EvaluationContextItem] = field(default_factory=list)
    outcome_measurement: list[EvaluationContextItem] = field(default_factory=list)
    claim_references: dict[str, list[str]] | None = None


EVALUATION_DIMENSIONS = ("data_construction", "available_inputs", "outcome_measurement")


def evaluation_context_payload(context: EvaluationContext) -> dict:
    """Serialize new role references or historical proposals without converting between them."""
    if context.claim_references is not None:
        if (set(context.claim_references) != set(EVALUATION_DIMENSIONS)
                or any(getattr(context, key) for key in EVALUATION_DIMENSIONS)):
            raise ReaderContextError("Cannot mix evaluation references and legacy proposals.")
        return {key: list(context.claim_references[key]) for key in EVALUATION_DIMENSIONS}
    return {key: [dataclass_to_dict(item) for item in getattr(context, key)]
            for key in EVALUATION_DIMENSIONS}


@dataclass(frozen=True)
class ReaderExplanation:
    """Reader-facing explanation grouped into evidence-bound paragraphs."""

    opening_context: list[ReaderExplanationParagraph] = field(default_factory=list)
    core_thesis: list[ReaderExplanationParagraph] = field(default_factory=list)
    problem_walkthrough: list[ReaderExplanationParagraph] = field(default_factory=list)
    solution_walkthrough: list[ReaderExplanationParagraph] = field(default_factory=list)
    experiment_interpretation: list[ReaderExplanationParagraph] = field(default_factory=list)
    related_work_context: list[ReaderExplanationParagraph] = field(default_factory=list)
    limitations_discussion: list[ReaderExplanationParagraph] = field(default_factory=list)
    plain_language_story: list[ReaderExplanationParagraph] = field(default_factory=list)
    reader_takeaway: list[ReaderExplanationParagraph] = field(default_factory=list)


@dataclass(frozen=True)
class PaperReading:
    """Structured researcher-grade reading of one paper."""

    title: str
    area_context: AreaContext
    problem_solution: ProblemSolution
    related_work: RelatedWorkAssessment
    limitations: LimitationAssessment
    critical_assessment: CriticalAssessment
    essence: str
    plain_language_example: str
    experiment_summary: str = ""
    experiment_evidence: list[EvidenceAnchor] = field(default_factory=list)
    unsupported_or_rejected_claims: list[str] = field(default_factory=list)
    claim_units: list[ClaimUnit] = field(default_factory=list)
    reader_explanation: ReaderExplanation = field(default_factory=ReaderExplanation)
    evaluation_context: EvaluationContext = field(default_factory=EvaluationContext)
    source_url: str = ""
    experimental_results: list[ExperimentalResult] = field(default_factory=list)
    method_flow: MethodFlow = field(default_factory=MethodFlow)


@dataclass(frozen=True)
class ReaderAttempt:
    """One model attempt to produce structured paper-reading JSON."""

    attempt_index: int
    provider: str
    model: str
    status: str
    error_message: str | None = None
    response_excerpt: str = ""
    input_budget: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperReadingResult:
    """Parsed paper reading plus structured attempt audit."""

    reading: PaperReading
    attempts: list[ReaderAttempt]


class ReaderExplanationError(AnalysisError):
    """Fresh explanation bindings are unusable; do not spend another repair request."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Reader explanation bindings invalid: {message}")
        self.reader_attempts: list[dict[str, object]] = []


class ReaderContextError(AnalysisError):
    """Invalid evaluation references cannot be repaired by another syntax-only request."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Reader evaluation context invalid: {message}")
        self.reader_attempts: list[dict[str, object]] = []


def _reading_response_example(
    *, facts_only: bool = False, source_id: str = "b0000000000000000:1",
) -> str:
    evidence = [{"source_id": source_id}]
    explanation = {item.name: [] for item in fields(ReaderExplanation)}
    explanation["solution_walkthrough"] = [{
        "text": "<explanation grounded only in c1>", "supporting_claim_ids": ["c1"],
    }]
    reading = {
        "title": "<paper title>",
        "area_context": {
            "background": "<source-grounded context>", "active_questions": ["<question>"],
            "common_baselines": ["<named baseline>"], "evidence": evidence,
        },
        "problem_solution": {
            "problem": "<research problem>", "why_it_matters": "<motivation>",
            "hidden_assumptions": ["<source-grounded assumption>"],
            "solution": "<main approach>", "mechanism": "<how the approach works>",
            "evidence": evidence,
        },
        "related_work": {
            "prior_work": ["<named prior work>"], "novelty": "<attributed contribution>",
            "repackaging_risk": "<evidence-grounded assessment>", "evidence": evidence,
        },
        "experiments": {"summary": "<setup, results and conditions>", "evidence": evidence},
        "experimental_results": [{
            "result_id": "r1", "question": "<tested research question>",
            "conditions": ["<task, setup and outcome stage>"], "metric": "<metric name>",
            "observations": [{"subject": "<method under the stated condition>",
                              "value": "<exact reported value or observation>"}],
            "comparison_scope": ["<compared method and setting>"],
            "uncertainty": [], "supporting_claim_ids": ["c2"], "evidence": evidence,
            "source_kind": "text", "source_label": "<table/figure/section label>",
            "physical_page": None, "binding_status": "text_bound",
        }],
        "evaluation_context": {key: [] for key in (
            "data_construction", "available_inputs", "outcome_measurement",
        )},
        "method_flow": {"operations": [{"scope": "<task performed by this operation>",
            "operation_claim_id": "c1", "inputs": [],
            "outputs": [{"name": "<artifact produced by the operation described in c1>",
                         "supporting_claim_ids": ["c1"]}],
            "conditions": []}], "links": [], "gaps": []},
        "limitations": {
            "explicit_limitations": ["<paper-stated limitation>"],
            "inferred_weaknesses": [], "future_work": [], "evidence": evidence,
        },
        "critical_assessment": {
            "overclaiming_risk": "<bounded assessment>", "weak_evaluations": [],
            "missing_ablations": [], "bottom_line": "<evidence-grounded conclusion>",
            "evidence": evidence,
        },
        "plain_language_example": "<grounded simple example>",
        "essence": "<one narrow assertion>",
        "claim_units": [{
            "claim_id": "c1", "section": "solution", "claim_kind": "fact",
            "text": "<one atomic method assertion>", "evidence": evidence,
            "publishable_default": True,
            "method": {"kind": "operation", "from_claim_id": None, "to_claim_id": None},
        }, {
            "claim_id": "c2", "section": "experiment", "claim_kind": "fact",
            "text": "<one scoped experimental observation>", "evidence": evidence,
            "publishable_default": True,
            "method": None,
        }, {
            "claim_id": "c3", "section": "experiment", "claim_kind": "fact",
            "text": "<one evaluation metric or aggregation definition>", "evidence": evidence,
            "publishable_default": True, "method": None,
        }],
        "reader_explanation": {} if facts_only else explanation,
    }
    reading["evaluation_context"]["outcome_measurement"] = ["c3"]
    return json.dumps({
        "deep_readings": [reading],
        "unsupported_or_rejected_claims": ["<considered but ungrounded claim>"],
    }, ensure_ascii=False, separators=(",", ":"))


def _reader_table_projection(value: object) -> object:
    """Keep literal table structure in the prompt; geometry stays in local evidence."""
    if isinstance(value, list):
        return [_reader_table_projection(item) for item in value]
    if isinstance(value, dict):
        return {key: _reader_table_projection(item) for key, item in value.items()
                if key not in {"box", "row_header_boxes", "column_header_boxes"}}
    return value


def paper_reading_prompt(
    artifact: Artifact,
    area_context: str | None = None,
    *,
    language: str = "en",
    packet: PaperReadingPacket | None = None,
    facts_only: bool = False,
) -> str:
    """Build the structured paper-reading prompt."""

    context = area_context or "Infer only from supplied sources; mark missing context as unknown."
    reading_packet = packet or build_reading_packet(artifact)
    source_index = build_source_index(artifact)
    table_context = (
        "\nPOSITIONED TABLE SOURCES (literal cells, not approved findings):\n"
        + json.dumps(_reader_table_projection(artifact.metadata["table_evidence"]),
                     ensure_ascii=False)
        + "\nKeep row/model groups, column paths and units distinct. Do not split glued numbers "
          "or infer cells from unresolved grids. Continue selecting original source_id blocks.\n"
        if artifact.metadata.get("table_evidence") else ""
    )
    explanation_contract = (
        "- Return reader_explanation as an empty object {}. This stage extracts factual "
        "candidates and evaluation conditions, NOT a second article. A separate writer "
        "will compose source-bound paragraphs, then a Verifier will review the exact "
        "final text against the full source. None of these candidates is yet verified.\n"
        if facts_only else f"""
- reader_explanation is the reader-facing explanation layer. Each field is a JSON list
  of paragraph objects with text and supporting_claim_ids. Use an empty list when no
  distinct, grounded explanation is needed. Usually one paragraph per field is enough;
  solution_walkthrough may use more paragraphs to explain the mechanism clearly.
  Keep each paragraph on one topic and cite every claim_unit needed for its factual content.
- reader_explanation must not introduce any new facts beyond the anchored claims. Explain the
  mechanism, experimental conditions and limitations without unsupported generalizations.
- solution_walkthrough must be the most detailed explanation field. Cover components,
  data flow, why each step exists, how components interact and how they connect to
  reported experiments when grounded. Explain the broader area problem first.
- Follow this public writing style contract for reader_explanation only:
{READER_PUBLIC_WRITING_STYLE_CONTRACT}"""
    )
    language_rule = (
        "REPORT LANGUAGE: Simplified Chinese. Every analytical JSON string value must be "
        "Simplified Chinese, including background, problem, motivation, solution, mechanism, "
        "experiments, related work, limitations, critique, plain_language_example, and essence. "
        "Evidence selects supplied source_id values; the program retrieves the original text."
        if language == "zh"
        else "REPORT LANGUAGE: English. Write analytical prose in English. Evidence selects "
        "supplied source_id values; the program retrieves the original text."
    )
    return f"""{RESEARCH_RADAR_RUNTIME_CONTRACT}

Run the deep-reading stage for this ResearchRadar source.
Act as a skeptical but fair researcher.
{language_rule}

Area context:
{context}

Paper:
TITLE: {artifact.source.title}
URL: {artifact.source.url}
{render_reading_packet(reading_packet, rendered_source=source_index.render())}{table_context}

Return one complete JSON object for this single paper, with two root keys:
- deep_readings: an array containing exactly one reading object.
- unsupported_or_rejected_claims: a sibling string array at the root, not inside
  reader_explanation and not an additional item in deep_readings.
Close reader_explanation, then the reading object, then the deep_readings array
before writing the root unsupported_or_rejected_claims field. Do not omit closing braces.
The complete example below defines the nesting and field types. Its placeholders
are not paper facts or evidence; replace them from the supplied packet, never copy them.
Use empty arrays where no grounded entries exist rather than inventing content.

Rules:
- Evidence is a selection, not generated text: every evidence item is
  {{"source_id":"an exact offered source_id value"}}.
  Copy the value after source_id=; the schema lists the available values. Blocks are already
  same-page and bounded. Select separate blocks when support spans multiple passages.
  Do not calculate line ranges or character counts, and do not add brackets to a source_id.
  The program copies the exact substring from the full paper reading packet, including
  formula layout. Never return quote/location fields, reconstructed formulas or paraphrases
  as evidence. A valid selection does not itself establish that it supports an assertion.
- Separate facts from interpretation and speculation.
- This packet contains the complete available extracted text, including references and appendices.
  Text extraction is not visual inspection: missing from extracted text is not absent from the PDF.
  Report coverage gaps as input limitations, not as proof the authors omitted an experiment
  or discussion. Keep evaluation units, aggregation, outcome stage and conditions explicit.
- Table comparisons need the metric and model/group headers plus baseline and target rows.
  Cite both sides of a comparison; a number appearing somewhere in a table is not support
  for a particular method/metric pairing. Do not reconstruct unreadable cells.
- Cross-check results against supplied tables, figures and prose. When they conflict,
  preserve both cited observations as an unresolved discrepancy; do not choose a preferred number.
  Attribution to the authors does not resolve a contradiction or justify an unconditional result.
- claim_units is a required list of atomic claims for verification and publication.
- experimental_results is a list of source-bound experiment records, not another summary.
  Use [] for nonexperimental work or when no result can be extracted. Each record contains
  result_id, question, conditions (list), metric, observations (a list of objects, each with
  subject and value string fields; never a list of strings),
  comparison_scope (list), uncertainty (list), supporting_claim_ids (list), evidence (exact
  source-block objects), source_kind (text/table/figure), source_label, physical_page (1-based
  PDF page or null), binding_status (text_bound/unresolved/source_conflict). No invented cells
  or values. State preprocessing/selection and pre/post-clarification or correction conditions.
  Do not infer a ranking from a single cell or flattened chart labels. A visual value not
  independently bound to a method/legend remains unresolved. Cite conflicting source statements
  separately and mark source_conflict; do not silently choose one. These records propose context;
  only separately verified claims and exact final paragraphs can become public.
- evaluation_context separates data construction (selection and exclusions), available
  inputs (what the system and evaluator receive), and outcome measurement (unit,
  aggregation and stage, including clarification/correction). Each dimension is a list of
  existing factual claim_id strings from claim_units. Extract each condition once in
  claim_units with its own evidence, then index it here; do not create a second summary,
  text/evidence object or new context claim. A fact may serve more than one dimension.
  Leave a dimension empty when unstated. References organize verification and prose coverage,
  not approval; every referenced fact and the final explanation still require verification.
- Return string arrays for active_questions, common_baselines, hidden_assumptions,
  prior_work, explicit_limitations, inferred_weaknesses, future_work, weak_evaluations,
  missing_ablations, and unsupported_or_rejected_claims; do not replace them with prose strings.
- Give every claim_unit a unique short claim_id such as c1, c2, or c3.
  section must be problem, solution, experiment, related_work, limitations,
  critical_assessment, or essence. claim_kind must be fact, interpretation,
  novelty, limitation, critique, or essence.
{explanation_contract}
- Keep each claim_unit to exactly one verifiable assertion; split broad claims.
- claim_units must not combine method, result, novelty, and critique in one sentence.
- Setup facts must be separate claim_units: benchmark identity, metric definition,
  default backbone, embedding model, top-k retrieval, decoding, context length,
  hardware/time limit, performance result, cost result, and limitation each need
  their own atomic claim.
- Do not write combined setup claims such as "default backbone + embedding model +
  top-k + greedy decoding"; split them into separate claim_units with separate
  evidence quotes.
- Do not combine method design with reported performance, result with cost, ranking
  with causal explanation, or factual setup with critique.
- method_flow contains operations, links and gaps, referring to the same factual claim_units.
  Each operation has scope (the task it performs), operation_claim_id, inputs, outputs and
  conditions. Each role value is {{"name":"a material or constraint from the paper",
  "supporting_claim_ids":["existing factual ID"]}}. An action is not an output object:
  if c1 states that the builder generates profiles from persona seeds, the action can reference
  c1, the input can name "persona seeds" supported by c1, and the output can name "profiles"
  supported by c1. This does not require duplicate facts or authorize a new material/constraint.
  Distinguish dataset construction from system evaluation when the paper has both; use the
  paper's actual task boundaries rather than forcing every paper into those two categories.
  operation_claim_id must itself assert what is done, not only a true setting or statistic;
  scope names that assertion and cannot add an action missing from it. Each named role must
  follow from its supporting assertions, not merely neighboring source text. Return empty
  role lists for unstated inputs/outputs, without invention.
  Keep statistics and results in their existing experiment fields and claims.
  Operations are an unordered inventory. Each link connects distinct operation IDs and has
  from_claim_id, to_claim_id and nonempty
  relation_claim_id for ONE dedicated precedence claim_unit. That fact declares method=
  {{"kind":"precedes","from_claim_id":"operation-id","to_claim_id":"operation-id"}}
  and its own original source evidence. The endpoints must match the link exactly.
  Operation facts declare method={{"kind":"operation","from_claim_id":null,"to_claim_id":null}};
  settings alone use kind="condition" with null endpoints; other claims use method=null.
  The operation fact must describe the action in its text. A role tag is not evidence.
  Do not reuse a fact about a different pair simply because its quoted block also contains
  the whole algorithm. Use the relation fact in the same claim_units ledger, not a second
  paraphrased claim hidden in method_flow. Never infer
  a connection from adjacency, section order or domain convention. Use gaps for unextracted or
  unresolved parts; no fixed step count or linear flow is required. Do not duplicate prose in
  this index or leave the only account of the process in problem_solution.mechanism.
- claim_units must cover the factual, method, experiment, limitation, critique, and essence
  statements you want downstream article generation to use.
- claim_units may include facts, interpretation, novelty, limitation, critique, or essence,
  but every publishable_default=true unit must have exact evidence anchors.
- If a section-level conclusion is broad, put only the precise supported subclaims in
  claim_units and move the broad wording to unsupported_or_rejected_claims.
- Related work must extract concrete representative methods, baselines, datasets, or
  benchmarks explicitly named in the paper. If none are available, write "unknown"; do
  not fill the gap with generic novelty prose. Put named methods into
  related_work.prior_work, not only into area_context.common_baselines.
- Experiments must separate setup, metrics or benchmarks, main findings, cost or
  robustness findings, and known caveats. If the paper does not support one part,
  say "unknown" instead of guessing.
- Experiment and result claims must prefer evidence from experiments_results chunks.
- Limitations must separate paper-explicit limitations, evidence-backed inferred
  weaknesses, and critique that needs external verification.
- Limitations and critique must prefer evidence from limitations_conclusion chunks or
  explicit evaluation evidence. Section-index warnings concern heading detection, not
  missing source text; inspect the complete text rather than inventing a missing section.
- Author-reported superlatives such as best, state-of-the-art, or outperforms must be
  phrased as author-reported claims unless independently verified by supplied evidence.
- Broad essence statements must not bundle multiple contributions. Split them into
  separate atomic claim_units and keep only a narrow essence claim publishable by default.
- Keep analytical section fields as concise research notes, not a second reader-facing
  article. Avoid repeating the same prose across analytical fields. claim_units are the
  factual verification layer; reader_explanation may explain those claims without adding
  facts. Preserve experiment setup, metrics, comparison
  conditions, results, caveats, and limitations in atomic claims; do not omit them or
  merge independent assertions just to shorten the response.
- Every factual or critical claim needs evidence in the same section.
- Every section evidence field must be a non-empty list of objects.
- Every evidence object contains only source_id. Select the block
  establishing the assertion, including experimental qualifiers, not an unrelated nearby line.
- Do not turn author framing into your own conclusion unless evidence supports it.
- Be neutral, sharp, and concrete. Do not flatter the paper.
- Do not draft the final article here; this stage feeds an outline-first synthesis step.
- Return JSON only, without indentation. Do not wrap it in Markdown.

Complete JSON response example (replace all placeholders):
{_reading_response_example(facts_only=facts_only, source_id=source_index.source_ids[0])}
"""


def model_paper_reading(
    artifact: Artifact,
    provider: LLMProvider,
    *,
    model: str,
    area_context: str | None = None,
    language: str = "en",
    packet: PaperReadingPacket | None = None,
) -> PaperReading:
    """Run model-based deep reading and parse the structured result."""

    return model_paper_reading_with_attempts(
        artifact,
        provider,
        model=model,
        area_context=area_context,
        language=language,
        packet=packet,
    ).reading


def model_paper_reading_with_attempts(
    artifact: Artifact,
    provider: LLMProvider,
    *,
    model: str,
    area_context: str | None = None,
    language: str = "en",
    packet: PaperReadingPacket | None = None,
    facts_only: bool = False,
) -> PaperReadingResult:
    """Keep the existing schema retry, but stop unbound explanations without another call."""

    reading_packet = packet or build_reading_packet(artifact)
    if reading_packet.source_text != artifact.text or not artifact.text.strip():
        raise ReaderInputError(
            "reader_input_incomplete", "Reader requires the complete extracted text.", {},
        )
    user_prompt = paper_reading_prompt(
        artifact,
        area_context,
        language=language,
        packet=reading_packet,
        facts_only=facts_only,
    )
    messages = [
        Message(
            role="system",
            content=(
                "You are a skeptical but fair research analyst. "
                f"{_system_language_rule(language)} "
                "Return strict JSON only."
            ),
        ),
        Message(role="user", content=user_prompt),
    ]
    attempts: list[ReaderAttempt] = []
    last_error = ""
    current_messages = messages
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    response_schema = (paper_reading_response_schema(facts_only=facts_only,
                       source_ids=build_source_index(artifact).source_ids)
                       if getattr(provider, "supports_response_schema", False) else None)
    for attempt_index in (1, 2):
        try:
            input_budget = check_reader_input(current_messages, provider, model=model,
                                             response_schema=response_schema)
        except ReaderInputError as exc:
            exc.audit["attempt_index"] = attempt_index
            exc.reader_attempts = [dataclass_to_dict(attempt) for attempt in attempts]
            raise
        excerpt = ""
        validation_error: AnalysisError | None = None

        def parse(content: str) -> PaperReading:
            nonlocal excerpt, validation_error
            excerpt = _response_excerpt(content)
            try:
                return parse_paper_reading(
                    content, artifact, require_explanation_bindings=True,
                    require_source_references=True,
                    require_method_assertions=response_schema is not None,
                )
            except AnalysisError as error:
                validation_error = error
                raise

        try:
            validation = ({"validate_response": parse}
                          if isinstance(provider, CachedLLMProvider) else {})
            if response_schema is None:
                response = provider.complete(current_messages, model=model, **validation)
            else:
                response = provider.complete_with_schema(
                    current_messages, model=model, response_schema=response_schema, **validation,
                )
            reading = parse(response.content)
        except AnalysisError as exc:
            if exc is not validation_error:
                raise  # Provider failures are not Reader-format repair candidates.
            last_error = str(exc)
            attempts.append(
                ReaderAttempt(
                    attempt_index=attempt_index,
                    provider=provider_name,
                    model=model,
                    status="failed",
                    error_message=last_error,
                    response_excerpt=excerpt,
                    input_budget=input_budget,
                )
            )
            if isinstance(exc, (ReaderExplanationError, ReaderContextError, SourceReferenceError)):
                exc.reader_attempts = [dataclass_to_dict(attempt) for attempt in attempts]
                raise
            if response_schema is not None:
                raise AnalysisError(f"Constrained paper reading failed validation: {exc}") from exc
            if attempt_index == 2:
                break
            current_messages = [
                messages[0],
                Message(
                    role="user",
                    content=_retry_paper_reading_prompt(
                        original_prompt=user_prompt,
                        error_message=last_error,
                        response_excerpt=excerpt,
                    ),
                ),
            ]
            continue
        attempts.append(
            ReaderAttempt(
                attempt_index=attempt_index,
                provider=provider_name,
                model=model,
                status="succeeded",
                response_excerpt=excerpt,
                input_budget=input_budget,
            )
        )
        return PaperReadingResult(reading=reading, attempts=attempts)

    raise AnalysisError(f"Paper reading failed after 2 attempts: {last_error}")


def parse_paper_reading(
    raw_json: str, artifact: Artifact, *, require_explanation_bindings: bool = False,
    require_source_references: bool = False,
    require_method_assertions: bool = False,
) -> PaperReading:
    """Parse a reading; fresh model calls require explicit bindings, old records remain readable."""

    payload = resolve_reader_evidence(_load_json_object(raw_json), artifact,
                                     require_references=require_source_references)
    reading_data = payload.get("deep_readings", payload)
    if isinstance(reading_data, list):
        if not reading_data:
            raise AnalysisError("Paper reading JSON contained no deep readings.")
        if len(reading_data) != 1:
            raise AnalysisError("Paper reading JSON must contain exactly one deep reading.")
        reading_data = reading_data[0]
    if not isinstance(reading_data, dict):
        raise AnalysisError("Paper reading JSON must contain an object deep_readings value.")
    if require_source_references:
        flow = reading_data.get("method_flow")
        if not isinstance(flow, dict) or set(flow) != {"operations", "links", "gaps"}:
            raise AnalysisError("Fresh Reader method_flow requires scoped operation records.")

    fallback_evidence = _parse_evidence(
        payload.get("evidence_index", []),
        artifact,
        required=False,
    )
    claim_unit_data = reading_data.get("claim_units") or payload.get("claim_units", [])
    claim_units = _parse_claim_units(claim_unit_data, artifact)
    explicit_ids = {
        item["claim_id"].strip()
        for item in (claim_unit_data if isinstance(claim_unit_data, list) else [])
        if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
    }
    if require_explanation_bindings:
        _require_explanation_bindings(
            reading_data.get("reader_explanation", {}), claim_unit_data, claim_units,
        )
    reading = PaperReading(
        title=str(reading_data.get("title") or artifact.source.title),
        area_context=_parse_area_context(reading_data.get("area_context", {}), artifact),
        problem_solution=_parse_problem_solution(
            reading_data.get("problem_solution", {}),
            artifact,
            fallback_evidence,
        ),
        related_work=_parse_related_work(
            reading_data.get("related_work")
            or reading_data.get("related_work_analysis")
            or {},
            artifact,
            fallback_evidence,
        ),
        limitations=_parse_limitations(
            reading_data.get("limitations", {}),
            artifact,
            fallback_evidence,
        ),
        critical_assessment=_parse_critical_assessment(
            reading_data.get("critical_assessment", {}),
            artifact,
            fallback_evidence,
        ),
        essence=_optional_string(reading_data, "essence", fallback="unknown"),
        plain_language_example=_plain_language_example(reading_data.get("plain_language_example")),
        experiment_summary=_parse_experiment_summary(reading_data),
        experiment_evidence=_parse_experiment_evidence(
            reading_data,
            artifact,
            fallback_evidence,
        ),
        unsupported_or_rejected_claims=list(dict.fromkeys([
            *_string_list(reading_data.get("unsupported_or_rejected_claims")),
            *_string_list(payload.get("unsupported_or_rejected_claims")),
        ])),
        claim_units=claim_units,
        reader_explanation=_parse_reader_explanation(
            reading_data.get("reader_explanation", {}),
        ),
        evaluation_context=_parse_evaluation_context(
            reading_data.get("evaluation_context"), artifact,
            claim_units={unit.claim_id: unit for unit in claim_units
                         if unit.claim_id in explicit_ids},
            require_references=require_source_references,
        ),
        source_url=artifact.source.url,
        experimental_results=parse_experimental_results(
            reading_data.get("experimental_results"), artifact,
            claim_ids={unit.claim_id for unit in claim_units},
        ),
        method_flow=parse_method_flow(reading_data.get("method_flow"),
            claim_ids={unit.claim_id for unit in claim_units if unit.claim_kind == "fact"}),
    )
    _require_anchor(reading.problem_solution.evidence, "problem_solution")
    validate_method_assertions(reading.method_flow,
        {unit.claim_id: unit.method for unit in claim_units},
        require_typed=require_method_assertions)
    _require_anchor(reading.related_work.evidence, "related_work")
    _require_anchor(reading.limitations.evidence, "limitations")
    _require_anchor(reading.critical_assessment.evidence, "critical_assessment")
    return reading


def _require_explanation_bindings(
    value: object, claim_unit_data: object, claim_units: list[ClaimUnit],
) -> None:
    if not isinstance(value, dict):
        raise ReaderExplanationError("expected section arrays of paragraph objects.")
    # Legacy positional IDs support old-file reading, not binding new model prose.
    known_ids = {
        item["claim_id"].strip()
        for item in (claim_unit_data if isinstance(claim_unit_data, list) else [])
        if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
        and item["claim_id"].strip()
    }
    known_ids &= {claim.claim_id for claim in claim_units}
    for section in fields(ReaderExplanation):
        paragraphs = value.get(section.name, [])
        if not isinstance(paragraphs, list):
            raise ReaderExplanationError(f"{section.name} must be a paragraph array.")
        for paragraph in paragraphs:
            if (not isinstance(paragraph, dict)
                    or not isinstance(paragraph.get("text"), str)
                    or not paragraph["text"].strip()):
                raise ReaderExplanationError(f"{section.name} requires nonempty paragraph objects.")
            ids = paragraph.get("supporting_claim_ids")
            if (not isinstance(ids, list) or not ids
                    or any(not isinstance(item, str) or not item.strip() for item in ids)):
                raise ReaderExplanationError(f"{section.name} requires explicit support IDs.")
            normalized = [item.strip() for item in ids]
            if len(set(normalized)) != len(normalized) or not set(normalized) <= known_ids:
                raise ReaderExplanationError(
                    f"{section.name} has duplicate or unknown support IDs."
                )


def _parse_evaluation_context(
    value: object, artifact: Artifact, *, claim_units: dict[str, ClaimUnit],
    require_references: bool = False,
) -> EvaluationContext:
    if value is None:
        if require_references:
            raise ReaderContextError("Fresh output requires the three evaluation dimensions.")
        return EvaluationContext()
    allowed = set(EVALUATION_DIMENSIONS)
    if (not isinstance(value, dict) or set(value) - allowed
            or (require_references and set(value) != allowed)):
        raise ReaderContextError("Use only the three evaluation dimensions.")
    dimensions = {key: value.get(key, []) for key in EVALUATION_DIMENSIONS}
    if any(not isinstance(items, list) for items in dimensions.values()):
        raise ReaderContextError("Each evaluation dimension must be a list.")
    if require_references or any(isinstance(item, str) for items in dimensions.values()
                                 for item in items):
        for dimension, ids in dimensions.items():
            if (any(not isinstance(identity, str) or identity not in claim_units
                    for identity in ids)
                    or len(ids) != len(set(ids))):
                raise ReaderContextError(
                    "References require distinct, explicit existing claim IDs.")
            for index, identity in enumerate(ids):
                unit = claim_units[identity]
                if unit.claim_kind != "fact" or not unit.evidence:
                    raise ReaderContextError(
                        f"evaluation_context.{dimension}[{index}] "
                        f"(claim_id={_response_excerpt(identity, limit=80)!r}, "
                        f"claim_kind={_response_excerpt(unit.claim_kind, limit=48)!r}, "
                        f"evidence_count={len(unit.evidence)}): "
                        "Evaluation references require anchored factual claims."
                    )
        return EvaluationContext(claim_references={key: list(ids)
                                                   for key, ids in dimensions.items()})
    parsed = {}
    for key, entries in dimensions.items():
        parsed[key] = []
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"text", "evidence"}
                    or not isinstance(entry["text"], str) or not entry["text"].strip()):
                raise ReaderContextError("Evaluation context requires text and source evidence.")
            anchors = _parse_evidence(entry["evidence"], artifact, required=True)
            _require_anchor(anchors, "evaluation_context")
            parsed[key].append(EvaluationContextItem(entry["text"], anchors))
    return EvaluationContext(**parsed)


def _retry_paper_reading_prompt(
    *,
    original_prompt: str,
    error_message: str,
    response_excerpt: str,
) -> str:
    """Build a prompt for retrying malformed paper-reading JSON."""

    return f"""Repair the previous paper-reading JSON response.

The previous response could not be parsed or failed required schema validation.
Error: {error_message}

Previous response excerpt:
{response_excerpt}

Return a complete replacement JSON object, not a patch, diff, explanation, or Markdown.
Do not omit required fields. Do not invent new claims to fill missing schema fields.
Keep all ResearchRadar evidence rules unchanged:
- evidence contains exact offered source_id values, never ranges or model-written quotes;
- the program retrieves an exact substring, without changing formulas or source whitespace;
- keep claim_units atomic;
- do not relax quote matching, claim lint, or anchor completeness.

Original task and source packet:
{original_prompt}
"""


def _response_excerpt(value: str, *, limit: int = 800) -> str:
    """Return a short, redacted response excerpt for audit logs."""

    excerpt = redact_text(value.strip())
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[:limit].rstrip() + "..."


def render_deep_reading_report(
    readings: list[PaperReading],
    claims: list[Claim] | None = None,
    *,
    language: str = "en",
) -> str:
    """Render structured paper readings as a human-readable Markdown audit report."""

    labels = _deep_reading_labels(language)
    lines = [f"# {labels['title']}", ""]
    if not readings:
        lines.append(labels["no_readings"])
        return "\n".join(lines).strip() + "\n"
    allowed = _publishable_prefixes(claims)
    for reading in readings:
        lines.extend([f"## {reading.title}", ""])
        lines.extend(_reader_explanation_lines(reading.reader_explanation, labels))
        if _can_render("Essence:", allowed):
            lines.extend([f"**{labels['essence']}:** {reading.essence}", ""])
        if _can_render("Problem:", allowed):
            lines.extend(
                [
                    f"### {labels['problem']}",
                    f"**{labels['core']}:** {reading.problem_solution.problem}",
                    f"- {labels['why_it_matters']}: {reading.problem_solution.why_it_matters}",
                    _list_line(
                        labels["hidden_assumptions"],
                        reading.problem_solution.hidden_assumptions,
                        language=language,
                    ),
                    "",
                ]
            )
        if _can_render("Solution:", allowed):
            lines.extend(
                [
                    f"### {labels['solution']}",
                    f"**{labels['core']}:** {reading.problem_solution.solution}",
                    f"- {labels['mechanism']}: {reading.problem_solution.mechanism}",
                    "",
                ]
            )
        if _can_render("Experiment:", allowed):
            lines.extend(
                [
                    f"### {labels['experiments']}",
                    (
                        f"**{labels['core']}:** "
                        f"{reading.experiment_summary or labels['no_experiment']}"
                    ),
                    "",
                ]
            )
        if reading.plain_language_example:
            lines.extend(
                [
                    f"### {labels['plain_example']}",
                    reading.plain_language_example,
                    "",
                ]
            )
        if _can_render("Related work:", allowed):
            lines.extend(
                [
                    f"### {labels['related_work']}",
                    f"**{labels['core']}:** {reading.related_work.novelty}",
                    _list_line(
                        labels["prior_work"],
                        reading.related_work.prior_work,
                        language=language,
                    ),
                    f"- {labels['repackaging_risk']}: {reading.related_work.repackaging_risk}",
                    "",
                ]
            )
        if _can_render("Limitations:", allowed):
            explicit = reading.limitations.explicit_limitations
            inferred = reading.limitations.inferred_weaknesses
            lines.extend(
                [
                    f"### {labels['limitations']}",
                    f"**{labels['core']}:** {_first_or_none(explicit, labels['no_limitations'])}",
                    _list_line(labels["explicit_limitations"], explicit, language=language),
                    _list_line(labels["inferred_weaknesses"], inferred, language=language),
                    _list_line(
                        labels["future_work"],
                        reading.limitations.future_work,
                        language=language,
                    ),
                    "",
                ]
            )
        if _can_render("Critical assessment:", allowed):
            lines.extend(
                [
                    f"### {labels['critical']}",
                    f"**{labels['core']}:** {reading.critical_assessment.bottom_line}",
                    (
                        f"- {labels['overclaiming_risk']}: "
                        f"{reading.critical_assessment.overclaiming_risk}"
                    ),
                    _list_line(
                        labels["weak_evaluations"],
                        reading.critical_assessment.weak_evaluations,
                        language=language,
                    ),
                    _list_line(
                        labels["missing_ablations"],
                        reading.critical_assessment.missing_ablations,
                        language=language,
                    ),
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def reading_to_dict(reading: PaperReading) -> dict[str, object]:
    """Convert a paper reading to a JSON-friendly dictionary."""

    return {**dataclass_to_dict(reading),
            "evaluation_context": evaluation_context_payload(reading.evaluation_context)}


def _publishable_prefixes(claims: list[Claim] | None) -> set[str] | None:
    if claims is None:
        return None
    prefixes = set()
    for claim in claims:
        if not claim.is_publishable():
            continue
        prefix, separator, _ = claim.text.partition(":")
        if separator:
            prefixes.add(f"{prefix.casefold()}:")
    return prefixes


def _can_render(prefix: str, allowed: set[str] | None) -> bool:
    return allowed is None or prefix.casefold() in allowed


def _reader_explanation_lines(
    explanation: ReaderExplanation,
    labels: dict[str, str],
) -> list[str]:
    sections = [
        ("opening_context", labels["opening_context"]),
        ("core_thesis", labels["core_thesis"]),
        ("problem_walkthrough", labels["problem"]),
        ("solution_walkthrough", labels["solution"]),
        ("experiment_interpretation", labels["experiments"]),
        ("related_work_context", labels["related_work"]),
        ("limitations_discussion", labels["limitations"]),
        ("plain_language_story", labels["plain_example"]),
        ("reader_takeaway", labels["reader_takeaway"]),
    ]
    lines: list[str] = []
    for key, label in sections:
        text = "\n\n".join(
            paragraph.text
            for paragraph in getattr(explanation, key, [])
            if paragraph.text.strip()
        )
        if text:
            lines.extend([f"### {label}", text, ""])
    return lines


def _list_line(label: str, values: list[str], *, language: str = "en") -> str:
    if not values:
        empty = "未捕捉到" if language == "zh" else "none captured"
        return f"- {label}: {empty}"
    return f"- {label}: " + "; ".join(values)


def _deep_reading_labels(language: str) -> dict[str, str]:
    if language == "zh":
        return {
            "title": "深度阅读报告",
            "no_readings": "没有生成深度阅读结果。",
            "essence": "本质判断",
            "problem": "问题与动机",
            "solution": "方法与机制",
            "experiments": "实验与评估",
            "plain_example": "通俗例子",
            "related_work": "相关工作",
            "limitations": "局限与未来工作",
            "critical": "中立批判",
            "opening_context": "背景知识速读",
            "core_thesis": "核心判断",
            "reader_takeaway": "读者 takeaway",
            "core": "核心判断",
            "why_it_matters": "为什么重要",
            "hidden_assumptions": "隐藏假设",
            "mechanism": "机制",
            "no_experiment": "没有捕捉到实验摘要。",
            "prior_work": "已有工作",
            "repackaging_risk": "重新包装风险",
            "no_limitations": "没有捕捉到明确局限。",
            "explicit_limitations": "作者明确局限",
            "inferred_weaknesses": "推断弱点",
            "future_work": "未来工作",
            "overclaiming_risk": "过度声称风险",
            "weak_evaluations": "薄弱评估",
            "missing_ablations": "缺失消融",
        }
    return {
        "title": "Deep Reading Report",
        "no_readings": "No deep readings were produced.",
        "essence": "Essence",
        "problem": "Problems and Motivation",
        "solution": "Solution",
        "experiments": "Experiments",
        "plain_example": "Plain-language Example",
        "related_work": "Related Work",
        "limitations": "Limitations and Future Work",
        "critical": "Critical Assessment",
        "opening_context": "Opening Context",
        "core_thesis": "Core Thesis",
        "reader_takeaway": "Reader Takeaway",
        "core": "Core",
        "why_it_matters": "Why it matters",
        "hidden_assumptions": "Hidden assumptions",
        "mechanism": "Mechanism",
        "no_experiment": "No experiment summary captured.",
        "prior_work": "Prior work",
        "repackaging_risk": "Repackaging risk",
        "no_limitations": "No explicit limitations captured.",
        "explicit_limitations": "Explicit limitations",
        "inferred_weaknesses": "Inferred weaknesses",
        "future_work": "Future work",
        "overclaiming_risk": "Overclaiming risk",
        "weak_evaluations": "Weak evaluations",
        "missing_ablations": "Missing ablations",
    }


def _system_language_rule(language: str) -> str:
    if language == "zh":
        return (
            "All analytical JSON string values must be Simplified Chinese; only evidence "
            "quote strings may preserve original source wording."
        )
    return "All analytical JSON string values must be English."


def _first_or_none(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def reading_to_claims(
    reading: PaperReading, *, include_context_claims: bool = False,
) -> list[Claim]:
    """Convert a structured paper reading into evidence-bound claims."""

    if reading.claim_units:
        return [
            *_claim_units_to_claims(reading.claim_units),
            *(_context_claims(reading) if include_context_claims else []),
            *[
                Claim(
                    text=text,
                    status=ClaimStatus.UNSUPPORTED,
                    rationale="Rejected during paper reading.",
                    metadata={"paper_reading": {"source": "unsupported_or_rejected_claims"}},
                )
                for text in reading.unsupported_or_rejected_claims
            ],
        ]
    return [
        _claim(
            f"Problem: {reading.problem_solution.problem}",
            reading.problem_solution.evidence,
            "Paper problem statement.",
        ),
        _claim(
            f"Solution: {reading.problem_solution.solution}",
            reading.problem_solution.evidence,
            "Paper solution summary.",
        ),
        _claim(
            f"Related work: {reading.related_work.novelty}",
            reading.related_work.evidence,
            "Novelty assessment against related work.",
        ),
        *(
            [
                _claim(
                    f"Experiment: {reading.experiment_summary}",
                    reading.experiment_evidence,
                    "Experiment or evaluation summary.",
                )
            ]
            if reading.experiment_summary
            else []
        ),
        *(
            [
                _claim(
                    f"Limitations: {'; '.join(reading.limitations.explicit_limitations)}",
                    reading.limitations.evidence,
                    "Explicit limitations reported or supported by the paper.",
                )
            ]
            if reading.limitations.explicit_limitations
            else []
        ),
        _claim(
            f"Critical assessment: {reading.critical_assessment.bottom_line}",
            reading.critical_assessment.evidence,
            "Neutral critique backed by evaluation or method evidence.",
        ),
        *(
            [
                _claim(
                    f"Essence: {reading.essence}",
                    _combined_evidence(reading),
                    "One-sentence essence of the paper.",
                )
            ]
            if reading.essence != "unknown"
            else []
        ),
        *[
            Claim(
                text=text,
                status=ClaimStatus.UNSUPPORTED,
                rationale="Rejected during paper reading.",
            )
            for text in reading.unsupported_or_rejected_claims
        ],
    ]


def _context_claims(reading: PaperReading) -> list[Claim]:
    """Project anchored method/conditions into candidates, never into approved facts."""
    proposed = ([] if method_claim_ids(reading.method_flow) else [
        ("problem_solution.mechanism", "solution", reading.problem_solution.mechanism,
         reading.problem_solution.evidence)])
    if reading.evaluation_context.claim_references is None:
        proposed.extend((f"evaluation_context.{dimension}", "experiment", item.text, item.evidence)
                        for dimension in EVALUATION_DIMENSIONS
                        for item in getattr(reading.evaluation_context, dimension))
    def signature(text: str, evidence: list[EvidenceAnchor]) -> str:
        return json.dumps({"text": text.strip(), "evidence": [
            {"source_url": a.source_url, "quote": a.quote, "location": a.location}
            for a in evidence]}, ensure_ascii=False, sort_keys=True)
    seen = {signature(unit.text, unit.evidence) for unit in reading.claim_units}
    existing_ids = {unit.claim_id for unit in reading.claim_units}
    claims = []
    for origin, section, text, evidence in proposed:
        identity = signature(text, evidence)
        if not text.strip() or not evidence or identity in seen:
            continue
        digest = hashlib.sha256((reading.source_url + "\0" + origin + "\0" + identity).encode())
        claim_id = "context-" + digest.hexdigest()[:16]
        if claim_id in existing_ids:
            raise AnalysisError("Context claim identity conflicts with an existing claim.")
        existing_ids.add(claim_id)
        seen.add(identity)
        unit = ClaimUnit(section=section, claim_kind="fact", text=text.strip(), evidence=evidence,
                         claim_id=claim_id, publishable_default=bool(reading.source_url) and all(
                             a.source_url == reading.source_url for a in evidence))
        claim = _claim_units_to_claims([unit])[0]
        claims.append(replace(claim, metadata={"paper_reading": {
            **claim.metadata["paper_reading"], "source": "reading_context", "context_field": origin,
        }}))
    return claims


def _claim_units_to_claims(units: list[ClaimUnit]) -> list[Claim]:
    claims = []
    for unit in units:
        status, status_reason = _claim_unit_initial_status(unit)
        claims.append(
            Claim(
                text=_claim_unit_text(unit),
                status=status,
                evidence=unit.evidence,
                rationale="Atomic paper-reading claim.",
                metadata={
                    "paper_reading": {
                        "source": "claim_units",
                        "claim_id": unit.claim_id,
                        "section": unit.section,
                        "claim_kind": unit.claim_kind,
                        "publishable_default": unit.publishable_default,
                        "status_reason": status_reason,
                        **({"method": dataclass_to_dict(unit.method)} if unit.method else {}),
                    },
                },
            )
        )
    return claims


def _claim_unit_initial_status(unit: ClaimUnit) -> tuple[ClaimStatus, str]:
    if not unit.evidence:
        return ClaimStatus.UNSUPPORTED, "missing evidence"
    if not unit.publishable_default:
        return ClaimStatus.NEEDS_REVIEW, "not publishable by default"
    lint_reason = _claim_lint_reason(unit)
    if lint_reason is not None:
        return ClaimStatus.NEEDS_REVIEW, lint_reason
    if _requires_author_report_attribution(unit.text):
        return ClaimStatus.NEEDS_REVIEW, "author-reported superlative needs attribution"
    if _bundles_multiple_essence_claims(unit):
        return ClaimStatus.NEEDS_REVIEW, "essence bundles multiple claims"
    if _requires_external_verification(unit):
        return ClaimStatus.NEEDS_REVIEW, "claim requires external verification"
    return ClaimStatus.SUPPORTED, "supported by supplied evidence"


def _claim_lint_reason(unit: ClaimUnit) -> str | None:
    text = _strip_claim_prefix(unit.text).casefold()
    setup_facets = [
        _has_any(text, ("backbone", "llm backbone")),
        _has_any(text, ("embedding model", "sentence-transformer", "all-minilm")),
        _has_any(text, ("top-k", "top k", "k=10", "retrieval uses k")),
        _has_any(text, ("greedy decoding", "decoding")),
        _has_any(text, ("context length", "context window")),
        _has_any(text, ("gpu", "a100", "two days", "time limit")),
    ]
    if sum(1 for matched in setup_facets if matched) > 1:
        return "claim too broad; split setup facets"
    # Method verbs and scoring vocabulary alone do not establish an empirical result.
    has_result = _has_result_marker(text)
    has_cost = _has_any(
        text,
        (
            "token cost",
            "tokens per",
            "cost",
            "overhead",
            "latency",
            "computational overhead",
        ),
    )
    if has_result and has_cost:
        return "claim too broad; split result and cost"
    has_ranking = _has_any(text, ("top-performing", "competitive", "outperform", "best"))
    has_causal = _has_any(text, ("due to", "attributed", "may explain", "because", "likely"))
    if has_ranking and has_causal:
        return "claim too broad; split ranking and causal explanation"
    has_fact_setup = _has_any(text, ("benchmark", "metric", "dataset", "backbone"))
    has_critique = _has_any(text, ("may not", "does not reflect", "not reflect", "limiting"))
    if has_fact_setup and has_critique:
        return "claim too broad; split fact and critique"
    return None


def _strip_claim_prefix(text: str) -> str:
    return re.sub(r"^\s*[A-Za-z _-]+:\s*", "", text).strip()


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_result_marker(text: str) -> bool:
    return _has_any(
        text,
        (
            "performance",
            "result",
            "outperform",
            "outperforms",
            "best",
            "improvement",
            "achieves",
            "f1",
            "bleu",
        ),
    )


def _requires_author_report_attribution(text: str) -> bool:
    normalized = text.casefold()
    normalized = re.sub(
        r"\bbest(?:\s+of\s+|-of-)(?:[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"\s+(?:rounds?|runs?|trials?)\b",
        "trial selection",
        normalized,
    )
    superlatives = (
        "best",
        "state-of-the-art",
        "sota",
        "outperform",
        "outperforms",
        "outperformed",
    )
    if not any(term in normalized for term in superlatives):
        return False
    attribution_markers = (
        "author reports",
        "authors report",
        "author-reported",
        "paper reports",
        "paper claims",
        "the paper reports",
        "the paper claims",
        "reported by the authors",
        "claimed by the authors",
    )
    return not any(marker in normalized for marker in attribution_markers)


def _bundles_multiple_essence_claims(unit: ClaimUnit) -> bool:
    if unit.section.strip().casefold() != "essence":
        return False
    normalized = unit.text.casefold()
    contribution_verbs = ("proposes", "introduces", "compares", "evaluates", "reports")
    verb_count = sum(1 for verb in contribution_verbs if verb in normalized)
    return verb_count >= 2


def _requires_external_verification(unit: ClaimUnit) -> bool:
    if unit.claim_kind.strip().casefold() not in {"critique", "limitation"}:
        return False
    normalized = unit.text.casefold()
    external_markers = (
        "independent replication",
        "externally validated",
        "external validation",
        "not replicated",
    )
    return any(marker in normalized for marker in external_markers)


def _claim_unit_text(unit: ClaimUnit) -> str:
    text = unit.text.strip()
    prefix = _claim_unit_prefix(unit.section)
    if text.casefold().startswith(prefix.casefold()):
        return text
    return f"{prefix} {text}"


def _claim_unit_prefix(section: str) -> str:
    normalized = section.strip().casefold().replace("-", "_").replace(" ", "_")
    prefixes = {
        "problem": "Problem:",
        "problem_solution": "Problem:",
        "motivation": "Problem:",
        "solution": "Solution:",
        "mechanism": "Solution:",
        "experiment": "Experiment:",
        "experiments": "Experiment:",
        "evaluation": "Experiment:",
        "related_work": "Related work:",
        "related_work_analysis": "Related work:",
        "novelty": "Related work:",
        "limitations": "Limitations:",
        "limitation": "Limitations:",
        "future_work": "Limitations:",
        "critical": "Critical assessment:",
        "critique": "Critical assessment:",
        "critical_assessment": "Critical assessment:",
        "essence": "Essence:",
    }
    return prefixes.get(normalized, f"{section.strip() or 'Claim'}:")


def validate_paper_reading(
    reading: PaperReading,
    artifact: Artifact | None = None,
    *,
    include_context_claims: bool = False,
) -> tuple[list[Claim], list[ReviewFinding]]:
    """Validate that paper-reading claims are evidence-backed before publication."""

    claims, findings = enforce_evidence_policy(reading_to_claims(
        reading, include_context_claims=include_context_claims,
    ))
    findings.extend(_claim_lint_findings(claims))
    if artifact is None:
        return claims, findings
    checked_claims: list[Claim] = []
    for claim in claims:
        if not claim.is_publishable():
            checked_claims.append(claim)
            continue
        valid_evidence = [
            anchor
            for anchor in claim.evidence
            if find_quote(anchor.quote, artifact.text) is not None
        ]
        if len(valid_evidence) == len(claim.evidence):
            checked_claims.append(claim)
            continue
        missing_count = len(claim.evidence) - len(valid_evidence)
        if valid_evidence:
            checked_claims.append(
                replace(
                    claim,
                    evidence=valid_evidence,
                    metadata={
                        **claim.metadata,
                        "evidence_validation": {
                            "status": "partial",
                            "missing_anchor_count": missing_count,
                        },
                    },
                )
            )
            findings.append(
                ReviewFinding(
                    severity="warning",
                    message="Some evidence anchors were not found in the ingested text.",
                    claim_text=claim.text,
                    metadata={
                        "kind": "evidence_anchor_unmatched",
                        "missing_anchor_count": missing_count,
                    },
                )
            )
            continue
        checked_claims.append(
            replace(
                claim,
                status=ClaimStatus.UNSUPPORTED,
                evidence=[],
                metadata={
                    **claim.metadata,
                    "evidence_validation": {
                        "status": "failed",
                        "missing_anchor_count": missing_count,
                    },
                },
            )
        )
        findings.append(
            ReviewFinding(
                severity="error",
                message="No evidence anchors for this claim were found in the ingested text.",
                claim_text=claim.text,
                metadata={
                    "kind": "evidence_anchor_unmatched",
                    "missing_anchor_count": missing_count,
                },
            )
        )
    return checked_claims, findings


def _claim_lint_findings(claims: list[Claim]) -> list[ReviewFinding]:
    findings = []
    for claim in claims:
        reason = str(claim.metadata.get("paper_reading", {}).get("status_reason") or "")
        if not reason.startswith("claim too broad"):
            continue
        findings.append(
            ReviewFinding(
                severity="warning",
                message=f"Claim lint requires splitting: {reason}",
                claim_text=claim.text,
                metadata={"kind": "claim_lint", "reason": reason},
            )
        )
    return findings


def heuristic_paper_reading(artifact: Artifact) -> PaperReading:
    """Build a conservative reading from labeled fixture-like text."""

    text = artifact.text
    anchor = EvidenceAnchor(
        source_url=artifact.source.url,
        source_title=artifact.source.title,
        quote=text[:500],
        location="extracted text",
        confidence=0.8,
    )
    return PaperReading(
        title=artifact.source.title,
        area_context=AreaContext(
            background=_section(text, "Background") or "Area background is not established.",
            active_questions=[_section(text, "Question")] if _section(text, "Question") else [],
            common_baselines=[_section(text, "Baseline")] if _section(text, "Baseline") else [],
            evidence=[anchor],
        ),
        problem_solution=ProblemSolution(
            problem=_section(text, "Problem") or "Problem is not clearly stated.",
            why_it_matters=_section(text, "Motivation") or "Motivation is not clearly stated.",
            hidden_assumptions=[_section(text, "Assumption")]
            if _section(text, "Assumption")
            else [],
            solution=_section(text, "Solution") or "Solution is not clearly stated.",
            mechanism=_section(text, "Mechanism") or "Mechanism is not clearly stated.",
            evidence=[anchor],
        ),
        related_work=RelatedWorkAssessment(
            prior_work=[_section(text, "Related Work")] if _section(text, "Related Work") else [],
            novelty=_section(text, "Novelty") or "Novelty is not established.",
            repackaging_risk=_section(text, "Repackaging Risk") or "Repackaging risk is unknown.",
            evidence=[anchor],
        ),
        limitations=LimitationAssessment(
            explicit_limitations=[_section(text, "Limitation")]
            if _section(text, "Limitation")
            else [],
            inferred_weaknesses=[_section(text, "Weakness")] if _section(text, "Weakness") else [],
            evidence=[anchor],
            future_work=[_section(text, "Future Work")] if _section(text, "Future Work") else [],
        ),
        critical_assessment=CriticalAssessment(
            overclaiming_risk=_section(text, "Overclaiming") or "Overclaiming risk is unknown.",
            weak_evaluations=[_section(text, "Weak Evaluation")]
            if _section(text, "Weak Evaluation")
            else [],
            missing_ablations=[_section(text, "Missing Ablation")]
            if _section(text, "Missing Ablation")
            else [],
            bottom_line=(
                _section(text, "Critical Bottom Line")
                or "Critical bottom line is unknown."
            ),
            evidence=[anchor],
        ),
        experiment_summary=_section(text, "Experiment"),
        experiment_evidence=[anchor] if _section(text, "Experiment") else [],
        essence=_section(text, "Essence") or "The paper's essence is not established.",
        plain_language_example=_section(text, "Example") or "No grounded example is available.",
        unsupported_or_rejected_claims=[
            _section(text, "Unsupported Claim")
        ]
        if _section(text, "Unsupported Claim")
        else [],
    )


def _claim(text: str, evidence: list[EvidenceAnchor], rationale: str) -> Claim:
    status = ClaimStatus.SUPPORTED if evidence else ClaimStatus.UNSUPPORTED
    return Claim(text=text, status=status, evidence=evidence, rationale=rationale)


def _combined_evidence(reading: PaperReading) -> list[EvidenceAnchor]:
    return [
        *reading.problem_solution.evidence,
        *reading.related_work.evidence,
        *reading.limitations.evidence,
        *reading.critical_assessment.evidence,
    ]


def _section(text: str, label: str) -> str:
    prefix = f"{label}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix.lower()):
            return stripped[len(prefix) :].strip()
    return ""


def _load_json_object(raw_json: str) -> dict[str, object]:
    text = raw_json.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    text = _extract_json_object_text(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            f"Paper reading response was not valid JSON (line {exc.lineno}, column {exc.colno})."
        ) from exc
    if not isinstance(payload, dict):
        raise AnalysisError("Paper reading JSON must be an object.")
    return payload


def _extract_json_object_text(text: str) -> str:
    if text.startswith(("{", "[")):
        return text
    start = text.find("{")
    array_start = text.find("[")
    if array_start >= 0 and (start < 0 or array_start < start):
        return text[array_start:]
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


def _parse_area_context(value: object, artifact: Artifact) -> AreaContext:
    data = _mapping(value, "area_context")
    return AreaContext(
        background=_optional_string(
            data,
            "background",
            aliases=("area_background", "background_context", "context"),
            fallback="unknown",
        ),
        active_questions=_string_list(data.get("active_questions", [])),
        common_baselines=_string_list(data.get("common_baselines", [])),
        evidence=_parse_evidence(data.get("evidence", []), artifact, required=False),
    )


def _parse_problem_solution(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> ProblemSolution:
    data = _mapping(value, "problem_solution")
    return ProblemSolution(
        problem=_required_string(data, "problem"),
        why_it_matters=_required_string(data, "why_it_matters"),
        hidden_assumptions=_string_list(data.get("hidden_assumptions", [])),
        solution=_required_string(data, "solution"),
        mechanism=_required_string(data, "mechanism"),
        evidence=_section_evidence(data, artifact, fallback_evidence),
    )


def _parse_related_work(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> RelatedWorkAssessment:
    data = _mapping(value, "related_work")
    return RelatedWorkAssessment(
        prior_work=_string_list(data.get("prior_work", [])),
        novelty=_required_string(data, "novelty"),
        repackaging_risk=_required_string(data, "repackaging_risk"),
        evidence=_section_evidence(data, artifact, fallback_evidence),
    )


def _parse_limitations(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> LimitationAssessment:
    data = _mapping(value, "limitations")
    return LimitationAssessment(
        explicit_limitations=_string_list(data.get("explicit_limitations", [])),
        inferred_weaknesses=_string_list(data.get("inferred_weaknesses", [])),
        evidence=_section_evidence(data, artifact, fallback_evidence),
        future_work=_string_list(data.get("future_work", [])),
    )


def _parse_critical_assessment(
    value: object,
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> CriticalAssessment:
    data = _mapping(value, "critical_assessment")
    return CriticalAssessment(
        overclaiming_risk=_required_string(data, "overclaiming_risk"),
        weak_evaluations=_string_list(data.get("weak_evaluations", [])),
        missing_ablations=_string_list(data.get("missing_ablations", [])),
        bottom_line=_required_string(data, "bottom_line"),
        evidence=_section_evidence(data, artifact, fallback_evidence),
    )


def _parse_experiment_summary(data: dict[str, object]) -> str:
    experiments = data.get("experiments") or data.get("experiment")
    if isinstance(experiments, dict):
        summary = (
            experiments.get("summary")
            or experiments.get("evaluation")
            or experiments.get("headline_results")
        )
        if isinstance(summary, dict):
            return _joined_experiment_parts(summary)
        direct_summary = str(summary or "").strip()
        if direct_summary:
            return direct_summary
        return _joined_experiment_parts(experiments)
    return str(data.get("experiment_summary") or "").strip()


def _joined_experiment_parts(experiments: dict[str, object]) -> str:
    parts = []
    labels = {
        "setup": "Setup",
        "metrics_benchmarks": "Metrics/benchmarks",
        "metrics_or_benchmarks": "Metrics/benchmarks",
        "main_findings": "Main findings",
        "cost_robustness_findings": "Cost/robustness findings",
        "cost_or_robustness_findings": "Cost/robustness findings",
        "known_caveats": "Known caveats",
    }
    for key, label in labels.items():
        text = _string_or_joined_list(experiments.get(key))
        if text:
            parts.append(f"{label}: {text}")
    return " ".join(parts)


def _string_or_joined_list(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(_readable_text(item) for item in value if _readable_text(item))
    return str(value or "").strip()


def _plain_language_example(value: object) -> str:
    if isinstance(value, dict):
        text = value.get("text") or value.get("example") or value.get("summary")
        return str(text or "").strip()
    return str(value or "").strip()


def _parse_experiment_evidence(
    data: dict[str, object],
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> list[EvidenceAnchor]:
    experiments = data.get("experiments") or data.get("experiment")
    if isinstance(experiments, dict):
        return _section_evidence(experiments, artifact, fallback_evidence)
    return _parse_evidence(data.get("experiment_evidence", []), artifact, required=False)


def _parse_reader_explanation(value: object) -> ReaderExplanation:
    data = value if isinstance(value, dict) else {}
    return ReaderExplanation(
        opening_context=_optional_explanation(data, "opening_context"),
        core_thesis=_optional_explanation(data, "core_thesis"),
        problem_walkthrough=_optional_explanation(data, "problem_walkthrough"),
        solution_walkthrough=_optional_explanation(data, "solution_walkthrough"),
        experiment_interpretation=_optional_explanation(data, "experiment_interpretation"),
        related_work_context=_optional_explanation(data, "related_work_context"),
        limitations_discussion=_optional_explanation(data, "limitations_discussion"),
        plain_language_story=_optional_explanation(data, "plain_language_story"),
        reader_takeaway=_optional_explanation(data, "reader_takeaway"),
    )


def _optional_explanation(
    data: dict[object, object],
    key: str,
) -> list[ReaderExplanationParagraph]:
    value = data.get(key)
    items = value if isinstance(value, list) else [value]
    paragraphs: list[ReaderExplanationParagraph] = []
    for item in items:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            raw_supporting_claim_ids = item.get("supporting_claim_ids", [])
            if raw_supporting_claim_ids is None:
                raw_supporting_claim_ids = []
            if not isinstance(raw_supporting_claim_ids, list):
                raise AnalysisError(
                    "Reader explanation paragraph supporting_claim_ids must be a list."
                )
            supporting_claim_ids = [
                str(claim_id).strip()
                for claim_id in raw_supporting_claim_ids
                if str(claim_id).strip()
            ]
        else:
            text = str(item or "").strip()
            supporting_claim_ids = []
        if text:
            paragraphs.append(
                ReaderExplanationParagraph(
                    text=text,
                    supporting_claim_ids=supporting_claim_ids,
                )
            )
    return paragraphs


def _parse_claim_units(value: object, artifact: Artifact) -> list[ClaimUnit]:
    if not isinstance(value, list):
        return []
    units: list[ClaimUnit] = []
    seen_claim_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        claim_kind = str(item.get("claim_kind") or item.get("kind") or "").strip()
        text = str(item.get("text") or item.get("claim") or "").strip()
        if not section or not claim_kind or not text:
            continue
        claim_id = str(item.get("claim_id") or "").strip()
        if not claim_id:
            claim_id = f"legacy-c{index + 1}"
        if claim_id in seen_claim_ids:
            raise AnalysisError(f"Paper reading contains duplicate claim_id: {claim_id}")
        seen_claim_ids.add(claim_id)
        evidence = _parse_evidence(item.get("evidence", []), artifact, required=False)
        publishable_default = item.get("publishable_default", True)
        units.append(
            ClaimUnit(
                section=section,
                claim_kind=claim_kind,
                text=text,
                evidence=evidence,
                claim_id=claim_id,
                publishable_default=_bool_value(publishable_default),
                method=parse_method_assertion(item.get("method")),
            )
        )
    return units


def _section_evidence(
    data: dict[str, object],
    artifact: Artifact,
    fallback_evidence: list[EvidenceAnchor],
) -> list[EvidenceAnchor]:
    anchors = _parse_evidence(
        data.get("evidence")
        or data.get("evidence_anchors")
        or data.get("citations")
        or [],
        artifact,
        required=False,
    )
    return anchors or fallback_evidence


def _parse_evidence(
    value: object,
    artifact: Artifact,
    *,
    required: bool,
) -> list[EvidenceAnchor]:
    if not isinstance(value, list):
        if required:
            raise AnalysisError("Evidence must be a list.")
        return []
    anchors: list[EvidenceAnchor] = []
    for item in value:
        if isinstance(item, str):
            quote = item.strip()
            if quote:
                anchors.append(
                    EvidenceAnchor(
                        source_url=artifact.source.url,
                        source_title=artifact.source.title,
                        quote=quote,
                        location="model anchor",
                        confidence=0.7,
                    )
                )
            continue
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or item.get("snippet") or item.get("anchor") or "").strip()
        if not quote:
            continue
        anchors.append(
            EvidenceAnchor(
                source_url=artifact.source.url,
                source_title=artifact.source.title,
                quote=quote,
                location=str(item.get("location") or item.get("section") or "model anchor"),
                confidence=float(item.get("confidence", 0.7)),
            )
        )
    if required and not anchors:
        raise AnalysisError("Expected at least one evidence anchor.")
    return anchors


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AnalysisError(f"Paper reading field must be an object: {name}")
    return value


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AnalysisError(f"Paper reading field is required: {key}")
    return value.strip()


def _optional_string(
    data: dict[str, object],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    fallback: str = "",
) -> str:
    for candidate in (key, *aliases):
        value = data.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _readable_text(item))]


def _readable_text(value: object) -> str:
    if isinstance(value, dict):
        if "name" in value and "reported_profile" in value:
            return f"{value['name']}: {value['reported_profile']}".strip()
        for key in ("text", "name", "summary", "claim"):
            if key in value and str(value[key]).strip():
                return str(value[key]).strip()
        return ""
    return str(value).strip()


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() not in {"false", "0", "no"}
    return bool(value)


def _require_anchor(evidence: list[EvidenceAnchor], section: str) -> None:
    if not evidence:
        raise AnalysisError(f"Paper reading section has no evidence anchors: {section}")
