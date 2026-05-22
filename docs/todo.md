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
- DeepSeek v4 Pro as the default reader route.
- Codex or command-backed providers as verifier routes.
- Failed-run diagnostics for provider and transport failures.
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

## Prioritized TODO

1. Add a strong web search provider.
   - Use web search to improve discovery recall.
   - Do not let web snippets become publishable claims.
   - Keep web connector failures as warnings when paper discovery still succeeds.

2. Add multi-topic recall and precision evaluation.
   - Evaluate `agent-memory`, `llm-reasoning-eval`, `rag-systems`, and user-provided topics.
   - Track source counts, primary-paper counts, selected deep sources, publishable claims, filtered
     noise, and reviewer downgrades.
   - Use the results to tune topic profiles before adding more publishing features.

3. Evaluate DeepSeek topic bootstrap quality.
   - Generate editable topic YAML drafts.
   - Check whether queries, concept groups, negative phrases, and priority sources are too broad or
     too narrow.
   - Keep manual review for new topic onboarding until quality is proven.

4. Stabilize Codex reader for weekly deep dives.
   - Keep DeepSeek v4 Pro as the default daily reader until Codex reader schema stability improves.
   - Use Codex reader for high-value weekly runs only after timeout and schema-retry behavior is
     reliable.

5. Polish article rendering and diagrams.
   - Improve article structure, titles, introductions, and transitions using only verified claims.
   - Prefer self-drawn explanatory diagrams.
   - Reuse original paper figures only with license and attribution audit.

6. Validate WeChat draft end to end.
   - Create draft-only output after manual review.
   - Do not auto-publish or mass-send.
   - Write publish failure artifacts instead of swallowing errors.

7. Add scheduler and cloud automation.
   - Start with local scheduled runs for confirmed topic configs.
   - Add cloud or Codex automation only after daily research output is stable.
   - Keep secrets out of prompts, logs, generated reports, and committed files.

## Near-Term Execution Order

1. Implement strong web search provider and fake tests.
2. Run multi-topic recall and precision evaluation under `/private/tmp`.
3. Tune topic profiles only where the evaluation exposes concrete misses.
4. Re-run real smoke before touching WeChat, scheduler, or cloud automation.
