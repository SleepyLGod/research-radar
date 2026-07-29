# ResearchRadar Usage Guide

This guide keeps the longer operational notes out of the README. It covers local setup, model
routes, daily runs, WeChat drafts, scheduler installation, and privacy checks. For custom model
vendors and local servers, see [Provider Configuration](providers.md).

## Setup

Install dependencies and create local config:

```bash
uv sync --extra dev
uv run research-radar init
```

`config.example.yaml` is a small public template. Put reviewed topics and daily preferences in
local `config.yaml`. `config.yaml`, `.env`, `runs/`, `data/`, `cache/`, and scheduler outputs are
local-only runtime state. Do not commit them.

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

For custom provider instances, store an arbitrary named secret:

```bash
uv run research-radar secrets set-named kimi.api_key
uv run research-radar secrets status --name kimi.api_key
```

## Model Routes

The default quality path is:

- Deep reading: `deepseek/deepseek-v4-pro`
- Source gist and report localization: lightweight DeepSeek routes
- Verification: `codex/gpt-5.6-terra` with `high` reasoning effort
- Web search: Tavily when the web-search secret is present

Daily users usually do not need route flags. Use the defaults first, then inspect or override
providers only when you are testing another model:

```bash
uv run research-radar provider list --config config.yaml
uv run research-radar provider routes --config config.yaml --mode daily
```

Xiaomi is configured as an optional DeepSeek-equivalent OpenAI-compatible provider. It does not
change defaults. To let Xiaomi handle routes that are normally DeepSeek-backed, pass:

```bash
--deepseek-provider xiaomi
```

Kimi, Qwen, Minimax, OpenAI-compatible local servers, Anthropic API, Codex CLI, and Claude Code
CLI use the same provider-instance pattern documented in [Provider Configuration](providers.md).

Task-specific overrides still win. For example, Xiaomi reader only:

```bash
uv run research-radar run paper \
  --topic <topic-id> \
  --url https://arxiv.org/pdf/2604.01707v1 \
  --config config.yaml \
  --root /private/tmp/research-radar-xiaomi-paper \
  --reader-provider xiaomi \
  --secret-source keychain \
  --model-cache
```

## Daily Research Run

Run a daily topic report:

```bash
uv run research-radar run daily \
  --topic <topic-id> \
  --config config.yaml \
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
- `review_findings.jsonl`: structured verifier, evidence, and public writing style findings
- `runtime_summary.json`: stage timing and cache summary

`public_writing_style` findings are non-blocking warnings. They flag template-like public prose or
machine metadata that should not appear in reader-facing text. They do not change claims, evidence
anchors, source links, or publication status.

For repeat smoke runs, `--model-cache` keeps expensive reader/verifier/localization calls local to
the run root.

## Single-Paper Run

Use this when you want to inspect one paper without running discovery:

```bash
uv run research-radar run paper \
  --topic <topic-id> \
  --url https://arxiv.org/pdf/2604.01707v1 \
  --config config.yaml \
  --root /private/tmp/research-radar-paper-smoke \
  --reader-provider deepseek \
  --verifier-provider codex \
  --secret-source keychain \
  --language zh \
  --model-cache
```

The paper run writes `paper.md`, `deep_reading.md`, `claims.jsonl`, `review_report.md`, and
evidence artifacts. Public content still comes only from supported claims with complete anchors.
Public writing style warnings may appear in `review_report.md` or `review_findings.jsonl`; they are
audit notes, not an automatic rewrite pass.

## Public Archive and RSS

Export any completed run from its platform-neutral `article_draft.json`:

```bash
uv run research-radar archive export \
  --run runs/<date-topic> \
  --output public-archive \
  --base-url https://research.example.com \
  --site-language zh
```

The export writes:

```text
public-archive/
├── archive.json
├── index.html
├── feed.xml
├── reports/<run-id>/index.html
├── reports/<run-id>/metadata.json
└── assets/<run-id>/...
```

One output directory is bound to the first valid `--base-url` used with it. Later exports must use
the same URL so report canonical links and RSS entries cannot drift across domains. It is also
bound to one site navigation language, selected with `--site-language zh|en`. A report is one daily
research edition and may contain several deep-read papers; `/papers/` is reserved for a future
single-paper knowledge base. The command only builds static files; deployment is intentionally
separate.

Archive and WeChat are sibling outputs from `ArticleDraft`. Archive export does not rewrite
`wechat.html`, upload WeChat media, create a draft, or change scheduler behavior.

### Publish the Archive through Git

After the dedicated Pages checkout has been created once, keep its non-secret settings in the
gitignored local `config.yaml`:

```yaml
archive:
  checkout: /path/to/research-radar-pages
  output_subdir: archive
  base_url: https://example.github.io/research-radar/archive
  site_language: zh
  remote: origin
  branch: gh-pages
