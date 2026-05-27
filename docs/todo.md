# ResearchRadar TODO Roadmap

ResearchRadar is a research-quality daily brief system. Its core job is to search broadly, select
precisely, read papers deeply, verify claims conservatively, and produce publishable research
briefs. WeChat, Zhihu, and other channels are downstream renderers and publishers; they should not
drive the research model.

## Current State

- Paper-first source selection for research briefs.
- Topic concept gates for precision-sensitive discovery.
- Source history so daily reports focus on new papers and new versions.
- Full-paper reading packets from PDF extraction.
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
- WeChat draft-only artifacts for manual review; no auto-publish or mass-send.
- Long-form daily article rendering with a top contents list, deep-read paper sections, other-source
  links, seen-before fallback, and concise evidence notes.
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
- `deep_reading.md` can remain a researcher audit note; `paper.md` should be suitable for careful
  human reading.
- WeChat HTML should read like a long article rather than a raw audit page:
  - Include a top contents list instead of relying on unsupported fixed sidebar behavior.
  - Put selected papers in a dedicated deep-read section.
  - Keep non-deep-read papers, repos, and web context as links plus conservative gists.
  - Prefer self-drawn explanatory diagrams; original paper figures require license and attribution
    audit before reuse.

## Prioritized TODO

1. Validate long-form WeChat daily article output with real draft-only smoke.
   - Run daily research, generate an evidence-gated long-form `ArticleDraft`, render WeChat HTML,
     and create a manual-review draft.
   - Do not auto-publish or mass-send.
   - Inspect readability, contents links, deep-read sections, other-source links, and evidence notes.

2. Add scheduler and local automation for confirmed topics.
   - Start with local scheduled runs for reviewed topic configs.
   - Keep source history append-only so daily reports focus on new papers and new versions.
   - Keep secrets out of prompts, logs, generated reports, and committed files.

3. Add multi-topic recall and precision evaluation as a recurring quality gate.
   - Evaluate `agent-memory`, `llm-reasoning-eval`, `rag-systems`, and user-provided topics.
   - Track source counts, primary-paper counts, selected deep sources, publishable claims, filtered
     noise, and reviewer downgrades.
   - Use the results to tune topic profiles before adding more publishing features.

4. Evaluate DeepSeek topic bootstrap quality.
   - Generate editable topic YAML drafts.
   - Check whether queries, concept groups, negative phrases, and priority sources are too broad or
     too narrow.
   - Keep manual review for new topic onboarding until quality is proven.

5. Stabilize Codex reader for weekly deep dives.
   - Keep DeepSeek v4 Pro as the default daily reader until Codex reader schema stability improves.
   - Use Codex reader for high-value weekly runs only after timeout and schema-retry behavior is
     reliable.

6. Expand diagrams and figure handling.
   - Improve self-drawn explanatory diagrams using only verified structured readings.
   - Reuse original paper figures only with license and attribution audit.

7. Continue cost and first-run runtime optimization.
   - Treat first-run latency as a background-job cost issue, not a reason to weaken evidence gates.
   - Consider reader/verifier budget strategies only after the daily E2E path is stable.
   - Preserve `--model-cache` for repeat smoke and debugging runs.

## Near-Term Execution Order

1. Run one real `agent-memory` daily under `/private/tmp` and inspect the long-form WeChat draft.
2. Validate WeChat draft-only creation from that run.
3. Add local scheduler only after long-form draft-only publishing is readable and auditable.
4. Re-run multi-topic evaluation before expanding providers beyond the current Tavily-based recall.
