"""A source-bound method index over existing claims, not a second set of assertions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace

from research_radar.exceptions import AnalysisError
from research_radar.models import Claim, dataclass_to_dict


@dataclass(frozen=True)
class MethodReview:
    """Decision bound to a proposed method structure and its exact source facts."""

    status: str
    reason: str
    binding_sha256: str


@dataclass(frozen=True)
class MethodAssertion:
    """A declared operation, condition or directed order fact in the claim ledger."""

    kind: str
    from_claim_id: str | None = None
    to_claim_id: str | None = None


def parse_method_assertion(value: object) -> MethodAssertion | None:
    """Read explicit roles without classifying prose or inferring missing endpoints."""
    if value is None:
        return None
    if (not isinstance(value, dict)
            or set(value) != {"kind", "from_claim_id", "to_claim_id"}
            or value["kind"] not in ("operation", "condition", "precedes")):
        raise AnalysisError("Method assertion requires an explicit kind and endpoints.")
    start, end = value["from_claim_id"], value["to_claim_id"]
    if value["kind"] == "precedes":
        if (not isinstance(start, str) or not start.strip() or not isinstance(end, str)
                or not end.strip() or start == end):
            raise AnalysisError("Method relation requires distinct explicit operation IDs.")
    elif start is not None or end is not None:
        raise AnalysisError("Only a method relation may declare operation endpoints.")
    return MethodAssertion(value["kind"], start, end)


@dataclass(frozen=True)
class MethodLink:
    """An explicit proposed dependency; list adjacency never creates a link."""

    from_claim_id: str
    to_claim_id: str
    supporting_claim_ids: list[str]
    review: MethodReview | None = None
    relation_claim_id: str | None = None


@dataclass(frozen=True)
class MethodRoleValue:
    """Name a material or constraint, supported by facts rather than pretending to be one."""

    name: str
    supporting_claim_ids: list[str]


@dataclass(frozen=True)
class MethodOperation:
    """One source-backed operation and its task-local inputs, outputs and conditions."""

    scope: str
    operation_claim_id: str
    inputs: list[MethodRoleValue]
    outputs: list[MethodRoleValue]
    conditions: list[MethodRoleValue]
    review: MethodReview | None = None


@dataclass(frozen=True)
class MethodFlow:
    """Roles and connections refer only to the paper's original claim identities."""

    input_claim_ids: list[str] = field(default_factory=list)
    step_claim_ids: list[str] = field(default_factory=list)
    output_claim_ids: list[str] = field(default_factory=list)
    links: list[MethodLink] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    review: MethodReview | None = None
    operations: list[MethodOperation] | None = None

    @property
    def has_role_review(self) -> bool:
        """Distinguish prior decisions from an index still awaiting its first review."""
        return (
            self.review is not None
            if self.operations is None
            else any(op.review is not None for op in self.operations)
        )


def method_flow_payload(flow: MethodFlow) -> dict:
    """Expose proposals without presenting internal review state as model-authored facts."""
    payload = {
        "links": [
            {
                "from_claim_id": link.from_claim_id,
                "to_claim_id": link.to_claim_id,
                **({"relation_claim_id": link.relation_claim_id} if link.relation_claim_id
                   else {"supporting_claim_ids": link.supporting_claim_ids}),
            }
            for link in flow.links
        ],
        "gaps": flow.gaps,
    }
    if flow.operations is not None:
        return {
            **payload,
            "operations": [
                {key: value for key, value in dataclass_to_dict(op).items() if key != "review"}
                for op in flow.operations
            ],
        }
    return {
        **payload,
        "input_claim_ids": flow.input_claim_ids,
        "step_claim_ids": flow.step_claim_ids,
        "output_claim_ids": flow.output_claim_ids,
    }


