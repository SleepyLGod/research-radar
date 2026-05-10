# ResearchRadar

ResearchRadar is a privacy-first research intelligence system that monitors papers, blogs,
open-source projects, and web sources, then turns verified analysis into platform-ready
research briefs.

The project is intentionally local-first for v1. API keys, WeChat credentials, raw run data,
and user preferences stay out of git and are stored through a secret backend.

## What v1 Does

- Runs daily monitoring and weekly deep-dive pipelines from a CLI.
- Keeps a durable run directory with source manifests, evidence ledgers, drafts, and review reports.
- Uses typed interfaces for discovery, ingestion, LLM analysis, evidence verification, neutral
  article drafts, renderers, and publishers.
- Includes a dedicated researcher-grade paper reading skill under `docs/skills/research-radar/`.
- Stores secrets through macOS Keychain via `keyring`.
- Encrypts sensitive runtime state with envelope encryption and AES-GCM.
- Provides a privacy scanner for committed files.
- Supports fake clients in tests so the system can be verified without real API keys.

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
uv run research-radar secrets set wechat
```

Generate a dry-run daily report:

```bash
uv run research-radar run daily --topic agent-memory
```

Generate WeChat-compatible HTML from a run:

```bash
uv run research-radar compose wechat --run runs/<date-topic>
```

Create a WeChat draft after manual review:

```bash
uv run research-radar publish wechat-draft --run runs/<date-topic>
```

The publisher creates a draft only. It does not auto-publish or mass-send.

## Research Reading Standard

ResearchRadar is designed to read papers as a researcher, not as a generic summarizer. The
paper-reading workflow requires area context, problem/solution analysis, related-work comparison,
limitations, neutral critique, and evidence anchors for factual or critical claims.

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
