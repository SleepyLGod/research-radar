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
- Verified mechanism diagrams and improved figure selection for daily public articles.
- Local Public Archive/RSS export from `ArticleDraft`, including static daily report pages, a
  research-journal index, public metadata, and a feed. A Chinese GitHub Pages deployment is live;
  automatic archive publishing is not yet configured. `/papers/` remains a future single-paper
  knowledge base.
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

1. Add a Zhihu renderer/export MVP.
   - Build new channel renderers from the verified `ArticleDraft`; do not reuse WeChat HTML as the
     source of truth.
   - Keep channel-specific formatting downstream of verified claims, localized readings, source
     metadata, and figure metadata.
   - Do not let Zhihu or any future platform change the core research and evidence model.

2. Revisit Archive publishing automation after repeated manual use.
   - Keep the static output directory as the hosting-neutral interface.
   - Add a small Git publisher only if repeated manual pushes prove it is useful.
   - Keep Archive failures independent from WeChat draft creation.

3. Continue figure and diagram quality from real failures.
   - Improve TeX-source extraction and difficult PDF crops only when real papers expose gaps.
   - Keep figure explanations bound to same-paper verified content.

4. Tune topics from real daily runs.
   - Do not overfit topic profiles before real usage shows a pattern.
   - Use multi-topic eval and daily draft outcomes to identify recall failures, off-center source
     selection, shallow readings, low publishable claim counts, or missing figures.
   - Adjust queries, paper queries, concept groups, centrality signals, and negative phrases only
     when repeated runs show the same issue.

5. Continue cost and first-run runtime optimization.
   - Treat first-run latency as a background-job cost issue, not a reason to weaken evidence gates.
   - Consider reader/verifier budget strategies only when real scheduler runs show the cost is
     painful.
   - Preserve `--model-cache` for repeat smoke and debugging runs.

6. Keep weekly deep dive and Codex reader as future work.
   - Weekly remains a later product mode; daily research plus WeChat draft is the current main path.
   - Codex reader uses the same deep-reading prompt, schema, and evidence gate as DeepSeek reader.
   - Future work is about Codex reader reliability: schema stability, timeout behavior, and long-paper
     output quality.

## Near-Term Execution Order

1. Add a Zhihu renderer/export MVP from `ArticleDraft`.
2. Repeat the manual Archive update flow before deciding whether to automate Git publishing.
3. Improve figures and tune topic profiles when repeated real-run failures appear.
4. Revisit weekly deep dive and Codex reader only when daily usage shows the need.