def method_claim_ids(flow: MethodFlow) -> list[str]:
    """Return explicit node and relationship support once, never infer new assertions."""
    if flow.operations is not None:
        return list(
            dict.fromkeys(
                [
                    *(identity for op in flow.operations for identity in _operation_claim_ids(op)),
                    *(identity for link in flow.links for identity in link.supporting_claim_ids),
                ]
            )
        )
    return list(
        dict.fromkeys(
            [
                *flow.input_claim_ids,
                *flow.step_claim_ids,
                *flow.output_claim_ids,
                *(identity for link in flow.links for identity in link.supporting_claim_ids),
            ]
        )
    )


def _operation_claim_ids(operation: MethodOperation) -> list[str]:
    return list(
        dict.fromkeys(
            [
                operation.operation_claim_id,
                *(
                    identity
                    for value in [*operation.inputs, *operation.outputs, *operation.conditions]
                    for identity in value.supporting_claim_ids
                ),
            ]
        )
    )


def method_narrative_scope(flow: MethodFlow) -> dict:
    """Describe an index's scope without certifying unextracted steps or immediate edges."""
    return {
        "coverage": "indexed_facts_only",
        "order": "explicit_links_only",
        "operation_support": {
            op.operation_claim_id: _operation_claim_ids(op) for op in flow.operations or []
        },
    }


def parse_method_flow(value: object, *, claim_ids: set[str]) -> MethodFlow:
    """Keep old readings empty; reject malformed or invented references in new indexes."""
    if value is None:
        return MethodFlow()
    legacy = {"input_claim_ids", "step_claim_ids", "output_claim_ids", "links", "gaps"}
    current = {"operations", "links", "gaps"}
    if not isinstance(value, dict) or set(value) not in (legacy, current):
        raise AnalysisError("Method flow requires explicit roles, links and gaps.")

    def references(raw: object) -> list[str]:
        if (
            not isinstance(raw, list)
            or any(not isinstance(x, str) or x not in claim_ids for x in raw)
            or len(set(raw)) != len(raw)
        ):
            raise AnalysisError("Method flow contains invalid, duplicate or unknown claim IDs.")
        return raw

    roles = {}
    operations = None
    if set(value) == current:
        if not isinstance(value["operations"], list):
            raise AnalysisError("Method operations must be an array.")
        operations, seen_operations = [], set()
        keys = {"scope", "operation_claim_id", "inputs", "outputs", "conditions"}

        def role_values(raw: object) -> list[MethodRoleValue]:
            if not isinstance(raw, list):
                raise AnalysisError("Method materials and conditions must be named arrays.")
            values, names = [], set()
            for item in raw:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"name", "supporting_claim_ids"}
                    or not isinstance(item["name"], str)
                    or not item["name"].strip()
                    or item["name"] in names
                ):
                    raise AnalysisError(
                        "Method role values require unique names and explicit support."
                    )
                support = references(item["supporting_claim_ids"])
                if not support:
                    raise AnalysisError(
                        "Named method materials and conditions require factual support."
                    )
                values.append(MethodRoleValue(item["name"], support))
                names.add(item["name"])
            return values

        for row in value["operations"]:
            if (
                not isinstance(row, dict)
                or set(row) != keys
                or not isinstance(row["scope"], str)
                or not row["scope"].strip()
                or not isinstance(row["operation_claim_id"], str)
                or row["operation_claim_id"] not in claim_ids
                or row["operation_claim_id"] in seen_operations
            ):
                raise AnalysisError(
                    "Method operations require unique factual IDs and explicit scope."
                )
            refs = {key: role_values(row[key]) for key in ("inputs", "outputs", "conditions")}
            operations.append(MethodOperation(row["scope"], row["operation_claim_id"], **refs))
            seen_operations.add(row["operation_claim_id"])
        nodes = {op.operation_claim_id for op in operations}
    else:
        roles = {
            key: references(value[key])
            for key in ("input_claim_ids", "step_claim_ids", "output_claim_ids")
        }
        nodes = {identity for ids in roles.values() for identity in ids}
    gaps = value["gaps"]
    if not isinstance(gaps, list) or any(not isinstance(x, str) or not x.strip() for x in gaps):
        raise AnalysisError("Method flow gaps must be explicit nonempty strings.")
    if not isinstance(value["links"], list):
        raise AnalysisError("Method flow links must be a list.")
    links, seen = [], set()
    for link in value["links"]:
        if (
            not isinstance(link, dict)
            or set(link) not in (
                {"from_claim_id", "to_claim_id", "supporting_claim_ids"},
                {"from_claim_id", "to_claim_id", "relation_claim_id"})
            or not isinstance(link["from_claim_id"], str)
            or not isinstance(link["to_claim_id"], str)
            or link["from_claim_id"] not in nodes
            or link["to_claim_id"] not in nodes
        ):
            raise AnalysisError("Method flow link endpoints must reference declared nodes.")
        pair = link["from_claim_id"], link["to_claim_id"]
        if pair[0] == pair[1]:
            raise AnalysisError("Method dependencies must connect distinct operations.")
        relation = link.get("relation_claim_id")
        if "relation_claim_id" in link and (not isinstance(relation, str) or not relation):
            raise AnalysisError("Method relation requires an explicit factual identity.")
        support = references([relation] if relation else link["supporting_claim_ids"])
        if pair in seen or not support:
            raise AnalysisError("Method flow links require unique endpoints and explicit support.")
        seen.add(pair)
        links.append(MethodLink(*pair, support, relation_claim_id=relation))
    return MethodFlow(**roles, links=links, gaps=gaps, operations=operations)


