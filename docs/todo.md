# ResearchRadar TODO Roadmap

ResearchRadar is a research-quality daily brief system. Its core job is to search broadly, select
precisely, read papers deeply, verify claims conservatively, and produce publishable research
briefs. WeChat, Zhihu, and other channels are downstream renderers and publishers; they should not
drive the research model.

## Current State

- Paper-first source selection for research briefs.
- Topic concept gates for precision-sensitive discovery.
- Outcome-based source history so daily reports suppress a paper only after a successful report
  outcome. A failed reader, verifier, or artifact write can be retried as new; version updates and
  paper-family aliases remain visible.
- Source-history outcome memory so later runs can show when a source previously appeared in a
  daily report or WeChat draft. History write failures warn without invalidating an otherwise
  successful research run.
- Unique attempt IDs and owner-only run/history directories, so same-day reruns never overwrite
  one another and the report date remains a separate manifest field.
- Multi-topic eval gate v1 across `agent-memory`, `llm-reasoning-eval`, `rag-systems`, and
  `llm-inference`, validated with a real four-topic WeChat draft smoke.
- Topic bootstrap quality lint for editable YAML drafts, with topic-specific signals for inference
  serving, robot foundation models, and long-context evaluation.
- Source-aware paper acquisition for arXiv and OpenReview, including OpenReview PDF ingestion.
- Full-paper reading packets from extracted PDFs, with a completeness gate that rejects
  abstract-only HTML for research briefs.
- Atomic claim units, claim linting, anchor completeness checks, and quote-only anchor repair.
- Claim-bound public explanations: reader paragraphs carry supporting claim IDs, localization must
  preserve those IDs, and `ArticleDraft` keeps only paragraphs whose same-paper claims remain
  publishable. Unsafe prose falls back to verified atomic claim text.
- Table-aware evidence windows for experiment and result claims.
- Tavily web search adapter, web-result canonicalization, and web search diagnostics.
- Source centrality reranking and curated public daily source lists.
- DeepSeek v4 Flash with explicit thinking and `high` reasoning effort as the default reader route.
- Codex `gpt-5.6-terra` with `high` reasoning effort as the default verifier route; other
  command-backed providers remain optional.
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
- Paper figure support from arXiv source assets and conservative PDF-only figure crops. PDF point
  coordinates are converted once at render time, and crops containing text, another caption, or
  clipped edges fail closed; full-page PDF screenshots are not allowed as public figures.
- Verified mechanism diagrams and improved figure selection for daily public articles.
- Local Public Archive/RSS export from `ArticleDraft`, including static daily report pages, a
  research-journal index, public metadata, and a feed. A Chinese GitHub Pages deployment is live;
  the Git checkout publisher adds preflight, signed-off commit, and push automation without tying
  the exporter to GitHub. `/papers/` remains a future single-paper knowledge base.
- Private SMTP email v1 can render HTML/plain-text from `ArticleDraft`, embed safe PNG/JPEG figures
  with CID, and send one report to one personal inbox. Gmail TLS/App Password self-send has been
  validated end to end. It does not manage public subscribers.
- Local launchd scheduler generation and lifecycle commands for daily WeChat draft jobs, including
  install, status, run-now, uninstall, overlap protection, validated run handoff, process-group
  watchdogs, live bounded logs, and redacted last-run state.
- Zhihu-specific Markdown export v2 from `ArticleDraft`, including a title-free two-level document,
  flat source lists, safe local assets or public image URLs, and schema-v2 export metadata. The
  export has been validated in the real Zhihu editor; login and automatic publishing remain out of
  scope.
- Privacy scan, redaction, local secret handling, and no auto-publish boundary.

## Non-Negotiable Quality Rules

- `paper.md` and daily public reports may only use supported claims with complete evidence anchors.
- Reader explanations may appear publicly only when every supporting claim ID belongs to the same
  paper and remains publishable after verification. Localization cannot add or replace IDs.
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

1. Continue figure and diagram quality from real failures.
   - Improve TeX-source extraction and difficult PDF crops only when real papers expose gaps.
   - Keep figure explanations bound to same-paper verified content.

2. Tune topics from real daily runs.
   - Do not overfit topic profiles before real usage shows a pattern.
   - Use multi-topic eval and daily draft outcomes to identify recall failures, off-center source
     selection, shallow readings, low publishable claim counts, or missing figures.
   - Adjust queries, paper queries, concept groups, centrality signals, and negative phrases only
     when repeated runs show the same issue.

3. Decide whether Archive and private email belong in scheduled delivery.
   - Keep WeChat draft creation, Archive publishing, and email delivery as independent failure
     domains.
   - Automate another channel only after repeated manual use shows that it is useful.

4. Continue cost and first-run runtime optimization.
   - Treat first-run latency as a background-job cost issue, not a reason to weaken evidence gates.
   - Consider reader/verifier budget strategies only when real scheduler runs show the cost is
     painful.
   - Preserve `--model-cache` for repeat smoke and debugging runs.

5. Keep weekly deep dive and Codex reader as future work.
   - There is no current `run weekly` command. A future weekly mode must aggregate multiple daily
     runs rather than relabel one run as a weekly report.
   - Daily research plus WeChat draft is the current main path.
   - Codex reader uses the same deep-reading prompt, schema, and evidence gate as DeepSeek reader.
   - Future work is about Codex reader reliability: schema stability, timeout behavior, and long-paper
     output quality.

## Near-Term Execution Order

1. Use real daily runs across several topics and record repeated quality failures.
2. Improve figures and tune topic profiles only when those failures repeat.
3. Decide whether Archive or private email should join scheduled delivery.
4. Revisit weekly deep dive and Codex reader only when daily usage shows the need.