```

Run a side-effect-free preflight first. It copies the existing Archive into a temporary directory,
exports the new report there, and validates RSS, canonical links, images, and public-content
boundaries. It does not change the Pages checkout, commit, or push:

```bash
uv run research-radar archive publish-git \
  --run <RUN_DIR> \
  --config config.yaml \
  --dry-run
```

The dry run requires the checkout to match its remote. If it is behind, update it with a normal
fast-forward first; the dry run will not change the checkout on your behalf.

Publish after the preflight succeeds:

```bash
uv run research-radar archive publish-git \
  --run <RUN_DIR> \
  --config config.yaml
```

The publisher requires a clean checkout on the configured branch. It fetches and safely
fast-forwards a checkout that is only behind its remote, stages only `output_subdir`, creates a
signed-off commit, and pushes it. It refuses dirty, diverged, or locally-ahead checkouts instead of
guessing. A successful run writes `archive_publish_result.json`; a failed publish writes
`archive_publish_error.json`. If the export produces no changes, it does not create an empty commit.

## Zhihu Manual Export

Export one completed daily run as a title-free Zhihu article body and a safe local image bundle:

```bash
uv run research-radar compose zhihu --run runs/<date-topic>
```

The command writes `zhihu.md`, `zhihu_export.json`, and `zhihu-assets/` inside the run directory.
Uploading `zhihu.md` alone does not upload the adjacent image directory. In local image mode, use the
asset list in `zhihu_export.json` to upload the images manually.

To give Zhihu public image URLs it can fetch during Markdown import, first publish the images to an
HTTP(S) location, then pass that run-specific image root:

```bash
uv run research-radar compose zhihu \
  --run runs/<date-topic> \
  --asset-base-url https://example.com/archive/assets/<run-id>/
```

The URL is an explicit hosting interface; it is not tied to GitHub Pages. The exporter records
`image_mode` and each resolved public image URL in `zhihu_export.json`. Use the metadata title in
Zhihu's title field and import the generated body once. ResearchRadar does not log in to Zhihu,
store browser cookies, or publish automatically. WeChat and Archive remain independent outputs from
the same `ArticleDraft`.

The Zhihu renderer intentionally uses only two heading levels, flat source lists, ordinary HTTP(S)
links, and compact figure notes. A final real-editor preview is still required because Zhihu may
normalize imported Markdown and fetch remote images asynchronously.

### Manual GitHub Pages deployment

The project archive is currently published at
<https://sleepylgod.github.io/research-radar/archive/>. GitHub Pages is only the hosting layer; the
archive remains a host-neutral static directory.

Use a dedicated checkout of the `gh-pages` branch. Keep it separate from the main development
checkout, add a `.nojekyll` file, ignore `/.archive-retired-assets/`, and keep a small root
`index.html` that links to `./archive/`:

```bash
PAGES_CHECKOUT="/path/to/research-radar-pages"
RUN_DIR="runs/<date-topic>"

git clone --branch gh-pages --single-branch \
  https://github.com/<owner>/<repository>.git "$PAGES_CHECKOUT"

: > "$PAGES_CHECKOUT/.nojekyll"
printf '/.archive-retired-assets/\n' > "$PAGES_CHECKOUT/.gitignore"
cat > "$PAGES_CHECKOUT/index.html" <<'HTML'
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url=./archive/">
  <title>ResearchRadar 研究归档</title>
</head>
<body>
  <p><a href="./archive/">打开 ResearchRadar 研究归档</a></p>
</body>
</html>
HTML

uv run research-radar archive export \
  --run "$RUN_DIR" \
  --output "$PAGES_CHECKOUT/archive" \
  --base-url https://sleepylgod.github.io/research-radar/archive \
  --site-language zh

git -C "$PAGES_CHECKOUT" add .nojekyll .gitignore index.html archive
git -C "$PAGES_CHECKOUT" commit -s -m "[publish] Update ResearchRadar archive"
git -C "$PAGES_CHECKOUT" push origin gh-pages
```

Configure GitHub Pages to publish `gh-pages` from `/(root)`. To use another repository, point
`--output` at that repository's local checkout and use its public base URL instead. No GitHub API
or hosting-provider code is required.

The manual commands above remain useful for initial Pages setup and recovery. Routine updates can
use `archive publish-git` once the local `archive` config has been reviewed.

## Private Email

Private email v1 sends one completed `ArticleDraft` to one personal inbox. It does not manage
subscribers, tracking, unsubscribe links, or campaigns. Add SMTP settings to the gitignored local
`config.yaml`:

```yaml
email:
  smtp_host: smtp.example.com
  smtp_port: 465
  security: tls
  username: you@example.com
  password_secret: email.smtp_password
  from_address: you@example.com
  to_address: you@example.com
  timeout_seconds: 30