def validate_method_assertions(
    flow: MethodFlow, assertions: dict[str, MethodAssertion | None], *, require_typed: bool = False,
) -> None:
    """A typed edge must reference its own fact, with the same declared endpoints."""
    if (not require_typed and not any(assertions.values())
            and not any(link.relation_claim_id for link in flow.links)):
        return  # Historical untyped records remain readable, not newly approved.
    for op in flow.operations or []:
        role = assertions.get(op.operation_claim_id)
        if role is None or role.kind != "operation":
            raise AnalysisError(
                "Method operation must reference an operation assertion, not a condition.")
    for identity, role in assertions.items():
        if role is not None and role.kind == "precedes":
            for endpoint in (role.from_claim_id, role.to_claim_id):
                node = assertions.get(endpoint)
                if node is None or node.kind != "operation":
                    raise AnalysisError(
                        f"Method relation {identity} references a non-operation fact.")
    for link in flow.links:
        role = assertions.get(link.relation_claim_id)
        if (role is None or role.kind != "precedes"
                or (role.from_claim_id, role.to_claim_id)
                != (link.from_claim_id, link.to_claim_id)):
            raise AnalysisError("Method relation endpoints do not match its factual assertion.")


def _binding(
    flow: MethodFlow,
    claims: list[Claim],
    source_url: str,
    link: MethodLink | None = None,
    operation: MethodOperation | None = None,
) -> str:
    wanted = (
        set(method_claim_ids(flow))
        if link is None
        else {link.from_claim_id, link.to_claim_id, *link.supporting_claim_ids}
    )
    if operation is not None:
        wanted = set(_operation_claim_ids(operation))
    supporting = []
    for identity in sorted(wanted):
        matches = [
            c
            for c in claims
            if c.metadata.get("paper_reading", {}).get("claim_id") == identity
            and {a.source_url for a in c.evidence} == {source_url}
        ]
        if len(matches) != 1 or not matches[0].is_publishable():
            return ""
        supporting.append(dataclass_to_dict(matches[0]))
    payload = {
        "source_url": source_url,
        "flow": method_flow_payload(flow),
        "link": [link.from_claim_id, link.to_claim_id, link.supporting_claim_ids]
        if link is not None
        else None,
        "operation_claim_id": operation.operation_claim_id if operation is not None else None,
        "claims": supporting,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _decision_index(
    payload: object,
    key: str,
    source_url: str,
    identity_fields: tuple[str, ...],
    expected: set[tuple[str, ...]],
) -> dict[tuple[str, ...], list[dict]]:
    """Match exact structured targets; ambiguous/unknown records never grant approval."""
    rows = payload.get(key, []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return {}
    indexed: dict[tuple[str, ...], list[dict]] = {}
    keys = {"source_url", "status", "reason", *identity_fields}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source_url"), str):
            return {}
        if row["source_url"] != source_url:
            continue
        if set(row) != keys or any(not isinstance(row[field], str) for field in identity_fields):
            return {}
        identity = tuple(row[field] for field in identity_fields)
        if identity not in expected:
            return {}
        indexed.setdefault(identity, []).append(row)
    return indexed


def _review(candidates: list[dict], binding: str, missing: str) -> MethodReview:
    decision = candidates[0] if len(candidates) == 1 else {}
    status, reason = decision.get("status"), decision.get("reason")
    valid = (
        status in ("supported", "unsupported", "needs_review")
        and isinstance(reason, str)
        and bool(reason.strip())
    )
    return MethodReview(
        status if valid and binding else "needs_review",
        reason if valid else missing,
        binding if valid else "",
    )


def apply_method_decisions(
    flow: MethodFlow,
    claims: list[Claim],
    payload: object,
    *,
    source_url: str,
) -> MethodFlow:
    """Review roles and link meaning, without changing individual fact approvals."""
    if not method_claim_ids(flow):
        return flow
    decisions = _decision_index(
        payload,
        "method_link_decisions",
        source_url,
        ("from_claim_id", "to_claim_id"),
        {(link.from_claim_id, link.to_claim_id) for link in flow.links},
    )
    links = []
    for link in flow.links:
        links.append(
            replace(
                link,
                review=_review(
                    decisions.get((link.from_claim_id, link.to_claim_id), []),
                    _binding(flow, claims, source_url, link),
                    "Missing or ambiguous method connection decision.",
                ),
            )
        )
    if flow.operations is not None:
        roles = _decision_index(
            payload,
            "method_operation_decisions",
            source_url,
            ("operation_claim_id",),
            {(op.operation_claim_id,) for op in flow.operations},
        )
        return replace(
            flow,
            links=links,
            review=None,
            operations=[
                replace(
                    op,
                    review=_review(
                        roles.get((op.operation_claim_id,), []),
                        _binding(flow, claims, source_url, operation=op),
                        "Missing or ambiguous method operation decision.",
                    ),
                )
                for op in flow.operations
            ],
        )
    roles = _decision_index(payload, "method_flow_decisions", source_url, (), {()})
    return replace(
        flow,
        links=links,
        review=_review(
            roles.get((), []),
            _binding(flow, claims, source_url),
            "Missing or ambiguous method role decision.",
        ),
    )


def reviewed_method_flow(flow: MethodFlow, claims: list[Claim], *, source_url: str) -> dict:
    """Require all supplied facts to be approved before authorizing a method narrative."""
    if any(link.from_claim_id == link.to_claim_id for link in flow.links):
        raise AnalysisError("Method dependencies must connect distinct operations.")
    ids = method_claim_ids(flow)
    for identity in ids:
        matches = [
            c
            for c in claims
            if c.metadata.get("paper_reading", {}).get("claim_id") == identity
            and {a.source_url for a in c.evidence} == {source_url}
        ]
        if len(matches) != 1 or not matches[0].is_publishable():
            raise AnalysisError("Method flow has an unavailable factual step or condition.")
    if flow.operations is not None:
        for op in flow.operations:
            if (
                op.review is None
                or op.review.status != "supported"
                or not op.review.binding_sha256
                or op.review.binding_sha256 != _binding(flow, claims, source_url, operation=op)
            ):
                raise AnalysisError("Method flow has unreviewed or changed operation roles.")
    elif ids and (
        flow.review is None
        or flow.review.status != "supported"
        or not flow.review.binding_sha256
        or flow.review.binding_sha256 != _binding(flow, claims, source_url)
    ):
        raise AnalysisError("Method flow has unreviewed or changed input/operation/output roles.")
    for link in flow.links:
        if (
            link.review is None
            or link.review.status != "supported"
            or not link.review.binding_sha256
            or link.review.binding_sha256 != _binding(flow, claims, source_url, link)
        ):
            raise AnalysisError("Method flow has an unreviewed or changed connection.")
    return method_flow_payload(flow)
