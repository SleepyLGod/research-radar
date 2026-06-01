# ResearchRadar Usage Guide

This guide keeps the longer operational notes out of the README. It covers local setup, model
routes, daily runs, WeChat drafts, scheduler installation, and privacy checks.

## Setup

Install dependencies and create local config:

```bash
uv sync --extra dev
uv run research-radar init
```

`config.yaml`, `.env`, `runs/`, `data/`, `cache/`, and scheduler outputs are local-only runtime
state. Do not commit them.

Check the repository privacy boundary before committing:

```bash
uv run research-radar privacy scan
```

## Secrets

ResearchRadar can read secrets from macOS Keychain or from an explicit local environment file. The
recommended daily path is Keychain:

```bash
uv run research-radar secrets set deepseek
uv run research-radar secrets set xiaomi
uv run research-radar secrets set web-search
uv run research-radar secrets set github
uv run research-radar secrets set wechat
uv run research-radar secrets status
```

`secrets status` prints only `present` or `missing`; it never prints secret values.

For temporary local experiments, commands also support:

```bash
--secret-source env --env-file .env
```

## Model Routes

The default quality path is:

- Deep reading: `deepseek/deepseek-v4-pro`
- Source gist and report localization: lightweight DeepSeek routes
- Verification: `codex/gpt-5.5`
- Web search: Tavily when the web-search secret is present

Xiaomi is configured as an optional DeepSeek-equivalent OpenAI-compatible provider. It does not
change defaults. To let Xiaomi handle routes that are normally DeepSeek-backed, pass:

```bash
--deepseek-provider xiaomi
```

Task-specific overrides still win. For example, Xiaomi reader only:

```bash
uv run research-radar run paper \
  --topic agent-memory \
  --url https://arxiv.org/pdf/2604.01707v1 \
  --config config.example.yaml \
  --root /private/tmp/research-radar-xiaomi-paper \
  --reader-provider xiaomi \
  --secret-source keychain \
  --model-cache
```

## Daily Research Run

Run a daily topic report:

```bash
uv run research-radar run daily \
  --topic agent-memory \
  --config config.example.yaml \
  --root research-radar-data \
  --limit 5 \
  --deep-limit 1 \
  --language zh \
  --model-cache
```

Useful outputs under the run directory:

- `daily.md`: public Markdown report
- `wechat.html`: local preview with local figures
- `wechat_publish.html`: publish-safe WeChat body
- `article_draft.json`: platform-neutral draft source
- `source_selection.json`: selected and skipped source audit
- `review_report.md`: verifier and evidence-gate audit
- `runtime_summary.json`: stage timing and cache summary

For repeat smoke runs, `--model-cache` keeps expensive reader/verifier/localization calls local to
the run root.

## Single-Paper Run

Use this when you want to inspect one paper without running discovery:

```bash
uv run research-radar run paper \
  --topic agent-memory \
  --url https://arxiv.org/pdf/2604.01707v1 \
  --config config.example.yaml \
  --root /private/tmp/research-radar-paper-smoke \
  --reader-provider deepseek \
  --verifier-provider codex \
  --secret-source keychain \
  --language zh \
  --model-cache
```

The paper run writes `paper.md`, `deep_reading.md`, `claims.jsonl`, `review_report.md`, and
evidence artifacts. Public content still comes only from supported claims with complete anchors.

## WeChat Drafts

Upload a cover image once and store the returned media id somewhere local:

```bash
uv run research-radar publish wechat-upload-thumb \
  --image /path/to/cover.png \
  --output /private/tmp/research-radar-thumb.json
```

Create a draft from a completed run:

```bash
uv run research-radar publish wechat-draft \
  --run runs/<date-topic> \
  --title "ResearchRadar 日报：<topic>" \
  --digest "今日精选 <topic> 相关论文精读。" \
  --thumb-media-id "<wechat-thumb-media-id>"
```

For local validation without calling WeChat:

```bash
uv run research-radar publish wechat-draft \
  --run runs/<date-topic> \
  --title "ResearchRadar 日报：<topic>" \
  --digest "今日精选 <topic> 相关论文精读。" \
  --thumb-media-id "<wechat-thumb-media-id>" \
  --dry-run
```

Draft creation is draft-only. ResearchRadar does not auto-publish or mass-send.

## Local Daily Draft Scheduler

Generate a macOS launchd job for a reviewed topic:

```bash
uv run research-radar schedule daily-draft \
  --topic agent-memory \
  --time 09:00 \
  --config config.example.yaml \
  --root research-radar-data \
  --thumb-media-id "<wechat-thumb-media-id>" \
  --language zh \
  --model-cache
```

The scheduler writes a runner script and plist under:

```text
<root>/schedules/daily-draft-<topic>/
```

Install manually:

```bash
cp <root>/schedules/daily-draft-agent-memory/ai.research-radar.daily-draft.agent-memory.plist \
  ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/ai.research-radar.daily-draft.agent-memory.plist
```

Check or test the job:

```bash
LABEL="ai.research-radar.daily-draft.agent-memory"
launchctl print "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
tail -F <root>/schedules/daily-draft-agent-memory/logs/stdout.log \
        <root>/schedules/daily-draft-agent-memory/logs/stderr.log
```

Uninstall a temporary job:

```bash
launchctl unload ~/Library/LaunchAgents/ai.research-radar.daily-draft.agent-memory.plist
rm ~/Library/LaunchAgents/ai.research-radar.daily-draft.agent-memory.plist
```

Use a stable root such as `research-radar-data` for long-running schedules. Avoid using
`/private/tmp` for permanent jobs.

## Evidence Boundary

ResearchRadar separates internal audit material from reader-facing content:

- `sources.jsonl` keeps full discovery records.
- `claims.jsonl` keeps claim status and evidence anchors.
- `review_report.md` keeps verifier findings and follow-up actions.
- Public reports render only supported, complete-anchor claims and localized reading text.

Web snippets help discovery and ranking. They do not become publishable research claims by
themselves.

## Validation Commands

For doc-only changes:

```bash
git diff --check
uv run research-radar privacy scan
```

For code changes:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check src tests
uv run research-radar privacy scan
git diff --check
```
