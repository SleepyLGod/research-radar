# ResearchRadar TODO Roadmap

ResearchRadar is a research-quality daily brief system. Its core job is to search broadly, select
precisely, read papers deeply, verify claims conservatively, and produce publishable research
briefs. WeChat, Zhihu, and other channels are downstream renderers and publishers; they should not
drive the research model.

## Current State

- Paper-first source selection for research briefs.
- Topic concept gates for precision-sensitive discovery.
- Source history so daily reports focus on new papers and new versions.
- Source-history outcome memory so later runs can show when a source previously appeared in a
  daily report or WeChat draft.
- Multi-topic eval gate v1 across `agent-memory`, `llm-reasoning-eval`, `rag-systems`, and
  `llm-inference`, validated with a real four-topic WeChat draft smoke.
- Topic bootstrap quality lint for editable YAML drafts, with topic-specific signals for inference
  serving, robot foundation models, and long-context evaluation.
- Source-aware paper acquisition for arXiv and OpenReview, including OpenReview PDF ingestion.
- Full-paper reading packets from extracted PDFs, with a completeness gate that rejects
  abstract-only HTML for research briefs.
- Atomic claim units, claim linting, anchor completeness checks, and quote-only anchor repair.
- Table-aware evidence windows for experiment and result claims.
- Tavily web search adapter, web-result canonicalization, and web search diagnostics.
- Source centrality reranking and curated public daily source lists.
- DeepSeek v4 Pro as the default reader route.
- Codex or command-backed providers as verifier routes.
- Opt-in model call cache and runtime summaries for reader/verifier cost audit.
- Publishable-only verifier review and conservative anchor-repair skipping to reduce wasted first-run
  model work.
- Failed-run diagnostics for provider and transport failures.
- WeChat draft-only creation for manual review in the WeChat editor, validated with real drafts;
  no auto-publish or mass-send.
- Long-form daily article rendering with a top contents list, deep-read paper sections, other-source
  links, seen-before fallback, and concise evidence notes.
- Public writing style contract for reader explanations and localization, plus non-blocking style
  warnings for template-like public text.
- Paper figure support from arXiv source assets and conservative PDF-only figure crops; full-page
  PDF screenshots are not allowed as public figures.
- Local launchd scheduler generation and real-run validation for daily WeChat draft jobs.
- Privacy scan, redaction, local secret handling, and no auto-publish boundary.

## Non-Negotiable Quality Rules

- `paper.md` and daily public reports may only use supported claims with complete evidence anchors.
- `review_report.md` may contain weak evidence, warnings, rejected claims, and follow-up actions; it
  is an internal audit artifact, not the reader-facing report.
- Readability must never weaken evidence requirements.
- Renderer code must not invent research claims. It may reorganize verified claims, but it must not
  add new facts, interpretations, URLs, rankings, or critiques.
- Model-generated URLs are not publishable links. Public links must come from source candidates or
  verified source metadata.
- When evidence is partial, missing, or only semantically similar, the claim stays unpublished.

## Paper Report Requirements

- Users can choose `--language en` or `--language zh`.
- English mode writes the report body in English.
- Chinese mode writes the report body in Chinese, while evidence quotes remain in the original
  source language.
- Reports should be accurate first, then readable:
  - Lead each major section with one concise core judgment.
  - Explain problem, motivation, solution, experiments, related work, limitations, critique, and
    essence.
  - Use plain-language examples only after the technical claim is evidence-backed.
  - Separate author-reported claims from system-level conclusions.
  - Avoid vague abstract-style prose when concrete verified claims are available.
  - Chinese reports should be natural and concrete, without template summaries or promotional
    phrasing. English reports should avoid hype, generic conclusions, vague attribution, and
    promotional tone.
  - Readability edits must preserve numbers, formulas, technical terms, benchmark names, metrics,
    source URLs, and exact evidence quotes.
- `deep_reading.md` can remain a researcher audit note; `paper.md` should be suitable for careful
  human reading.
- WeChat HTML should read like a long article rather than a raw audit page:
  - Include a top contents list instead of relying on unsupported fixed sidebar behavior.
  - Put selected papers in a dedicated deep-read section.
  - Keep non-deep-read papers, repos, and web context as links plus conservative gists.
  - Prefer self-drawn explanatory diagrams when they are grounded in verified readings.
  - Original paper figures require same-paper attribution, license metadata when available, and a
    real source asset or conservative crop; full PDF pages must not be used as figures.

## Prioritized TODO

1. Stabilize Codex reader for weekly deep dives.
   - Keep DeepSeek v4 Pro as the default daily reader until Codex reader schema stability improves.
   - Use Codex reader for high-value weekly runs only after timeout and schema-retry behavior is
     reliable.

2. Expand diagrams and figure handling.
   - Improve self-drawn explanatory diagrams using only verified structured readings.
   - Improve TeX-source figure/caption extraction and license metadata coverage.
   - Improve PDF figure cropping for multi-column, caption-above, and unusual layouts.
   - Reuse original paper figures only with license and attribution audit.

3. Continue cost and first-run runtime optimization.
   - Treat first-run latency as a background-job cost issue, not a reason to weaken evidence gates.
   - Consider reader/verifier budget strategies only after the daily E2E path is stable.
   - Preserve `--model-cache` for repeat smoke and debugging runs.

4. Add future publishing channels such as Zhihu.
   - Keep channel renderers downstream of the verified `ArticleDraft`.
   - Do not let channel formatting requirements change the core research and evidence model.

## Near-Term Execution Order

1. Use the multi-topic eval gate to tune reviewed topic profiles from recall/precision failures.
2. Stabilize Codex reader for weekly deep-dive runs.
3. Expand diagram and figure handling after the evaluation loop is stable.