```

For a personal Gmail self-send, use `smtp.gmail.com`, port `465`, and `security: tls`. Set
`username`, `from_address`, and `to_address` to the Gmail address you control. Gmail requires
two-step verification and a 16-character App Password for SMTP. Enter the generated App Password
without display spaces; do not use the normal Google account password.

Use `security: tls` for implicit TLS, commonly on port 465, or `security: starttls`, commonly on
port 587. Plaintext SMTP is rejected. Store the provider's SMTP application password in Keychain:

```bash
uv run research-radar secrets set-named email.smtp_password
```

Confirm only that the secret is present; this command never prints its value:

```bash
uv run research-radar secrets status \
  --name email.smtp_password \
  --secret-source keychain
```

Prepare `email.html`, `email.txt`, and safe preview images without connecting to SMTP:

```bash
uv run research-radar publish email \
  --run <RUN_DIR> \
  --config config.yaml \
  --dry-run
```

Send after reviewing the preview:

```bash
uv run research-radar publish email \
  --run <RUN_DIR> \
  --config config.yaml
```

The sent MIME message embeds safe PNG/JPEG paper figures using CID attachments, so it does not
depend on the public Archive and does not expose local file paths. A successful send writes
`email_send_result.json`; failures write a redacted `email_send_error.json`. The same run is not
sent twice unless `--allow-resend` is provided explicitly. Email is not part of the daily scheduler
in v1.

If the SMTP connection drops after delivery starts, ResearchRadar records `delivery_unknown` and
refuses an automatic retry. Check the inbox first; use `--allow-resend` only when a second copy is
acceptable. A dry run writes `email_preview_result.json` and never overwrites the durable send
record.

## WeChat Drafts

Upload a cover image once and store the returned media id somewhere local:

```bash
uv run research-radar publish wechat-upload-thumb \
  --image docs/assets/research-radar-plus.png \
  --output /private/tmp/research-radar-thumb.json
```

Load the stored id for later draft commands:

```bash
THUMB_MEDIA_ID="$(python3 -c 'import json; print(json.load(open("/private/tmp/research-radar-thumb.json"))["thumb_media_id"])')"
```

Create a draft from a completed run:

```bash
uv run research-radar publish wechat-draft \
  --run runs/<date-topic> \
  --title "ResearchRadar 日报：<topic>" \
  --digest "今日精选 <topic> 相关论文精读。" \
  --thumb-media-id "$THUMB_MEDIA_ID"
```

For local validation without calling WeChat:

```bash
uv run research-radar publish wechat-draft \
  --run runs/<date-topic> \
  --title "ResearchRadar 日报：<topic>" \
  --digest "今日精选 <topic> 相关论文精读。" \
  --thumb-media-id "$THUMB_MEDIA_ID" \
  --dry-run
```

Draft creation is draft-only. ResearchRadar does not auto-publish or mass-send.

## Local Daily Draft Scheduler

Generate a macOS launchd job for a reviewed topic:

```bash
uv run research-radar schedule daily-draft \
  --topic <topic-id> \
  --time 09:00 \
  --config config.yaml \
  --root research-radar-data \
  --thumb-media-id "<wechat-thumb-media-id>" \
  --language zh \
  --model-cache
```

The scheduler writes a runner script and plist under:

```text
<root>/schedules/daily-draft-<topic>/
```

The generated runner is a configuration snapshot. An installed launchd job does not automatically
pick up later changes to provider routes, model names, or Codex `reasoning_effort`. After changing
those settings, run `schedule daily-draft` again with the same stable root, then unload the installed
plist before copying and loading the regenerated one.

Install manually:

```bash
cp <root>/schedules/daily-draft-<topic-id>/ai.research-radar.daily-draft.<topic-id>.plist \
  ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/ai.research-radar.daily-draft.<topic-id>.plist
```

Check or test the job:

```bash
LABEL="ai.research-radar.daily-draft.<topic-id>"
launchctl print "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
tail -F <root>/schedules/daily-draft-<topic-id>/logs/stdout.log \
        <root>/schedules/daily-draft-<topic-id>/logs/stderr.log
```

Uninstall a temporary job:

```bash
launchctl unload ~/Library/LaunchAgents/ai.research-radar.daily-draft.<topic-id>.plist
rm ~/Library/LaunchAgents/ai.research-radar.daily-draft.<topic-id>.plist
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
