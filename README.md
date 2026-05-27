# ResearchRadar

ResearchRadar is a privacy-first research intelligence system that monitors papers, blogs,
open-source projects, and web sources, then turns verified analysis into platform-ready
research briefs.

The current repo is the v0.0.0 foundation: a local-first system for security, typed data,
research workflow, verified pipeline smoke runs, and draft-only publishing boundaries.
It is not yet the full v1 product. API keys, WeChat credentials, raw run data, and user
preferences stay out of git and are stored through a secret backend.

## Current v0.0.0 Foundation

- Provides daily monitoring and weekly deep-dive CLI scaffolds for dry-run validation.
- Keeps durable run directories with source manifests, evidence ledgers, drafts, and review reports.
- Uses typed interfaces for discovery, ingestion, LLM analysis, evidence verification, neutral
  article drafts, renderers, and publishers.
- Renders daily WeChat HTML as a long-form article with a contents list, deep-read paper sections,
  other-source links, seen-before fallback, and concise evidence notes.
- Includes a dedicated researcher-grade paper reading skill under `docs/skills/research-radar/`.
- Stores secrets through macOS Keychain via `keyring`.
- Encrypts sensitive runtime state with envelope encryption and AES-GCM.
- Provides a privacy scanner for committed files.
- Supports fake clients in tests so the system can be verified without real API keys.

## Target E2E Flow

1. Topic setup: define topic id, queries, priority sources, and cadence.
2. Planner: expand the topic into neutral scope, research questions, source priorities, and risks.
3. Discovery: search papers, repositories, RSS/blogs, and later open web sources.
4. Wide scan: cluster and rank candidates, then select sources for deep reading.
5. Ingestion: fetch and extract PDFs, HTML pages, and repository metadata with provenance.
6. Deep research reading: apply the ResearchRadar skill to problem, solution, related work,
   limitations, critique, examples, and essence.
7. Evidence ledger: convert claims into source-anchored records and reject unsupported claims.
8. Review: run rule-based and model-backed checks for hallucination, overclaiming, weak evidence,
   and unsupported critique.
9. Synthesis outline / prewriting: ask perspective-guided questions and outline before drafting.
10. ArticleDraft: assemble verified claims into a platform-neutral draft.
11. Rendering: render the same draft to Markdown, WeChat HTML, and future channel formats.
12. Manual publishing: create a WeChat draft only after review; no auto-publish.
13. Audit artifacts: keep manifests, sources, artifacts, claims, evidence, drafts, rendered output,
   and review reports under `runs/`.

## Quick Start

```bash
uv sync --extra dev
uv run research-radar init
uv run research-radar privacy scan
uv run pytest
```

Set local secrets when you are ready to call real providers:

```bash
uv run research-radar secrets set deepseek
uv run research-radar secrets set openai
uv run research-radar secrets set anthropic
uv run research-radar secrets set wechat
```

Generate a dry-run daily report:

```bash
uv run research-radar run daily --topic agent-memory
```

Run the same daily pipeline with a compatibility provider from an explicit local `.env` file:

```bash
uv run research-radar run daily --topic agent-memory --provider deepseek --secret-source env --env-file .env --deep-limit 1
```

Task-specific routes can override that compatibility default. Deep reading uses
`deepseek-v4-pro` by default when the DeepSeek reader route is selected; source gists still
use the lighter DeepSeek route. This example uses DeepSeek for reading and Codex CLI for
verification:

```bash
uv run research-radar run daily --topic agent-memory --reader-provider deepseek --verifier-provider codex --secret-source env --env-file .env --deep-limit 1
```

Deep-reading output is converted into evidence-bound claims; publishable article claims still come
from the evidence policy.
Use `--limit 3` for narrow real smoke runs while the discovery and relevance gates are evolving.
Deep-reading output is written to `readings.jsonl` and `deep_reading.md`.

Run the repeatable three-topic smoke harness under `/private/tmp`:

```bash
uv run research-radar eval topics --provider deepseek --secret-source env --env-file .env
```

The harness checks source selection, publishable claim count, warning-only connector failures, and
whether downgraded claims leaked into rendered briefs.
For `research_brief` topics, paper connectors use deterministic paper-focused query variants and
the smoke summary reports paper candidate diagnostics.

Enable strong web search by configuring the Tavily adapter and setting `WEB_SEARCH_API_KEY` through
Keychain or an explicit local `.env` file:

```yaml
discovery:
  web_search:
    provider: tavily
    header_secret_name: web_search.api_key
    max_results: 5
    search_depth: basic
```

Web search expands discovery recall only. Web snippets are not promoted into publishable research
claims.

Run a single-paper golden smoke without discovery:

```bash
uv run research-radar run paper --topic agent-memory --url https://arxiv.org/pdf/2604.01707v1 --provider deepseek --secret-source env --env-file .env
```

Single-paper output is written to `paper.md`, `deep_reading.md`, `claims.jsonl`, and
`review_report.md`.

Generate WeChat-compatible HTML from a run:

```bash
uv run research-radar compose wechat --run runs/<date-topic>
```

Daily WeChat HTML is a reader-facing long article, not the internal audit report: selected papers
are expanded into deep-read sections, non-selected sources stay as links plus conservative gists,
and evidence notes only include verified source anchors. Original paper figures are not reused
automatically; use self-drawn explanatory diagrams unless figure license and attribution have been
checked.

Create a WeChat draft after manual review:

```bash
uv run research-radar publish wechat-draft \
  --run runs/<date-topic> \
  --title "ResearchRadar: <topic>" \
  --digest "One-sentence reviewed digest" \
  --thumb-media-id "<wechat-thumb-media-id>"
```

For local E2E validation without calling the WeChat API, add `--dry-run`. The publisher renders
content from `article_draft.json`, writes `wechat.html` and publish audit artifacts, and creates a
draft only. It does not auto-publish or mass-send.

## Research Reading Standard

ResearchRadar is designed to read papers as a researcher, not as a generic summarizer. The
workflow requires planning, wide scanning, deep reading, outline-first synthesis, area context,
problem/solution analysis, related-work comparison, limitations, neutral critique, and evidence
anchors for factual or critical claims.

Graphify-style corpus graphs may be used for clustering and cross-document links, but graph output
is not treated as proof. Publishable claims must be grounded in source evidence.

## Repository Boundaries

Committed:

- Source code
- Tests
- Docs
- `config.example.yaml`
- `.env.example`

Local-only:

- `config.yaml`
- `.env`
- `runs/`
- `data/`
- API keys
- WeChat access tokens
- User preference data

Run `research-radar privacy scan` before committing.

## License

MIT
