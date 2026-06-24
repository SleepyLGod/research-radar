"""Create editable topic profile drafts from free-text research topics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from research_radar.analysis.providers import LLMProvider, Message
from research_radar.config import TopicConfig
from research_radar.exceptions import ResearchRadarError
from research_radar.storage.files import write_text

DRAFT_HEADER = "# Draft topic profile. Review before adding to config.yaml."

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "based",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "paper",
    "papers",
    "research",
    "the",
    "to",
    "using",
    "with",
}

DEFAULT_PRIORITY_SOURCES = [
    "arxiv.org",
    "semanticscholar.org",
    "openalex.org",
    "openreview.net",
    "github.com",
]

DEFAULT_NEGATIVE_PHRASES = [
    "course project",
    "job posting",
    "marketing page",
    "product announcement",
    "tutorial only",
]

GENERIC_ALIASES = {
    "ai",
    "benchmark",
    "benchmarks",
    "dataset",
    "datasets",
    "evaluation",
    "model",
    "models",
    "paper",
    "papers",
    "research",
    "system",
    "systems",
}


class _NoAliasDumper(yaml.SafeDumper):
    """YAML dumper that keeps editable drafts free of anchors."""

    def ignore_aliases(self, data: object) -> bool:
        """Disable YAML aliases for repeated values."""

        return True


def bootstrap_topic_draft(
    topic_text: str,
    *,
    language: str = "en",
    provider: LLMProvider | None = None,
    model: str | None = None,
) -> TopicConfig:
    """Build a reviewable topic configuration draft."""

    cleaned = _clean_topic_text(topic_text)
    if language not in {"en", "zh"}:
        raise ResearchRadarError("language must be en or zh.")
    if provider is None:
        return _heuristic_topic(cleaned, language=language)
    response = provider.complete(
        [
            Message(
                role="system",
                content=(
                    "You draft conservative ResearchRadar topic profiles. "
                    "Return strict JSON only. Do not include prose or markdown."
                ),
            ),
            Message(role="user", content=_bootstrap_prompt(cleaned, language)),
        ],
        model=model or "topic-bootstrap",
    )
    return _topic_from_model_payload(cleaned, language, response.content)


def default_topic_draft_path(root: Path, topic_id: str) -> Path:
    """Return the default editable draft path for a topic id."""

    return root / "topic_drafts" / f"{topic_id}.yaml"


def render_topic_draft_yaml(topic: TopicConfig) -> str:
    """Render a topic-list YAML snippet ready to paste under config topics."""

    payload = [
        {
            "id": topic.id,
            "source_intent": topic.source_intent,
            "report_language": topic.report_language,
            "queries": topic.queries,
            "paper_queries": topic.paper_queries,
            "web_queries": topic.web_queries,
            "negative_phrases": topic.negative_phrases,
            "concept_groups": topic.concept_groups,
            "priority_sources": topic.priority_sources,
        }
    ]
    body = yaml.dump(payload, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True)
    warning_lines = [f"# - {warning}" for warning in lint_topic_draft(topic)]
    warnings = "\n".join(["# Quality warnings:", *warning_lines, ""]) if warning_lines else ""
    return f"{DRAFT_HEADER}\n{warnings}{body}"


def lint_topic_draft(topic: TopicConfig) -> list[str]:
    """Return deterministic quality warnings for an editable topic draft."""

    warnings: list[str] = []
    if len(topic.queries) < 2:
        warnings.append("add at least two broad discovery queries")
    if len(topic.paper_queries) < 3:
        warnings.append("add at least three paper-focused queries")
    if len(topic.negative_phrases) < 3:
        warnings.append("add more negative phrases to reduce off-topic recall")
    for group in [
        "agent_context",
        "memory_mechanism",
        "evaluation_signal",
        "negative_compute_or_training",
    ]:
        aliases = topic.concept_groups.get(group, [])
        if not aliases:
            warnings.append(f"concept group `{group}` is empty")
        elif _aliases_are_too_generic(aliases):
            warnings.append(f"concept group `{group}` is too generic")
    return warnings


def write_topic_draft(
    root: Path,
    topic: TopicConfig,
    *,
    output: Path | None = None,
) -> Path:
    """Write a topic draft and return the absolute draft path."""

    path = output or default_topic_draft_path(root, topic.id)
    absolute_path = path.expanduser().resolve()
    write_text(absolute_path, render_topic_draft_yaml(topic))
    return absolute_path


def _heuristic_topic(topic_text: str, *, language: str) -> TopicConfig:
    terms = _meaningful_terms(topic_text)
    topic_id = _safe_topic_id(terms)
    base_phrase = " ".join(terms[:6])
    title_phrase = topic_text.casefold()
    concept_aliases = _concept_aliases(terms, title_phrase)
    topic_negative_phrases = _negative_phrases_for_terms(terms)
    return TopicConfig(
        id=topic_id,
        queries=_unique(
            [
                title_phrase,
                base_phrase,
                f"{base_phrase} systems",
                f"{base_phrase} evaluation",
            ]
        )[:4],
        paper_queries=_unique(
            [
                f"{base_phrase} paper",
                f"{base_phrase} benchmark",
                f"{base_phrase} evaluation",
                f"{base_phrase} survey",
                f"{base_phrase} arxiv",
            ]
        ),
        web_queries=_unique(
            [
                f"{base_phrase} official",
                f"{base_phrase} blog",
                f"{base_phrase} github",
            ]
        ),
        negative_phrases=topic_negative_phrases,
        concept_groups={
            "agent_context": concept_aliases["context"],
            "memory_mechanism": concept_aliases["mechanism"],
            "evaluation_signal": [
                f"{base_phrase} benchmark",
                f"{base_phrase} evaluation",
                "benchmark",
                "evaluation",
                "dataset",
            ],
            "negative_compute_or_training": topic_negative_phrases,
        },
        priority_sources=list(DEFAULT_PRIORITY_SOURCES),
        source_intent="research_brief",
        report_language=language,
    )


def _topic_from_model_payload(
    topic_text: str,
    language: str,
    raw_json: str,
) -> TopicConfig:
    payload = _load_json_object(raw_json)
    concept_groups = _string_list_mapping(payload.get("concept_groups"), "concept_groups")
    return TopicConfig(
        id=_safe_topic_id(_tokens(str(payload.get("id") or topic_text))),
        queries=_required_string_list(payload.get("queries"), "queries"),
        paper_queries=_required_string_list(payload.get("paper_queries"), "paper_queries"),
        web_queries=_optional_string_list(payload.get("web_queries"), "web_queries"),
        negative_phrases=_optional_string_list(
            payload.get("negative_phrases"),
            "negative_phrases",
        )
        or list(DEFAULT_NEGATIVE_PHRASES),
        concept_groups=concept_groups,
        priority_sources=_optional_string_list(
            payload.get("priority_sources"),
            "priority_sources",
        )
        or list(DEFAULT_PRIORITY_SOURCES),
        source_intent="research_brief",
        report_language=language,
    )


def _bootstrap_prompt(topic_text: str, language: str) -> str:
    return f"""
