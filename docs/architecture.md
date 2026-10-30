# ResearchRadar Architecture

ResearchRadar is a local-first research and publishing system. Its main boundary is simple:
models may discover, read, and explain sources, but reader-facing facts must pass the evidence
policy before any channel can render them.

## Subsystems

- `scheduler`: macOS launchd job generation, lifecycle commands, run locking, and non-secret state.
- `discovery`: source connectors for papers, repositories, RSS/blogs, and web search adapters.
- `ingestion`: source-aware PDF, HTML, and repository extraction with provenance and full-paper
  completeness checks.
- `analysis`: model routes, paper-reading schemas, localization, and the public explanation policy.
- `evidence`: claim ledger and unsupported-claim policy.
- `compose`: platform-neutral `ArticleDraft` construction plus Markdown, WeChat, Archive, Zhihu,
  and email renderers.
- `publishers.wechat`: WeChat Official Account draft API client.
- `publishers.email`: private SMTP delivery for one configured recipient.
- `storage`: owner-only run directories, manifests, source history, and limited encrypted state.
- `security`: secret backends, redaction, and privacy scanning.

WeChat, Archive/RSS, Zhihu, and email are sibling outputs. They consume the same filtered
`ArticleDraft`; no renderer gets to create new research claims.

## CLI And macOS App

The CLI and native menu-bar App are two entry points to the same Python application services,
research pipeline, evidence policy, and renderers. The App does not parse CLI output or read the
CLI's YAML configuration. Its typed JSON configuration is converted into the shared `AppConfig`.
The CLI's configuration and the App's workspace remain separate. Only source-history import is
offered, on explicit request; it does not import the CLI configuration, secrets, or reports.

Swift owns the interface, durable serialized job queue, report index, and one-shot schedule timer.
Versioned JSON requests, events, and terminal artifacts connect it to a bundled Python engine.
Only one engine job runs at a time. The engine and PDF helper start on demand; cancellation and
parent-process loss stop the process group. No Python engine or fixed polling loop remains idle.
The restricted report WebView is created only for reading and released when the panel is hidden.

The unreleased paper-ledger source slice adds an on-demand `read_paper_ledger` command. Shared
Python owns paper identity, versions and report occurrences; Swift owns topic-scoped filtering,
selection and navigation back to the original report or public reading/evidence. Saved public
reports are authoritative. The in-memory ledger is rebuildable, contains no copied prose, and
does not read credentials or infer paper relationships. No database or idle index scanner is added.

The App uses a PDFKit helper for PDF geometry/rendering; the CLI retains its Poppler fallback.
Both use the shared figure eligibility policy. An optional figure failure omits the image rather
than discarding an otherwise usable report.

App schedules require the App to remain running; the CLI launchd scheduler is a separate option.
Legacy scheduler conflicts must be resolved before enabling an overlapping App schedule.
Research and delivery are independent jobs: after an eligible report is saved, explicitly enabled
channels may enqueue delivery automatically. An uncertain delivery is never automatically resent.

## Canonical E2E Flow

1. Topic setup defines a topic id, queries, paper queries, and concept signals.
2. Planner expands the topic into neutral scope, research questions, source priorities, and risks.
3. Discovery produces normalized `SourceCandidate` records from papers, repositories, RSS/blogs,
   and later open web sources.
4. Wide scan clusters and ranks candidates, then selects sources for deep reading.
5. Ingestion stores PDFs, HTML pages, and repository metadata as artifacts with provenance; research
   briefs reject abstract-only HTML as successful deep reads.
6. Deep research reading produces atomic claim units with stable claim IDs and explanatory
   paragraphs that name the claims supporting them.
7. Evidence ledger and review assign claim status from exact source anchors; unsupported or
   incomplete claims remain internal.
8. Localization may translate paragraph text but must preserve supporting claim IDs exactly.
9. The public explanation policy keeps a paragraph only when all of its supporting claims from the
   same paper are publishable. Rejected or unbound prose is replaced, when possible, by verified
   atomic claim text.
10. Synthesis outline / prewriting preserves the full reportable source basis for internal use.
11. `ArticleDraft` assembles the filtered public content once.
12. Rendering transforms that draft into Markdown, WeChat HTML, Archive/RSS, Zhihu Markdown, or
   email without changing the evidence decision.
13. Delivery is user-configured: CLI publishing is explicit; the App can queue enabled channels
   after an eligible report. WeChat creates a draft, Archive updates a reviewed Git checkout,
   and private email sends to the configured recipient. No WeChat public publishing or mass-send
   is performed. Archive publishing remains a CLI feature.
14. Audit artifacts preserve manifests, sources, readings, claims, evidence, output, and review
   reports in a unique owner-only run directory. Source history suppresses a paper only after a
   successful daily outcome, not merely because discovery saw it.

## Run And Schedule Identity

Every run has a unique attempt ID and a separate report date. Re-running the same topic on the same
day therefore creates a new directory instead of overwriting an earlier attempt. Source history is
append-only JSONL and records successful report and publishing outcomes by paper family.

`schedule daily-draft` writes a reviewed command snapshot. `schedule install`, `status`, `run-now`,
and `uninstall` manage that snapshot through launchd. The runner uses a lock to prevent overlapping
attempts and writes a redacted `schedule_state.json`; it does not contain provider or publishing
secrets.

## Storage Boundary

Normal run artifacts are local plaintext files, not encrypted document storage. New run and source
history directories use owner-only permissions. Credentials use configured secret references,
including macOS Keychain and generic environment-backed names; SMTP passwords use the same secret
boundary. Envelope encryption is reserved for limited sensitive state such as token caches. Users
who need encryption at rest should use FileVault and keep the configured root private.

## Extension Points

Add a new source by implementing `DiscoveryConnector`.
Add a new model by implementing `LLMProvider`.
Add a new publisher by implementing a package under `publishers`.

## Research Skill

The project skill at `docs/skills/research-radar/SKILL.md` defines the required research behavior
contract: planner, wide scan, deep reading, prewriting, and publishing discipline. It should be
used before changing analysis prompts or adding new research workflows.

## Figure Policy

Public article figures should default to self-drawn explanatory diagrams derived from verified
claims. Original paper figures may be used only when license/source metadata supports reuse or a
human reviewer explicitly approves it for the target channel. Every reused figure must keep
attribution to the paper, authors when available, source URL or arXiv id, and known license.

arXiv source files can include TeX/LaTeX and figures, and arXiv OAI metadata can expose license
information. This does not mean every arXiv figure is automatically safe for public reuse: the
default arXiv license gives arXiv distribution rights, while third-party reuse depends on the
paper's selected license and attribution requirements.

For PDF-only papers, figure extraction is conservative. ResearchRadar may crop a figure region only
when it can bind a caption to the same paper and compute a credible crop; it must not publish a full
PDF page as if it were a figure. If a safe crop is unavailable, the public draft simply omits the
figure section and keeps diagnostics in audit artifacts.

The PDF fallback keeps Poppler bounding boxes in PDF points and converts them to render pixels only
at the `pdftoppm` boundary. Caption matching stays within one visual line and column. Crops that
contain article paragraphs, another figure/table caption, implausible geometry, or visible edge
clipping fail closed and are not exposed to any public renderer.
