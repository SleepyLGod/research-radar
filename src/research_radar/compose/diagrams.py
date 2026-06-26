"""Platform-neutral diagram helpers for verified research drafts."""

from __future__ import annotations

from research_radar.models import Claim

CLAIM_DIAGRAM_LABELS = {
    "Problem": {"en": "Problem", "zh": "问题"},
    "Solution": {"en": "Method", "zh": "方法"},
    "Experiment": {"en": "Evaluation", "zh": "实验"},
    "Limitations": {"en": "Caveat", "zh": "局限"},
    "Essence": {"en": "Takeaway", "zh": "要点"},
}

CLAIM_DIAGRAM_ORDER = ["Problem", "Solution", "Experiment", "Limitations", "Essence"]


def build_mechanism_diagram(
    claims: list[Claim],
    *,
    language: str = "en",
) -> dict[str, object] | None:
    """Build a small mechanism diagram from already publishable claims."""

    nodes_by_prefix: dict[str, dict[str, str]] = {}
    for claim in claims:
        if not claim.is_publishable():
            continue
        prefix, body = _claim_prefix_body(claim.text)
        if prefix not in CLAIM_DIAGRAM_LABELS or prefix in nodes_by_prefix:
            continue
        text = _localized_claim_text(prefix, body, language=language)
        if not text:
            continue
        nodes_by_prefix[prefix] = {
            "label": CLAIM_DIAGRAM_LABELS[prefix].get(
                language,
                CLAIM_DIAGRAM_LABELS[prefix]["en"],
            ),
            "text": text,
        }

    nodes = [
        nodes_by_prefix[prefix]
        for prefix in CLAIM_DIAGRAM_ORDER
        if prefix in nodes_by_prefix
    ]
    if len(nodes) < 2:
        return None
    title = "机制速览" if language == "zh" else "Mechanism at a Glance"
    return {"kind": "mechanism_flow", "title": title, "nodes": nodes[:5]}


def _claim_prefix_body(text: str) -> tuple[str, str]:
    if ":" not in text:
        return "", text.strip()
    prefix, body = text.split(":", 1)
    return prefix.strip(), body.strip()


def _localized_claim_text(prefix: str, body: str, *, language: str) -> str:
    if not body:
        return ""
    if language == "zh":
        return body
    return f"{prefix}: {body}"
