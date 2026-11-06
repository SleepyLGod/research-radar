"""Canonical single-paper output shape for explicitly capable endpoints."""

from __future__ import annotations


def paper_reading_response_schema(
    *, facts_only: bool = False, source_ids: list[str] | None = None,
) -> dict[str, object]:
    """Return a fresh strict JSON Schema; requesting it is not proof of enforcement."""
    text = {"type": "string"}

    def array(item: dict[str, object]) -> dict[str, object]:
        return {"type": "array", "items": item}

    def obj(**properties: dict[str, object]) -> dict[str, object]:
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    texts = array(text)
    source_id = {"type": "string", "pattern": r"^b[0-9a-f]{16}:[1-9][0-9]*$"}
    if source_ids is not None:
        if not source_ids or len(set(source_ids)) != len(source_ids):
            raise ValueError("Reader schema requires distinct offered source IDs.")
        source_id = {"type": "string", "enum": list(source_ids)}
    evidence = array(obj(source_id={"$ref": "#/$defs/source_id"}))
    paragraph = obj(text=text, supporting_claim_ids=texts)
    explanation = obj(**{key: array(paragraph) for key in (
        "opening_context", "core_thesis", "problem_walkthrough", "solution_walkthrough",
        "experiment_interpretation", "related_work_context", "limitations_discussion",
        "plain_language_story", "reader_takeaway",
    )})
    if facts_only:
        explanation = obj()
    context = obj(**{key: texts for key in (
        "data_construction", "available_inputs", "outcome_measurement",
    )})
    role_values = array(obj(name=text, supporting_claim_ids=texts))
    method_flow = obj(operations=array(obj(scope=text, operation_claim_id=text,
        inputs=role_values, outputs=role_values, conditions=role_values)),
        links=array(obj(from_claim_id=text, to_claim_id=text, relation_claim_id=text)),
        gaps=texts)
    method_assertion = {"anyOf": [
        {"type": "null"},
        obj(kind={"type": "string", "enum": ["operation", "condition", "precedes"]},
            from_claim_id={"type": ["string", "null"]},
            to_claim_id={"type": ["string", "null"]}),
    ]}
    reading = obj(
        title=text,
        area_context=obj(background=text, active_questions=texts, common_baselines=texts,
                         evidence=evidence),
        problem_solution=obj(problem=text, why_it_matters=text, hidden_assumptions=texts,
                             solution=text, mechanism=text, evidence=evidence),
        related_work=obj(prior_work=texts, novelty=text, repackaging_risk=text, evidence=evidence),
        experiments=obj(summary=text, evidence=evidence),
        experimental_results=array(obj(
            result_id=text, question=text, conditions=texts, metric=text,
            observations=array(obj(subject=text, value=text)), comparison_scope=texts,
            uncertainty=texts, supporting_claim_ids=texts, evidence=evidence,
            source_kind={"type": "string", "enum": ["text", "table", "figure"]},
            source_label=text, physical_page={"type": ["integer", "null"], "minimum": 1},
            binding_status={"type": "string",
                            "enum": ["text_bound", "unresolved", "source_conflict"]},
        )),
        evaluation_context=context,
        method_flow=method_flow,
        limitations=obj(explicit_limitations=texts, inferred_weaknesses=texts, future_work=texts,
                        evidence=evidence),
        critical_assessment=obj(overclaiming_risk=text, weak_evaluations=texts,
                                missing_ablations=texts, bottom_line=text, evidence=evidence),
        plain_language_example=text, essence=text,
        claim_units=array(obj(claim_id=text, section=text, claim_kind=text, text=text,
                              evidence=evidence, publishable_default={"type": "boolean"},
                              method=method_assertion)),
        reader_explanation=explanation,
    )
    return {**obj(deep_readings={**array(reading), "minItems": 1, "maxItems": 1},
                  unsupported_or_rejected_claims=texts), "$defs": {"source_id": source_id}}