Draft a ResearchRadar topic profile for this research topic:
{topic_text}

Return JSON with exactly these keys:
- id: lowercase slug
- queries: 2-4 broad search queries
- paper_queries: 3-6 paper-focused queries
- web_queries: 1-3 web/blog/repository follow-up queries
- negative_phrases: 3-8 phrases that should be downgraded as noise
- concept_groups: object with non-empty arrays for agent_context,
  memory_mechanism, evaluation_signal, and negative_compute_or_training
- priority_sources: source domains

Rules:
- Keep source_intent implicit as research_brief.
- Use report language {language}.
- Prefer original papers, benchmarks, official repos, and official docs.
- Do not include secrets, user info, or URLs.
""".strip()


def _concept_aliases(terms: list[str], title_phrase: str) -> dict[str, list[str]]:
    base_phrase = " ".join(terms[:6])
    bigrams = [f"{left} {right}" for left, right in zip(terms, terms[1:], strict=False)]
    context = _unique([title_phrase, base_phrase, *bigrams[:3]])
    mechanism = _unique([*_known_mechanism_aliases(terms), *bigrams, base_phrase])
    return {
        "context": context[:5],
        "mechanism": mechanism[:6],
    }


def _known_mechanism_aliases(terms: list[str]) -> list[str]:
    term_set = set(terms)
    aliases: list[str] = []
    if {"world", "models"} <= term_set or {"world", "model"} <= term_set:
        aliases.append("world model")
    if "diffusion" in term_set:
        aliases.append("diffusion model")
    if "retrieval" in term_set and "generation" in term_set:
        aliases.append("retrieval augmented generation")
    if "embodied" in term_set and ("agents" in term_set or "agent" in term_set):
        aliases.append("embodied agent")
    if "memory" in term_set:
        aliases.extend(["memory retrieval", "long-term memory"])
    if "reasoning" in term_set:
        aliases.extend(["reasoning evaluation", "chain-of-thought"])
    if "inference" in term_set or "serving" in term_set:
        aliases.extend(
            [
                "llm serving",
                "inference engine",
                "kv cache",
                "prefill",
                "decode",
                "batching",
                "speculative decoding",
            ]
        )
    if "robot" in term_set or "robotics" in term_set:
        aliases.extend(
            [
                "robot foundation model",
                "embodied agent",
                "vision-language-action",
                "robot manipulation benchmark",
            ]
        )
    if "long" in term_set and "context" in term_set:
        aliases.extend(
            [
                "long-context evaluation",
                "context length",
                "needle-in-a-haystack",
                "long-context benchmark",
            ]
        )
    return aliases


def _negative_phrases_for_terms(terms: list[str]) -> list[str]:
    term_set = set(terms)
    phrases = list(DEFAULT_NEGATIVE_PHRASES)
    if "inference" in term_set or "serving" in term_set:
        phrases.extend(["fine-tuning only", "post-training", "rag system", "agent memory"])
    if "robot" in term_set or "robotics" in term_set:
        phrases.extend(["industrial product page", "robot kit tutorial", "automation vendor"])
    if "long" in term_set and "context" in term_set:
        phrases.extend(["prompt engineering only", "chatbot tutorial", "short-context benchmark"])
    return _unique(phrases)


def _aliases_are_too_generic(aliases: list[str]) -> bool:
    meaningful = [alias for alias in aliases if alias.casefold() not in GENERIC_ALIASES]
    return len(meaningful) == 0


def _load_json_object(raw_json: str) -> dict[str, Any]:
    text = raw_json.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResearchRadarError("Topic bootstrap provider did not return valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ResearchRadarError("Topic bootstrap provider JSON must be an object.")
    return payload


def _string_list_mapping(value: object, name: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ResearchRadarError(f"{name} must be an object.")
    result: dict[str, list[str]] = {}
    for group, aliases in value.items():
        if not isinstance(group, str) or not group.strip():
            raise ResearchRadarError(f"{name} keys must be non-empty strings.")
        result[group.strip()] = _required_string_list(aliases, f"{name}.{group}")
    for required_group in [
        "agent_context",
        "memory_mechanism",
        "evaluation_signal",
        "negative_compute_or_training",
    ]:
        if required_group not in result:
            raise ResearchRadarError(f"{name}.{required_group} is required.")
    return result


def _required_string_list(value: object, name: str) -> list[str]:
    result = _optional_string_list(value, name)
    if not result:
        raise ResearchRadarError(f"{name} must contain at least one string.")
    return result


def _optional_string_list(value: object, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ResearchRadarError(f"{name} must be a list.")
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value):
        raise ResearchRadarError(f"{name} must contain only non-empty strings.")
    return _unique(result)


def _clean_topic_text(topic_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", topic_text).strip()
    if not cleaned:
        raise ResearchRadarError("Topic text cannot be empty.")
    return cleaned


def _safe_topic_id(terms: list[str]) -> str:
    meaningful = [term for term in terms if term not in STOPWORDS]
    slug = "-".join(meaningful[:6]).strip("-")
    if not slug:
        raise ResearchRadarError("Topic text must contain at least one searchable term.")
    return slug


def _meaningful_terms(topic_text: str) -> list[str]:
    terms = [token for token in _tokens(topic_text) if token not in STOPWORDS]
    if not terms:
        raise ResearchRadarError("Topic text must contain at least one searchable term.")
    return terms


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
