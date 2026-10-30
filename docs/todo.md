# ResearchRadar TODO Roadmap

ResearchRadar is a research-quality daily brief system. Its core job is to search broadly, select
precisely, read papers deeply, verify claims conservatively, and produce publishable research
briefs. WeChat, Zhihu, and other channels are downstream renderers and publishers; they should not
drive the research model.

## Current State

- **Shared model-call audit (2026-10-30, unreleased):** offline review confirms streaming
  remains opt-in, omitted/false streaming settings share the same request and cache identity,
  and endpoint, output budget, thinking/effort and streaming changes separate cached answers.
  Legacy Codex cache behavior is unchanged. The intentional OpenAI-compatible endpoint-identity
  migration still causes old entries to miss; documentation now distinguishes that migration
  from the default-disabled streaming option.

  Three additional boundary cases were reproduced and fixed: malformed non-streaming UTF-8
  no longer becomes a successful answer with replacement characters; excessive JSON nesting
  becomes a standard provider failure rather than an uncaught recursion error; incomplete HTTP
  bodies no longer contribute text excerpts, even without a recognizable JSON envelope.
  Byte counts and coarse failure states remain available. Invalid encoding/JSON does not retry,
  cache or enter reader repair; transient disconnects retain the existing one-retry limit.
  A final diagnostic privacy regression also prevents endpoint URL usernames/passwords from
  appearing in the failure hostname, for both streaming and non-streaming requests.

  Closeout verified this source slice independently of the pending Reader, evidence, translation,
  composition and relevance work: 1,178 isolated Python tests passed, with two existing opt-in
  tests skipped. Separately, the combined working tree passed 1,336 full Python tests, also with
  two skips. The full runs blocked network and real Keychain access explicitly.
  An additional offline daily-path regression covers both streaming and non-streaming reader
  and verifier responses through the existing public draft. The pipeline diagnostic test now
  asserts that partial model text is absent; unrelated verifier-test changes are excluded.
  Ruff, privacy and diff checks passed. No real service, credential access or package update was
  used for closeout. This source work does not update installed Apps or prove live endpoint
  availability, factual correctness, revised-reader prompt quality or parity between models.

- **Single-paper evidence disclosure (2026-10-30, unreleased):** ordinary reading now
  starts with the bottom “Verified claims & evidence” section collapsed. A native disclosure
  keeps every saved claim, quote and source link available. Opening a different paper resets
  the section; explicit evidence navigation from the ledger, graph or chapter menu reveals
  it before using the existing layout-aware scroll path. No report, research, evidence gate,
  delivery rule or persistent setting changed.

  A separate candidate, using the existing local signing certificate and an isolated
  read-only workspace, opened both saved comparison reports. Actual native clicks verified
  collapse, expansion and re-collapse; Chinese and English screenshots retain the original
  report text. Automated native-layout tests cover both languages, and existing evidence
  navigation tests still pass. Chapter-menu keyboard input and VoiceOver remain manual
  acceptance items; incomplete automation of the menu is not a passed input test.
  Pre-commit review also identified a deferred evidence jump overriding a newer chapter
  selection. A failing offline navigation regression reproduced the stale target; the fix
  clears it before the new direct jump. Rapid chapter selection during image loading still
  needs manual input acceptance; the earlier candidate predates this additional fix.
  Verification at the offline acceptance checkpoint: 396 Swift tests passed. Privacy,
  bundle/signature and diff checks passed. Original
  reports, previous Apps and normal configuration remain unchanged. No model/search request,
  secret value access, upload or delivery was performed during acceptance. This change remains
  unreleased; publication does not complete the pending manual checks.

- **Topic knowledge source closeout (2026-10-29, unreleased):** explicit organization of saved
  public deep reads, native multi-label classification, typed semantic relations and exact cited
  claim navigation are implemented. Source-only ledger entries are not given invented features.
  Saved browsing is local; explicit organization uses the configured reader model and cost
  confirmation, without discovery, PDF rereading or delivery. Failed/cancelled organization retains
  committed knowledge. Two real organizations on the same paper pair give partial quality evidence,
  not an autonomous-knowledge accuracy guarantee. Automatic/incremental organization, user-edited
  facets, periodic consolidation and broader-topic quality remain unimplemented or unaccepted.
  The App currently submits all reports for the selected topic, without a date/report picker;
  serialized input above 512,000 characters is rejected before a model call, not truncated.
  Physical keyboard/focus, help dismissal, VoiceOver, multiple displays and larger-graph/resource
  acceptance remain open. Existing beta downloads are unchanged. The dated checkpoints below retain
  their original scope; an early "not implemented" or "no live calls" statement is historical, not
  the final cumulative status. [Current user guide](macos-app.md#unreleased-candidate-organize-saved-papers).

- **Codex default model update (2026-10-28, unreleased):** source App/CLI defaults and newly
  generated scheduler snapshots use `gpt-6-luna/xhigh`. Updated App startup migrates the former
  built-in Luna verifier model while preserving the selected effort, custom models and DeepSeek
  selection. The existing Terra/high migration still applies. Installed Apps, existing scheduler
  snapshots, reports, caches and past live acceptance records are unchanged. No live validation
  of the new model or package rebuild is included in this update.

- **Popover startup fix (2026-10-27, unreleased):** the earlier missing-window check
  had two separate causes. The old layer-zero observer cannot recognize the native layer-25
  popover. Independently, the production App requested its first presentation while AppKit's
  status-item window was still zero-height or offscreen; it did not reopen after positioning.
  The minimal App-only fix waits for that window's move/resize/screen notifications, then releases
  those observers when the anchor is ready or presentation is cancelled. There is no timer,
  polling, new engine behavior or change to report content. Regression tests cover zero-height
  and offscreen anchors plus close/toggle cancellation. Full offline Python and Swift regression
  passed: 329 Swift tests in 59 suites, with the same two optional frozen-engine tests skipped.
  A disposable native-only App using the production entry point, paused isolated fixture data
  and no engine/helper observed an on-screen popover before any status-button action; subsequent
  AX status-button actions could open it again. This is controlled automation, not physical input
  or sustained reading acceptance. It exited normally, with no jobs/descendants and unchanged
  isolated files and retained candidate. The retained candidate was not rebuilt, no installed App
  or DMG was replaced, and manual reading/VoiceOver/multi-display checks remain deferred.
  [Cause and verification bounds](superpowers/plans/2026-10-26-native-reading-polish.md#offline-popover-startup-diagnosis-2026-10-27).

  A subsequently authorized independent packaged candidate reused the existing local signing
  identity and unchanged frozen engine. Release-mode build, static bundle verification and
  deep/strict signature checks passed; its designated requirement matches the retained candidate.
  With fresh paused isolated fixture data, the real signed candidate automatically showed its
  layer-25 popover before input, completed two AX status-button hide/reopen cycles, and exited
  through its own native Quit menu. Owned-window capture confirmed the isolated home screen.
  No jobs or descendants remained, and all isolated data plus retained/normal App file hashes
  were unchanged. This is packaged startup acceptance, not physical reading, extended resource
  measurement or a Release/DMG update. The user subsequently authorized reviewed signed-off
  source closeout to the existing Draft PR; manual reading checks remain pending, and merge
  or Release updates are not authorized.

- **Native reading content/figure repair (2026-10-27, unreleased):** the App now retains the
  previously omitted public legacy details and figure explanations. Distinct original captions
  remain available without replacing their translations. The figure heading and chapter menu
  share the actually loaded thumbnails, so missing, unsafe or undecodable images cannot leave an
  empty chapter or floating notes. Loading remains limited to the visible paper; hide/switch and
  cancellation checks cover releasing images and ignoring cancelled stale work. Full Python and
  Swift regression passed (327 Swift tests in 59 suites; two existing optional frozen-engine
  tests skipped), along with Ruff, localization, privacy and diff checks. Physical reading-click
  confirmation remains deferred. Research, generated reports, channel renderers, true configuration
  and retained App/DMG packages are unchanged.
  [Scope and verification](superpowers/plans/2026-10-26-native-reading-polish.md#follow-up-public-content-and-available-figure-chapters-2026-10-27).

  A subsequent independent candidate build reused the existing local signing selection and frozen
  engine. Bundle/signature checks passed and retained App file trees stayed unchanged. Controlled
  native checks of the current production views covered Chinese/light and English/dark fixture
  reports: supplementary prose and valid figure explanations are visible; all-unavailable figures
  leave no body heading or chapter menu action. Fixture files stayed unchanged with zero secret
  value reads or new jobs. The candidate process separately started and quit with isolated paused
  configuration, an empty queue and no child processes. Its popover visibility was **not accepted**
  by the automated startup checks; actual status-item input remains pending. This is not complete
  packaged-reader acceptance, a new DMG or a published update.
  The authorized source closeout keeps the fixes/tests and acceptance documents in separate
  signed-off commits on the existing PR branch. Local App/DMG files, screenshots, fixture data and
  raw acceptance logs are excluded. The PR remains Draft; merge and release are not authorized.

- **Native reading closeout for Draft review (2026-10-26):** the accumulated overview, public
  paper browsing, evidence and pane/typography changes were independently reviewed as one set of
  34 files, with no verified production defect. The user explicitly deferred the remaining physical
  reading-click confirmation; it is not passed and is not a Ready/release gate claimed by this work.
  Chinese/light and English/dark new-topic sheets have bounded native open/cancel acceptance,
  with unchanged fixture topic/job counts and no credential-value reads. Source commits and a
  Draft PR are the authorized closeout; no beta package or release changes are included.
  [Acceptance scope and remaining checks](superpowers/plans/2026-10-26-native-reading-polish.md#authorized-closeout).

- **Native pane/typography follow-up (2026-10-26, unreleased):** grouped settings and diagnostics
  now fill the shared adaptive detail surface instead of adding an outer inset rectangle. Native
  grouping and navigation materials remain. Topic/report toolbar insets are aligned; paper reading
  uses system proportional 15-point body text, clearer section spacing and primary-color card
  questions, with no added font asset or dependency. The English HTML entry now says Full daily
  report. A bilingual hosted regression reproduced the 20-point form inset and passed after the fix;
  long native reading at narrow widths also passed. Full Python/Swift regression passed, with the
  existing opt-in frozen-engine checks still skipped, followed by nine focused UI tests after the
  last text-style adjustment. Bundle, signing and fresh read-only review passed. Isolated native
  captures cover English/dark and Chinese/light pages; scroll, return, Escape and compact/full
  restoration passed without new jobs or credential reads. Extended repeated-menu automation hit
  a tracking/focus limit and is not claimed complete. Reports and prior Apps remain unchanged;
  physical input, onboarding/sheets, VoiceOver and multiple displays remain separate manual checks.
  [Details and bounds](superpowers/plans/2026-10-26-native-reading-polish.md#follow-up-consistent-content-panes-and-reading-typography).

- **Native reading polish candidate (2026-10-26, unreleased):** fixed reading navigation now adds
  report-scoped paper switching and jumps to existing sections, including repeat selection of the
  same chapter. Evidence keeps verbatim quotes with leading alignment, distinct locations and
  tinted safe source links. Friendly topic headings are shared across home, history and report
  overview; original report titles remain available in report information and delivery confirmations.
  Preview cards prioritize existing research questions, then core ideas, then summaries; claim counts
  are secondary and explicitly not independent replication or quality rankings. Delivery is shown
  only in report overview, with report-level fold state retained while reading. Full Python regression,
  317 Swift tests in 57 suites, Ruff, privacy, bundle/signature and a fresh read-only review passed.
  Controlled native input verified repeated jumps, paper switching to the top, return, Escape/reopen,
  compact/full restoration, retained delivery folding, native picker arrow/Return selection and both
  channel confirmation cancellations. Fresh system-window captures cover cards, reading and evidence
  in both languages and appearances; full HTML opens and returns without a persistent delivery block.
  Original and isolated report artifacts are
  byte unchanged; no new jobs or credential-value reads occurred. Physical keyboard, VoiceOver,
  multi-display and external-click acceptance are not implied by these local-input checks.
  The separately signed candidate preserves both prior Apps and real configuration; no published
  package has been replaced. [Scope and verification](superpowers/plans/2026-10-26-native-reading-polish.md).

- **Native paper browsing candidate (2026-10-26, unreleased):** opening a report now starts with
  previews of its existing public deep reads, then a selectable native paper detail with sectioned
  explanations, claims and original evidence. Additional discovered sources are listed separately,
  not presented as verified papers. The dated report list and explicit full-HTML report remain.
  Previews and native detail do not preload WebKit. Safe local raster images are decoded on demand;
  legacy PDF page screenshots and unsafe/missing images remain excluded. Existing report files,
  research/evidence behavior, channel confirmations and published packages are unchanged.
  Python regression, Swift regression (313 tests in 55 suites), focused data/image checks, privacy,
  bundle/signature and read-only review passed. Isolated native input exercised both papers,
  scrolling, return, Escape/reopen and full HTML
  in both languages and appearances, with no new jobs or credential-value reads; all original/copied
  artifacts were byte unchanged. Physical status-item routing and figure-load hide/remount stress
  remain distinct from this bounded acceptance. Cross-day paper accumulation, relation graphs,
  incremental research judgments and per-paper live progress are still future work.
  [Scope, layers and acceptance](superpowers/plans/2026-10-26-native-paper-reading.md).

- **Home hierarchy candidate (2026-10-26, unreleased):** secondary report titles, a clearer native
  reading action and less completed-task repetition improve the full and compact homes without
  changing their dimensions. Active/failure/empty/configuration attention stays visible; channel
  attention remains with the report. Existing same-day read and confirmed regeneration behavior
  is preserved without showing a second equivalent Run Now entry. Full Swift regression passed
  (301 tests in 52 suites); fresh bilingual light/dark and edge-state native captures were checked.
  Both new reader actions opened the existing report and returned without new jobs or secret reads.
  This is presentation polish, not completed paper cards, short research briefs or evidence views.
  [Scope and acceptance](superpowers/plans/2026-10-25-native-visual-alignment.md#home-hierarchy-follow-up-2026-10-26).

- **Reader return/scroll follow-up (2026-10-26, unreleased):** reproduced the expanded Delivery
  disclosure inflating native split-view minimum height and pushing navigation outside the window.
  A presentation-only minimum content width fixes that measurement without changing window size,
  HTML, the research pipeline or sending policy. Regression now exercises actual direct/retained
  workspaces in both languages, smaller content bounds and bidirectional scrolling; full Swift
  regression passed with 299 tests in 52 suites. Isolated native clicks verified expand, return,
  reopen, both confirmation cancellations, Escape and compact/full restoration with no new jobs
  or credential-value reads. Four system-window captures cover bilingual light/dark readers.
  Controlled local outside-click routing passed; physical cross-application mouse/trackpad checks
  remain manual. Old App, real configuration and published beta are unchanged.
  [Cause, scope and evidence](superpowers/plans/2026-10-25-native-visual-alignment.md#reader-follow-up-2026-10-26).

- **Unreleased native visual-alignment candidate (2026-10-25):** home typography and adaptive
  reading backgrounds are implemented; the reader now groups existing WeChat/email controls in
  one Delivery disclosure with independent summary states and one-time attention expansion.
  Full Swift regression (297 tests), Python regression, Ruff, privacy, bundle/signature checks
  and a local read-only review passed. Original report artifacts and isolated copies are byte
  unchanged. Own-view snapshots cover bilingual light/dark layouts, not system glass rendering.
  System capture and popover focus initially blocked native click/cancel/Escape acceptance; the
  reader follow-up above records what subsequently passed without substituting state tests. Old App and published beta remain
  unchanged. [Scope and acceptance](superpowers/plans/2026-10-25-native-visual-alignment.md).

- **Unreleased native overview candidate (2026-10-25):** the first product-prototype slice adapts
  the homepage and four coarse phases to existing App state. It separates current attempts,
  retained effective reports and channel attention without changing the research pipeline or
  renderers. [Scope and layer boundaries](superpowers/plans/2026-10-25-native-research-overview.md).
  Offline Python and Swift regression, privacy, bundle and signing checks passed. Native fixture
  captures cover 32 bilingual light/dark home states and 24 outcome states. They verify layout,
  not live research. Automated button navigation stopped at an unrecognized expand control;
  fresh manual interaction and visual acceptance remain pending. This is not part of the
  published beta. Paper cards,
  per-paper progress, automatic question briefs and a persistent relationship graph remain future
  work, not hidden functionality behind the new layout.

- **v0.3.0b1 Pre-release published (2026-10-25):** source metadata is aligned at `0.3.0b1` for CLI and
  bundled engine, with App short version `0.3.0`, build `2`, and the same full beta identifier.
  PR #1 was merged using Rebase and merge; tag `v0.3.0b1` points to merged `main` commit `e1eca67`.
  The [Release](https://github.com/SleepyLGod/research-radar/releases/tag/v0.3.0b1) provides the final
  DMG and checksum; CLI installation uses the source tag, not a standalone executable or PyPI package.
  Earlier versions remain unchanged. [Release notes](releases/v0.3.0b1.md) describe the packages,
  completed checks, and known limits. Publication is not notarization or complete first-use acceptance.

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
- DeepSeek `deepseek-flash` with explicit thinking and `high` reasoning effort as the default reader route.
- Codex `gpt-6-luna` with `xhigh` reasoning effort as the default verifier route; other
  command-backed providers remain optional.
- Opt-in model call cache and runtime summaries for reader/verifier cost audit.
- Publishable-only verifier review and conservative anchor-repair skipping to reduce wasted first-run
  model work.
- Failed-run diagnostics for provider and transport failures.
- OpenAI-compatible model requests retry a typed connection interruption once after one second,
  within the remaining request budget. HTTP/configuration/response-format errors are not retried;
  cancellation interrupts retry waiting. Publishers and whole research runs are not auto-retried.
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

### Research Workspace: Next Product Slice (2026-10-27)

- The native overview, paper previews, reading navigation and source-evidence views are already
  implemented in PR #3. Do not repeatedly reopen accepted presentation work as a prerequisite for
  adding features. Deferred manual checks remain explicit, not an automatic block on all development.
- The user permits continuing related features in the current PR; merge, release or a new branch
  is not a prerequisite. Keep individual feature changes understandable and separately committed
  when authorized.
- **Per-paper research progress: implemented locally; offline tests and review passed.** Reuse
  existing acquisition/reader events, an additive typed protocol field and an App snapshot scoped
  to the current request and topic. Only attempted papers appear; reading completion is not verifier
  acceptance. Stop retains observed results, and a new attempt starts with empty progress. No
  candidate totals or message parsing are used. See the
  [implementation contract](superpowers/plans/2026-10-27-native-paper-progress.md).
- Verification: Python regression **963 passed, 2 opt-in frozen checks skipped**; Swift regression
  **338 tests in 60 suites passed** in the normal macOS graphical environment; Ruff, privacy and
  diff checks passed. Eight native rendered-view captures cover both UI languages, appearances
  and compact/full sizes, using fake queue/engine events. These are not a signed-App popover test.
- Read-only review identified and fixed URL-in-title leakage and identity collisions after audit
  URL truncation/redaction. Regression checks first reproduced both failures, then passed. Runtime
  source IDs are now computed before those transformations. No research, evidence or renderer rule
  was changed; sample Markdown/WeChat HTML stay byte-identical with/without progress forwarding.
- Source-closeout review reproduced an additional URL-redaction gap when a title URL contains an
  apostrophe in its path or query. The complete URL token is now removed before wire output;
  both new regressions first failed and then passed. Final Python checks: **965 passed, 2 opt-in
  checks skipped**; Swift: **339 tests in 60 suites passed**. Earlier signed candidates predate
  this source-only fix and were not rebuilt or replaced by the closeout.
- The per-topic snapshot is in-memory only. Popover/mode/topic changes retain it, but App restart
  does not reconstruct historical paper progress. Queue, reports and existing event artifacts keep
  their current persistence. A fresh separately signed candidate and bounded native offline
  acceptance were completed on 2026-10-28, without changing the old App or real configuration.
  The isolated QA popover showed independent paper states, retained them after stop/reopen, and
  cleared them for a new request; the prior offline report bytes stayed unchanged. It used current
  production views/workflow with a test-only runner and fake credentials (zero value reads), not
  real research. AX button presses were unavailable; public AppStore actions drove run/stop, and
  Escape/controller show drove hide/reopen after local status-item click simulation bounced open.
  Physical pointer, live-service, VoiceOver and multi-screen acceptance are not inferred from it.
- **Overview copy reduction (2026-10-28, unreleased):** removed the repeated research-focus label,
  merged a known running stage into one short headline, and moved the standing paper-progress
  rule into an information popover. Per-paper states, failure reasons/actions, report provenance
  and the reading/verification distinction remain; the active phase keeps an accessibility value.
  No research, protocol, report file or delivery behavior changed. Swift **339 tests in 60 suites**
  and Python **963 passed, 2 opt-in checks skipped**, Ruff, localization validation, privacy and
  diff checks passed. Eight bilingual light/dark compact/full rendered captures were inspected.
  A separate 49.6 MiB candidate has since been built with the existing signing identity; the old
  development App and real configuration were not replaced. An isolated QA executable using
  current production views/workflow and offline replacements supplied 16 owned-popover running/
  failure captures, covering both languages, appearances and sizes. The actual information glyph
  opened the unchanged rule in both languages and sizes. Help dismissal/focus remains unaccepted:
  synthesized Escape/repeated-click handling was inconsistent, and no physical-input defect was
  established. Static text is absent from this environment's AX tree, so visual conclusions come
  from inspected screenshots, not AX-text assertions. Zero real credential reads, no live services
  or delivery, and unchanged report bytes. The test App exited. This feature remains unreleased;
  VoiceOver and other deferred manual checks remain open.
- **Cross-day paper ledger (2026-10-28, unreleased source):** a shared Python projection
  reads saved public report metadata on demand. Paper identities exclude version; occurrences
  retain report, date, version, safe source URL and report-local reading locator. Native Papers
  adds search, all/with-reading/source-only filters, inclusion history and return navigation to
  the original report, public reading and evidence. A v1 reading does not mark source-only v2 as
  read; similar titles do not merge. Missing versions remain unknown and unavailable reports
  are flagged. An in-memory topic/report-reference cache avoids duplicate reads; there is no
  database, idle scan, model stage, copied prose or relationship inference. Offline checks use
  two dated reports, including the production frozen engine and restart loader; report/delivery
  artifacts are not rewritten. Native snapshots are layout evidence, not physical-input proof.
  Candidate-App control-path acceptance is recorded below; physical keyboard search entry,
  help dismissal/focus, VoiceOver and other deferred manual checks remain unaccepted.
  Normal App/configuration and the published Release are unchanged.
  Python **985 passed, 2 opt-in checks skipped**; Swift reported **350 tests in 61 suites passed**,
  with the ledger frozen-engine test enabled and the older frozen-daily/cover opt-ins left off.
  Ruff, localization syntax, privacy, diff and independent frozen-engine bundle/signature checks
  passed. Eight rendered list/history layouts were inspected in both languages and appearances.
  Read-only review findings and its refresh follow-up were reproduced, fixed and rechecked.
- **Independent ledger candidate acceptance (2026-10-28, unreleased):** rebuilt native code and
  the production frozen engine into a separate 50.08 MiB App using the existing certificate and
  unchanged designated signing requirement. Real candidate controls, not a replacement test
  host, exercised two explicitly synthetic dated reports: merged papers, v1 reading vs v2
  source-only, unknown versions, both filters, both original reports, full HTML, public reading,
  evidence quote/location, and return to the selected paper's history. Menu-bar collapse/reopen,
  compact/full retention and restart reconstruction/evidence lookup passed. Draft/HTML/index and
  isolated configuration bytes were unchanged; the normal App and both earlier candidate App
  trees were retained byte-for-byte. Within one session, reopening/navigation reused the ledger
  request; restart rebuilt it. All requests were offline ledger reads, with no research/delivery
  job, real service call or credential-value access. The candidate exited without helper residue.
  Keyboard search remains unaccepted: AX value assignment did not update the binding and
  synthesized text input was inconclusive. Successful filtering is not a keyboard-search claim.
  Native AXPress/owned-control mouse events are bounded automation, not physical-user,
  VoiceOver, multi-display or appearance-accessibility acceptance. No product-code repair,
  replacement of the normal App, Git staging, commit, push or Release update occurred.
  An initial post-acceptance ledger check passed seven tests but failed the evidence-entry
  scroll-offset test; an isolated repeat also observed zero offset. The bounded follow-up below
  diagnoses and fixes that failure rather than dismissing it based on the native control path.
- **Evidence-entry positioning follow-up (2026-10-28, unreleased source):** traced a native reader
  lifecycle race: the one-shot scroll request could run before the scroll layout was ready.
  Waiting longer in the assertion did not replay the missed request. The App now uses the
  scroll-content geometry update for initial positioning and consumes that request once; no
  fixed delay, polling, repeated scroll attempts, protocol or research change was added.
  Native regression cases cover English/Chinese and fresh/preloaded report contents, reaching
  the evidence section, retaining manual scrolling across resize, and switching papers at the
  top. Draft and HTML bytes remain unchanged. Python **985 passed, 2 existing opt-in checks
  skipped**; Swift **350 tests in 61 suites passed**, with the ledger frozen-engine check enabled.
  Ruff, privacy, diff, candidate bundle and existing-signature checks passed. A separately signed
  candidate reused the unchanged frozen engine: actual popover controls reached visible evidence
  without scroll-wheel input, expanded the quote and returned to the original report/history.
  Protected fixture files and old Apps were unchanged; only an offline ledger read was created,
  and the candidate exited without helper residue. This is bounded native automation, not human
  input or accessibility acceptance. Earlier manual limitations remain open. No live services,
  credential-value reads, delivery, staging, commit, push or Release update.
- **Approved source closeout (2026-10-28):** after checks and review, commit the shared ledger
  and protocol separately from native browsing, evidence positioning and acceptance documents,
  then push to the existing Draft PR. Exclude Apps and acceptance artifacts. This does not accept
  the pending manual checks or authorize merging, a Release update, live research or delivery.
  Review regressions additionally cover raw query identity, encoded/non-ASCII reading links and
  evidence positioning after local images settle. Eight native positioning cases use real scroll
  events for user-scroll checks. A fresh isolated native/frozen-engine bundle retains the old
  Apps; earlier manual acceptance limits are unchanged. See the dated ledger plan for details.
- **Confirmed scope: cross-day topic research workspace, with a graph as well as a list.**
  For one topic, accumulate papers across reports, preserve versions and first/latest inclusion,
  and return from each paper to its report, public reading and evidence. This is requested work,
  not an optional visual enhancement. The ledger source candidate above is implemented separately
  from the earlier per-paper progress slice; native graph/link records are still future work.
- **Topic paper map / research-question map:** browse the same accumulated records as a list and
  an interactive graph. Paper nodes, question/category groupings and explicitly recorded links
  should support selection, filtering and source/evidence lookup. Incremental updates must retain
  prior provenance; stopping a new run cannot erase earlier topic knowledge. The graph is not just
  a network-shaped decoration or a second independent copy of the ledger.
- **Separate the prerequisites:** first define stable paper-family/version identity and a
  provenance-preserving cross-report index; then define link/group records and their origin;
  finally render the native list/graph from those records. Human groupings, explicit citations,
  model-suggested relations and verified research judgments must remain distinguishable. Graph
  proximity or an automatic cluster is not proof of support, contradiction or scientific consensus.
- **Next agreed direction: topic knowledge organization, not a citation-first graph.** AI proposes
  topic-specific classification facets that the user can adjust. Papers may belong to multiple
  groups; features, reasoned associations and group/topic summaries should help research judgment.
  Keep AI synthesis distinct from verified paper claims, with stable paper/version and source
  provenance. The graph, cards and feature table are views of these records, not separate knowledge.
- Offer automatic organization off/on plus an explicit reorganize action, using one shared job.
  Automatic work processes changed inputs and affected summaries; explicit reorganization may
  reconsider the whole topic without restarting discovery or deep reading. No input changes mean
  no automatic model call. Failed/cancelled organization retains the last successful snapshot.
  Start with an explicitly requested organization of existing materials before automatic updates
  and the native graph. Periodic consolidation may later reuse the same job. This is agreed design,
  not implemented functionality or approval for live calls. Evaluate Graphify against these needs;
  no mandatory dependency or additional background service is approved.
- **Shared knowledge service, offline implementation (2026-10-28):** an explicit Python
  operation now adapts saved public deep reads, reuses ledger paper identity with separate
  version keys, and retains exact report/claim provenance. An injected existing provider returns
  keywords, features, proposed facets, multi-label groups, conservative paper associations,
  bounded synthesis and open questions. Strict validation rejects unknown/cross-paper references;
  cancellation, invalid output, changed inputs or failed promotion retain the previous snapshot.
  This first operation organizes the supplied complete report scope, not an incremental update.
  That service slice did not wire an App/CLI/bridge entry, automatic trigger, confirmed-facet
  editing or native graph; the subsequent manual App connection is recorded below.
  Offline fixtures and a retained two-paper report exercise adaptation/storage only; no real
  model-quality acceptance, secret access, search, rereading or delivery is implied. See the
  [service plan](superpowers/plans/2026-10-28-topic-knowledge-service.md).
- **Manual App organization, offline source candidate (2026-10-28):** the paper ledger now has
  an explicit organization action/status backed by that same service, the existing serialized
  engine queue and terminal-artifact recovery. It uses the configured reader route, not the
  verifier, with a cost confirmation; it does not rediscover/read papers or create delivery jobs.
  Saved snapshot reads are local and do not construct a secret manager. The App shows typed
  snapshot metadata/counts while full source-backed records remain in the Python snapshot.
  Original reports/delivery records stay separate. A separate signed candidate subsequently
  passed automated native-button acceptance with an offline model boundary: cancel confirmation,
  success, stop, failure retaining the old snapshot, and quit/reopen. One untranslated cancel
  label was corrected using the existing translation. Old Apps and saved reports were unchanged;
  no idle test engine/PDF helper remained. This does not establish live organization quality or
  a new resource benchmark. The following slice adds native classification; automatic refresh, a separate organizer-model picker,
  live organization quality and manual keyboard/focus/VoiceOver/multi-display checks remain pending.
  See the [native manual slice](superpowers/plans/2026-10-28-native-manual-knowledge.md).
- **Native classification graph, offline candidate (2026-10-28):** the existing saved-snapshot
  commands now project facets, multi-label group membership, versioned paper cards, features
  and exact saved claim/quote references. Native node connectors represent stored classification
  only, not citations, consensus or verified scientific relationships. Users can select a facet,
  filter by text/multiple keywords, open paper details and their membership/keyword/feature
  evidence, or return through ledger history. Unclassified and source-only papers remain
  accessible; source-only records are not given invented features. Topic selection/filter and
  graph scroll state stay in the existing App presentation model, not a new database.
  Read-only review identified and corrected long-source-quote rejection and inaccessible keyword
  citations. Existing reports and snapshots are not rewritten. Real organization quality,
  automatic/incremental refresh, relation/structure views, facet editing and manual accessibility
  checks are still separate work. An independently signed candidate passed automated Chinese
  native graph/detail, keyword/membership evidence, ledger-history return and close/reopen checks
  using a saved offline snapshot; zero model/research/organization/delivery jobs were created.
  English/dark graph layout was observed, but English-detail automation was blocked, not passed.
  Full Python regression and 372 Swift tests passed; larger-topic/long-scroll and remaining manual
  interaction checks are pending. See the [classification plan](superpowers/plans/2026-10-28-native-classification-graph.md)
  for the exact offline scope; this is not live model-quality or full Demo-parity acceptance.
- **Classification workspace layout, offline candidate (2026-10-29):** aligned topic/view controls
  and node columns, reduced the normal header to two rows, moved snapshot details into on-demand
  information, and replaced dashed edges with shared-stem connectors for stored membership only.
  Six synthetic papers cover two facets, overlapping groups, an unclassified paper and long
  bilingual titles. Eight native hosted layouts cover both languages/appearances at two widths;
  a separate read-only QA App exercised Chinese/light facet switching, empty-result group clearing,
  retained search and unclassified-paper evidence/return. Review corrections preserve stop/notices
  in history and the group clear action when no paper matches. Full Swift regression (377 tests),
  Python regression (two existing opt-in skips), Ruff, privacy, static bundle/signature and diff
  checks passed. Existing reports, bottom-layer sources and old Apps were preserved; no research,
  organization or delivery job ran. Long-list scrolling/restoration, physical keyboard focus/input,
  information-popover dismissal and accessibility/multi-display checks remain manual pending;
  do not treat transient/blocked automation as acceptance. No live classification quality or new
  resource benchmark is claimed. See the [layout plan](superpowers/plans/2026-10-29-classification-workspace-layout.md).
- **Partitioned classification and empty states, offline candidate (2026-10-29):** supersedes the
  connector display above with unframed classification sections and individual paper cards.
  Multi-membership cards retain the same versioned identity and saved evidence; an unclassified
  section remains available. Composite App-only scroll targets distinguish repeated cards without
  changing the protocol or stored knowledge. Classification/ledger/report empty states now keep
  navigation at the top, use a compact message and allow clearing active filters. Regular settings
  collapse repeated explanations; first-use provider guidance, errors and connection-check cost
  warnings remain visible. Full Swift regression passed 380 tests, followed by 22 focused final
  checks; Python regression passed with two existing opt-in skips. Native hosted layouts cover both
  languages/appearances at 640/720-point widths. The separate read-only candidate exercised native
  empty-state positioning/clear actions, multi-membership evidence/return, default-collapsed settings
  and English/dark layout; further scenario details are in the
  [partition plan](superpowers/plans/2026-10-29-partitioned-classification-workspace.md).
  Help expansion/closing and keyboard focus remain manually pending after unreliable automation;
  exact scroll restoration, VoiceOver and multiple displays also remain pending. Fixture labels are
  synthetic, not accepted AI classification. Real organization quality is the next separate task;
  no service call, credential-value read, delivery, Release update or new resource benchmark is implied.
- **Saved semantic relations, local offline slice (2026-10-29):** projects existing undirected
  relations and exact endpoint references to Swift, rather than deriving edges from classification
  membership or similarity. The native paper workspace adds a separate Relations view; classification
  and the ledger remain available. Nodes use actual versioned paper keys, with transient deterministic
  layout, type filtering, relation details and topic-scoped camera/selection. Existing report evidence
  navigation pins the saved report fingerprint and uses the ledger's paper index; changed reports
  cannot silently replace the snapshot source. Python saved-snapshot read and Swift decoding/hosted
  windows were exercised with isolated offline fixtures, not the independent HTML Demo data.
  English/Chinese light/dark captures and local AppKit edge clicks are observed; source-button physical
  input, full popover reopening, accessibility and multiple displays remain manually pending.
  Full regression and final review results are recorded in the
  [relation slice plan](superpowers/plans/2026-10-29-native-semantic-relations.md).
  Final checks passed 1,043 Python tests (two existing opt-in skips), 391 Swift tests, Ruff,
  privacy and diff checks. Read-only review's reversed-endpoint lane overlap was reproduced,
  corrected and re-reviewed. This is still uncommitted local source, not an updated installed App.
  No live model, credential-value read, delivery, shipping App/DMG or Release acceptance is implied.
  Real organization quality, automatic refresh and larger-graph layout remain separate work.
- **Saved semantic relations, independent candidate acceptance (2026-10-29):** supersedes the
  source-only packaging/popover status above. A separate arm64 QA App uses the existing local
  signing identity and isolated synthetic snapshots, preserving previous Apps and real configuration.
  Actual native accessibility button actions opened both endpoint reports and explicitly expanded
  their correct saved quotations. Returning from each paper retained the selected relation, 115%
  zoom and measured node positions; Escape and status-item reopening retained the same view.
  Normal exit left no candidate App/helper process. Read-only engine auditing recorded nine ledger/
  knowledge reads, no forbidden-I/O attempts and no queued/scheduled jobs. Protected report/snapshot
  and source/previous-App hashes stayed unchanged; signature, symlink, arm64 dependency and native
  code/resource path checks passed. The candidate intentionally embeds an isolated QA root and is
  not a shipping package. Only QA setup/timing corrections were needed, not product changes.
  Physical keyboard/VoiceOver, multiple displays, larger graphs and real organization quality remain
  pending; this does not claim Quit/relaunch camera persistence or a new full regression/resource
  benchmark. No real credential, model, search or delivery was accessed; no commit/push or Release
  update occurred. See the [relation slice plan](superpowers/plans/2026-10-29-native-semantic-relations.md).
- **First real knowledge-quality check (2026-10-29):** one isolated native organization job used
  existing MemConflict v1/MemGuide v2 public deep reads and 85 anchored claims. The actual development
  route was DeepSeek `deepseek-flash`, thinking enabled/high; one model HTTP request succeeded without
  research or delivery. Native classification, all four relation reasons/both-paper references and
  both local report/quotation routes were checked against the saved real output. Previous Apps,
  normal configuration and reports remained unchanged; package checks and clean exit passed.
  This supersedes the earlier wholly-unverified real-provider status, not the content-quality gate:
  three of six facets have no groups, two relationship types are overly broad, and some explanation
  clauses omit their specific supporting references despite those facts existing in the input.
  The output is useful for assisted reading, not accepted as a reliable autonomous knowledge map.
  Next: tighten classification/relationship/evidence criteria before a separately approved comparison;
  do not solve weak interpretation with decorative edges or silently rewrite this snapshot. No prompt
  or product changes, second organization, commit/push or Release update occurred. Broader-topic,
  automatic/incremental and manual accessibility gates remain separate. See the
  [quality checkpoint](superpowers/plans/2026-10-29-native-semantic-relations.md#first-real-organization-quality-check).
- **Knowledge prompt revision 2, offline regression (2026-10-29):** tightened populated-facet,
  concrete-relation and clause-to-reference instructions without changing the schema, validator,
  model routes, evidence gate or App. The first real snapshot and its acceptance files remain
  unchanged. A public 34-reference excerpt retains the original weak output; a separate hand-edited
  replay tests the service/storage/projection path, not model quality. Six added cases protect
  revision provenance, legacy readability, exact evidence, and previous-snapshot retention on bad
  citations. Focused/full Python passed (64 focused; 1,049 full with two existing opt-in skips),
  plus Ruff, privacy and whitespace checks. Prompt constraints are not deterministic semantic
  validation: real classification/relationship improvement still needs a separately approved
  comparison. No live call, credential read, UI change, App rebuild, delivery or commit/push occurred.
  See the [prompt revision record](superpowers/plans/2026-10-28-topic-knowledge-service.md#prompt-revision-after-the-first-real-check).
- **Single real knowledge prompt comparison (2026-10-29):** reused v1; ran only v2 once in a
  separate signed candidate. Same two public deep reads, 85 references, question/language and
  input fingerprint; same DeepSeek `deepseek-flash` thinking/high. One organization job/HTTP
  request succeeded. Empty facets decreased 3→0; the broad shared_evaluation edge disappeared;
  specific protocol/metric citations improved. This is partial, not uniform semantic acceptance:
  different_assumption remains weak, an example K=5 became an unqualified setting, and some
  clause references/interpretation labels are still insufficient. Native classification, three
  relation reasons/both source sets and correct endpoint report/quote content were observed.
  Automatic quote positioning is not accepted: final frame review found a target below the visible
  window despite correct accessibility text; follow-up scroll automation lost the transient popover.
  Its cause/manual scroll are separate pending checks, not a UI fix in this slice.
  Protected old results/reports, real configuration, previous Apps and source stayed unchanged;
  bundle/privacy/diff checks and clean exit passed. No research, second organization, delivery,
  product change, commit/push or Release update. One pair does not establish stable model-quality
  improvement or large-topic quality; see the [real comparison record](superpowers/plans/2026-10-28-topic-knowledge-service.md#single-real-v1v2-comparison).
- **Exact knowledge-reference positioning repair (2026-10-29, offline):** the failed comparison
  route discarded the claim index and scrolled only to the evidence section header. This was a
  real App target-selection defect, not resolved by a longer test wait. App navigation now retains
  and range-checks the exact claim index, using the existing post-image-layout scroll; generic
  ledger evidence still targets the section. No prompt, protocol, report or research-policy change.
  Four native reproduction cases first failed and then passed; three new methods cover nine
  parameter combinations including first/late claims, invalid indices and navigation reset.
  Full gates: Python 1,049 passed / two existing opt-in skips, Swift 394 passed, Ruff, privacy and
  whitespace checks. A separately signed read-only candidate opened the saved relation's MemGuide
  claim 7 and MemConflict claim 36 inside the actual visible viewport without manual scrolling;
  explicit disclosure showed each original quote, and return preserved the selected relation.
  New/old organization workspaces, prompt, reports, real configuration and previous Apps retained
  their hashes. No model, search, credential or delivery access; no commit/push or Release update.
  This supersedes the specific automatic-positioning pending item above, not content-quality,
  physical keyboard/VoiceOver or multi-display acceptance. See the
  [repair checkpoint](superpowers/plans/2026-10-29-native-semantic-relations.md#exact-evidence-navigation-repair).
- **Cumulative source review (2026-10-29):** the reviewed set contains 91 allowlisted code,
  test and documentation files, excluding private configuration, certificates, Apps and raw
  acceptance output. Two independent local reviews found no confirmed actionable defect.
  CodeRabbit raised one scope/capacity suggestion: add report/date selection and validate
  multi-week input. The current contract is explicit full-topic organization with a fail-before-call
  size guard; neither scope selection nor large-topic acceptance is implemented. The suggestion is
  retained as follow-up, not reported as an implemented fix or as zero review issues. Bilingual
  guides now make this limitation and the unreleased/partial-quality status explicit. Existing
  report, prompt, result/configuration and previous-App preservation checks passed. No new research,
  credentials or delivery were used for closeout; physical input/accessibility gates remain open.
  Fresh full checks passed: Python 1,049 / two existing skips and Swift 394, plus Ruff, privacy
  and whitespace checks. The first permission-restricted Swift invocation failed at Trash/AppKit
  boundaries; a normal-permission rerun passed without product changes. Intermediate model/service
  source trees also passed their bounded Python checks; optional frozen-workflow gates remain opt-in.
- The original roadmap-only change was followed by explicit approval for offline implementation,
  candidate acceptance and then source closeout in the existing Draft PR. Split per-paper progress
  and copy reduction into signed-off commits; exclude Apps, installers and acceptance artifacts.
  This approval does not authorize live research, credential-value access, delivery, merging or a
  Release update. Graph/link records and deferred manual checks remain separate next steps.

### macOS Local Beta: Current Closeout (2026-10-25)

This is the current work list. Dated checkpoints below retain their original evidence and limits;
their unchecked items are not a second backlog. A later scoped acceptance supersedes an earlier
blocked attempt only for the behavior it actually exercised.

- **Implemented and accepted within the recorded scope:** topic/provider setup, durable research
  queue, one-shot schedules, appearance/language, native popover, report reader, independent
  WeChat/Email operations, cover selection/upload, diagnostics and opt-in notifications.
  Real Gmail, WeChat draft and cover operations were already accepted; do not repeat them merely
  to finish this checklist. Keyboard/focus/sidebar and draft-retention acceptance are recorded
  below. Recent bootstrap/npm launcher/PDF error-boundary and Gregorian-date repairs have offline
  and bounded native acceptance, not new real-provider acceptance.
- **Final App and DMG published:** `ResearchRadar-v0.3.0b1-macos26-arm64.dmg` comes from merged `main`
  commit `e1eca67` and includes version `0.3.0b1`, the Codex diagnostic/privacy repair and preceding
  fixes. The native
  App, PDF helper and production engine were rebuilt with the existing signing identity.
  Read-only package, signature, dependency and embedded-archive/privacy checks passed, followed
  by isolated native startup, existing Chinese-report reading and exit. The old App and DMGs were
  retained; normal configuration was unchanged. No credentials, reports or developer caches are packaged.
- **Recorded offline resource check completed within scope:** the preceding signed App's
  idle/reader samples
  and 20 report reopen/dismiss cycles, 20 standalone non-live engine cycles, and separate frozen
  fake App research/post-start cancellation. See the measurements below; this is not a real-model
  memory profile, cold-first-frame benchmark, exhaustive leak proof or all manual acceptance.
- **Real Codex verification and Chinese reading passed with cached inputs:** after updating the
  selected npm Codex client, one isolated native App run reused both original readings, reviewed
  89 eligible claims with `gpt-5.6-luna/high`, and generated a two-paper Chinese report with 85
  publishable claims. The native reader opened it without garbled Chinese; no delivery ran.
  This closes the cache-to-verification/report/reader check, not a fresh discovery-to-report run.
  The earlier first-use attempt generated a topic and completed reading but failed at verification;
  a complete fresh first-use run is still unverified and needs separate authorization.
- **Deferred by the user, not passed:** VoiceOver speech/activation, multi-display interaction,
  Reduce Transparency/Increase Contrast and remaining broader accessibility/manual coverage.
  These are not blockers for this scoped local beta; do not claim full accessibility acceptance.
- **Known limits:** Keychain authorization can recur across builds/items; the local certificate
  does not establish prompt-free updates. Normal launch uses `ResearchRadar-Dev`, even from a
  copied App. The image is locally signed, not notarized; downloaded/quarantined Gatekeeper
  acceptance and suitability for general distribution remain unverified. Publishing this limited
  Pre-release does not change those limits. No automatic updater or release automation was added.

### macOS App Checkpoint

Checkpoint dates use Asia/Hong_Kong (UTC+08:00); raw logs may show the preceding UTC date.

#### App And DMG Refresh: Offline Acceptance (2026-10-25)

##### Final Package And Pre-release From Merged `main` (`e1eca67`)

- PR #1 passed CodeRabbit and DCO checks and was merged using Rebase and merge. The resulting
  tree matched the checked PR exactly. Python regression passed 945 tests with 2 opt-in frozen
  tests skipped; Swift reported 283 tests passed. Merged-tree Python regression, Ruff and privacy
  checks also passed. No research, provider/search call or report delivery ran for this release.
- Rebuilt native App, PDF helper and production engine from `e1eca67`, retaining the existing
  local signing identity. Versions match: full release `0.3.0b1`, short version `0.3.0`, build `2`.
  Non-live frozen preflight, signatures, dependency/symlink, package/privacy and read-only DMG
  checks passed. The audit inspected 61 regular files and 882 archive entries, without a private
  metadata waiver. The package contains no configuration, credentials, reports or developer caches.
- The final App is 48.6 MiB logically; the DMG is 24,802,070 bytes (23.7 MiB). Its published name is
  `ResearchRadar-v0.3.0b1-macos26-arm64.dmg`; [release notes](releases/v0.3.0b1.md) record its SHA-256.
  An independent DMG copy passed isolated normal startup, existing Chinese-report reading and exit
  without App-owned helpers. No GUI engine request was created. Old Apps/DMGs, normal configuration
  and source/copied report bytes were preserved. This was not a new resource benchmark.
- At 16:20 Asia/Hong_Kong on 2026-10-25, `v0.3.0b1` was published as a Pre-release, not Latest/stable.
  Only the DMG and `SHA256SUMS` were attached. A draft-stage download matched both local files
  byte-for-byte before publication; this does not establish downloaded Gatekeeper acceptance.
  Local ignored evidence is under `.build/release-v0.3.0b1-20261025-e1eca67/`.
  Earlier package/checkpoint records below remain historical and are not the current download.

##### Versioned Refresh From `276a62f`

- Built the native App, PDF helper and Python engine as `0.3.0b1`; App and nested engine metadata
  use short version `0.3.0`, build `2`, and full release identifier `0.3.0b1`. The same signing
  identity and designated requirements were retained. Sanitized-PATH non-live frozen preflight
  confirmed the engine's runtime version.
- `ResearchRadar-0.3.0b1-arm64-20261025-276a62f.dmg` is 23.7 MiB; the App is 48.6 MiB logically.
  Package audit inspected 61 regular files and 882 archive entries, with no private-metadata
  waiver, test engine, configuration, credentials, reports or developer caches. Read-only mounted
  and copied App manifests matched the signed candidate; the image was detached afterward.
- A copy from the image launched through the normal system App entrypoint using isolated local-only
  routes, a paused topic, no schedules and disabled delivery. The existing two-paper/85-claim Chinese
  report opened without garbling; source and copied report bytes were unchanged. Normal exit left
  no App-owned descendants. No GUI engine request, research, live model check, search or delivery ran.
- After acceptance, the old development App was retained by rename and the candidate installed in
  its place. Previous App bytes, all existing DMG hashes and normal configuration remained unchanged.
  Local ignored evidence is under `.build/app-version-20261025-276a62f/`; the release draft records
  the DMG hash. This is not new resource, fresh first-use or downloaded/quarantined Gatekeeper
  acceptance, and no tag or release was created.

##### Earlier Refresh From `e906f95`

- Refreshed the production Python engine from `e906f95`; native source was unchanged, so its
  previously verified UI/resources/PDF helper were reused. App and engine signing requirements
  matched the prior build. Static comparison confirmed the frozen diagnostic functions match
  current source; non-live engine preflight passed.
- The App is 48.6 MiB logically and the compressed DMG is 23.7 MiB. Audit inspected 61 regular
  files and 882 archive entries, with no private build-metadata waiver, test engine, configuration,
  credentials, reports or developer caches. A read-only mount and copied App matched the signed
  candidate. These are package sizes, not a new RSS or startup-performance measurement.
- The DMG copy launched normally with isolated, local-only routes, a paused topic, no schedules
  and disabled delivery. It opened an unchanged existing Chinese report; the screenshot showed
  readable text, contents and the original two-paper/85-claim summary. It exited normally without
  App-owned descendants. No GUI engine request, research, model check, search or delivery ran.
- Installed the verified candidate as the development App only after acceptance. The previous
  App was retained by rename, not deleted; its manifest and old DMG hashes stayed identical.
  Normal configuration and source/copied report hashes were unchanged. The image was detached.
  This remains a locally signed development beta, not notarized or downloaded/quarantined
  Gatekeeper acceptance. Evidence is local and ignored under `.build/app-refresh-20261025/`.

#### Codex Diagnostics And Scoped Live Acceptance (2026-10-24)

- **Repair:** shared CLI failures now include the exit code and redacted head/tail excerpts from
  stderr and stdout within the existing 500-character limit. Known Codex input echoes are removed
  before redaction and clipping. Connection-check excerpts include their truncation marker within
  that same budget, retaining both ends after newline escaping. Local-path redaction omits the
  rest of a path-bearing line, including paths with spaces. This changes diagnostics, not model
  calls, retries, evidence rules or rendering. Previously truncated records cannot recover their
  missing tail. Raw launch/timeout/nonzero-exit exceptions are not chained into tracebacks, so
  their original command/input cannot bypass the redacted message.
- **Offline coverage:** regressions cover long echoed prompts, both output streams, empty output,
  Unicode/CRLF, secret/path/port redaction and small excerpt budgets. The same bounded failure
  reaches pipeline progress and bridge events/error artifacts with the verifier stage preserved.
- **Client compatibility:** the original first-use run completed two readings but its verifier
  command failed. A separately authorized native short probe preserved the explicit server error
  requiring a newer Codex. After updating only the selected npm package from 0.142.1 to 0.164.0,
  a native short probe succeeded. Node, npm, other installations and normal configuration were
  unchanged. This is a tested version, not a universal minimum-version guarantee.
- **Preparation limits:** the first cache replay used a PDF page excerpt instead of its abstract
  and was stopped before any model call. Correcting that input restored both papers' eligibility.
  A terminal-launched replay then stopped during Codex initialization because the terminal sandbox
  blocked its state-directory writes. Neither attempt established model rejection or an App defect;
  neither was silently retried. Subsequent runs had separate authorization.
- **Native result:** the final isolated App copy retained the production UI, queue, supervisor,
  protocol and research pipeline. Its test-only engine supplied the original local PDFs and
  PDF-backed metadata, blocked new reader/anchor requests and omitted optional figure extraction.
  An offline check inside that App first confirmed Codex state-directory access without making
  model calls. No global permissions, credential ACLs or real configuration were changed.
- **One research run passed:** both reading and anchor-repair caches hit; no paper was reread.
  One real `gpt-5.6-luna/high` call reviewed 89 eligible claims and retained 85 publishable claims.
  Three successful localization chunks produced a two-paper Chinese report. The native App saved
  its report record and opened the report with readable Chinese. File hashes were unchanged by
  reading; the isolated App exited with no observed research helpers remaining.
- **Boundaries:** no search, WeChat or email delivery ran in that final replay. Normal App/config
  and original cache hashes were unchanged. This is cache-to-verification/report/reader acceptance,
  not a fresh end-to-end first-use run, image acceptance, or a public installer release. Raw requests,
  reports, screenshots, logs, local paths and receipts stay in ignored local acceptance data; only
  this summary is public. Final evidence: ignored `.build/cache-native-20261024/final-result.json`.
- **Closeout checks:** 946 Python tests and 283 Swift tests passed, with frozen offline workflow
  tests explicitly enabled. Ruff, privacy, bundle/signature and diff checks passed. All 13 public
  Markdown documents and 45 local links were checked; no personal paths, non-example email/IP
  values or credential-like material were found. Read-only review caught and verified the
  newline-clipping and space-containing-path regressions above. Those final diagnostic-only
  follow-ups were tested offline; no live provider or delivery was called again, and the normal
  development App and DMG were not rebuilt during closeout.

#### Current App: Offline Resource And Lifecycle Check (2026-10-24)

- [x] Measured the unchanged signed production development App at `21b464a` with isolated
  per-instance data, disabled delivery/login/notifications/schedules and an unchanged existing
  offline report. External QA sampling, not App background polling, recorded:

  | Phase | Duration | Native App RSS at end | CPU at end | App descendants observed |
  | --- | --- | --- | --- | --- |
  | Hidden, before reading | 300 s | 55.27 MiB | 0% | None |
  | Report visible | 30 s | 106.45 MiB | 0% | None |
  | Hidden after reading | 30 s | 103.31 MiB | 0% | None |
  | Hidden after 20 report cycles | 60 s | 82.62 MiB | 0% | None |

  Initial idle RSS ranged from 52.98 to 83.42 MiB and CPU from 0 to 7.5%; the last samples above
  are not constant-resource guarantees. Native RSS excludes WebKit XPC processes and does not
  measure the total cost of live model/Codex research.
- [x] Twenty real-popover report reopen/dismiss cycles used alternating Escape and status-item
  clicks. The selected report remained available; inspected first/last captures were not blank.
  Per-cycle hidden RSS ranged from 103.97 to 106.33 MiB, ending at 104.38 MiB before the final
  idle period. No persistent monotonic rise or App helper was observed. Six existing Swift
  reader lifecycle tests passed, including dropping the last App WebView reference and mixed
  Chinese/image/formula/anchor rendering. The native measurement does not directly inspect weak
  references or prove that system WebKit processes exit immediately.
- [x] Twenty standalone production-engine non-live preflights (10 success / 10 cancellation)
  left no process groups. These are not App-queue cancellation tests. A separate signed QA App
  with the frozen offline engine completed one native Run Now report with no delivery jobs;
  engine/helper descendants were observed during work and absent afterward. Its sampled native
  App peak was 79.11 MiB, not the aggregate engine/helper peak. A fresh isolated run cancelled
  after `started` finished as `cancelled` and left no descendants; this separate App peaked at
  81.31 MiB. These launches are not one continuous memory curve.
- The earlier native cancellation happened before the engine wrote any terminal/event artifact
  and retained the existing conservative `interrupted` / `terminal_unconfirmed` outcome. It is
  not counted as the successful post-start cancellation. Initial AXPress and test-root permission
  failures were QA-driver/setup issues; only the ignored driver/data were adjusted, not product
  code. The failed attempt artifacts remain available.
- Limits: `/usr/bin/leaks` reported restricted inspection for the signed process; its output is
  not a zero-leak result or an attributable product leak finding. LaunchServices returned the
  production App PID in about 0.61 s, not a measured cold first frame. A later true cold-start or
  long-duration/live-workload profile remains separate; no new performance threshold is claimed.
- [x] The production App is 50,930,309 logical bytes (51,068,928 allocated); its engine is
  46,180,760 logical bytes. Source App, five normal configuration/state files, source report and
  copied report stayed unchanged; the reader test created no jobs, and all QA instances exited.
  Evidence: ignored `.build/beta-closeout-20261024/resources.json`, `summary.json`, native captures,
  engine terminal artifacts and separate fake-job data. No real service, secret-value read,
  upload or send was requested. This does not supersede the explicitly deferred manual gates.

#### Updated Local DMG: Read-only Closeout (2026-10-24)

- [x] At `21b464a`, copied the current signed production development App without rebuilding or
  re-signing it. The new image is `dist/ResearchRadar-local-beta-arm64-20261024-21b464a.dmg`,
  **24,797,977 bytes**, SHA-256
  `524aeae0045d5ec63cb4140c1ba9ccb654bfc4233d561ddd49f3b28f39977fe2`.
  Old images and the existing App were not replaced.
- [x] Image verification and a read-only mount passed. Source, payload and mounted App file/link
  manifests and designated requirements matched; deep/strict signature, arm64 dependency,
  contained-symlink and embedded-archive/private-path checks passed. The mounted volume contained
  only `ResearchRadar.app` and a generic local-beta note. The audit inspected 61 regular files
  and 882 archive entries, with no build-prefix exception or user-data/signing-material inclusion.
- [x] The volume was detached, and the normal App manifest plus five normal configuration/state
  hashes stayed unchanged. This was packaging/read-only inspection, not a new Finder,
  quarantined-download, real-provider or delivery test. Evidence: ignored
  `.build/beta-closeout-20261024/package-result.json` and packaging driver.

#### Gregorian Report Identity: Offline Repair (2026-10-24)

- [x] Reproduced the PR bot's date defect: non-Gregorian schedule calendars generated era/year
  identities rejected by the engine and failed to match existing same-day reports/jobs.
- [x] Added one Core `ReportDate.string(for:timeZone:)` function using Gregorian dates and
  `en_US_POSIX`. Scheduling, Run Now, confirmed Run Again and today's-report comparison reuse
  it. The user's time zone is retained; scheduling hours and display calendars are unchanged.
- [x] Offline regressions cover Gregorian, Buddhist, Hebrew, Japanese and Islamic civil calendars,
  Hong Kong/Los Angeles/UTC day and year boundaries, leap day, same-day report/job suppression,
  unchanged local schedule time and the existing confirmed-retry flow. No system calendar,
  existing report, saved configuration, Python date validation or delivery behavior was changed.
- [x] Full offline Swift regression passed **283 tests**, including the enabled frozen workflow;
  repo hygiene passed **15 tests**. Privacy scan and diff checks passed.
- [x] Rebuilt the development App with the existing signing identity; the designated requirement,
  strict signature, bundle/dependency/private-path checks and non-live frozen preflight passed.
  Its production engine contains no offline fixture modules. The previous App went to Trash.
- [x] Native RED/GREEN acceptance used `-AppleLocale th_TH@calendar=buddhist` only on isolated
  test processes, not system settings. The old native Run Now sent `2569-10-24` and received
  `invalid_report_date`. The updated frontend with a separate frozen offline engine sent
  `2026-10-24` for Run Now, the native Run Again confirmation and the due schedule. The first
  fake report had 1 read / 6 public claims; the explicit rerun normally returned no new content.
  Same-day Run Now reused the scheduled report, and restarting kept exactly one scheduled job.
- [x] The actual updated development App also launched with the isolated completed-report data
  without creating another job. All test instances exited; no App/helper remained. The five
  normal configuration/state hashes and system AppleLocale stayed unchanged. Evidence: ignored
  `.build/date-native-20261024/result.json`, requests, terminal artifacts and native captures.
- The DMG refresh is covered by the current closeout above; real-provider acceptance remains
  separate. No live model/search, credential-value access or sending was used for this repair.

#### Three P2 Repairs: Offline And Native Acceptance (2026-10-24)

- [x] App topic bootstrap now resolves the configured provider/model through the existing shared
  routing function and passes its cancellation event. Missing routes and provider failures are
  not replaced with heuristics; an explicitly local route keeps its existing behavior. The
  shared structured-topic parser accepts a valid model-generated profile for a Chinese input
  without requiring English tokens in the description. Topic/schema validation remains intact.
- [x] The shared Codex provider recognizes the standard npm `env node` shebang and invokes an
  absolute Node runtime with the selected script and original arguments. It honors an existing
  PATH runtime, otherwise checks launcher siblings, the recognized npm prefix and common
  Homebrew/local bin directories; it does not search arbitrary ancestor bin directories, load
  a shell, or widen engine PATH. Native commands, quoted paths and CLI arguments are preserved.
  Missing Node fails before starting a child and is reported by the existing provider diagnostics.
- [x] The App PDF adapter converts only `PDFHelperError` into the existing skippable
  `FigureExtractionError`; helper text-decoding failures are also typed as helper errors.
  Timeout, nonzero exit, malformed JSON and malformed text skip the optional image stage with a
  diagnostic. Programming errors still propagate, and crop safety, same-paper claim binding,
  evidence gates and all renderer implementations remain unchanged.
- [x] Reproduced the original defects before implementation. Final Python regression:
  **913 passed**, with both opt-in frozen integrations enabled; **128** focused tests passed.
  The full Swift suite passed **280** tests, and its queue/report/restart integration passed
  separately against the newly frozen test engine. A complete source/frozen offline daily with
  a failed helper still produced a ready report with **6** publishable claims and no figures.
- [x] Built separate production and offline-test engines without replacing the normal App.
  Sanitized-PATH production preflight, compressed archive/private-path scans, Mach-O dependency
  checks and engine signature verification passed. The production frozen bridge generated a
  Chinese topic through a configured fake model executable and ran an npm-style launcher using
  a fake Node runtime under `/usr/bin:/bin`; network and Keychain were denied for these checks.
  Evidence: ignored `.build/p2-fixes-20261024/` with RED/GREEN logs, frozen checks and report
  artifacts. No real providers, real credentials or real delivery clients were used.
- [x] Updated `dist/ResearchRadar.app` with the repaired production engine, reusing the existing
  local signing certificate and identical designated requirement. Bundle/dependency/private-path
  checks and strict signature verification passed. The previous development App went to Trash;
  the normal configuration, queue, schedules and report-index files retained their original hashes.
- [x] Native offline acceptance used isolated per-instance data. In the updated production App,
  **Generate topic draft** accepted a Chinese-only description and showed the configured fake
  model's profile for review. The npm-style launcher found its fake Node runtime while PATH
  remained `/usr/bin:/bin`; neither is an actual Codex/Node integration test. A separately signed
  QA copy used the frozen offline engine and a deliberately failing helper: native **Run Now**
  produced a ready report (1 read, 6 public claims, no figures) with an image-skip diagnostic.
  **Read report** rendered it; restart preserved the same report and single successful job.
  WeChat/Email were disabled, and no delivery jobs were created. Both test instances exited.
  Evidence: ignored `.build/p2-native-20261024/` (fixtures, native captures and verification).
- [x] Precommit rerun: **913 Python tests** and **280 Swift tests** passed with the frozen
  integrations enabled. Ruff, privacy, bundle/dependency/private-path checks, strict signing,
  diff checks and normal-data preservation checks passed. Evidence: ignored
  `.build/p2-closeout-20261024/`.
- Actual npm/provider acceptance remains separate. The latest closeout image now includes
  these repairs. No API-key values, real providers or sending were used in this checkpoint;
  it adds no UI, protocol command, dependency or auto-retry.

#### System Launch And Initial PR Review Verification (2026-10-24)

- [x] At `c021fc0`, launched the unchanged signed DMG App copy through
  `NSWorkspace.openApplication` / LaunchServices, with a new per-instance data-root override,
  a paused test topic, empty queue/report index/schedules and disabled delivery, login and
  notifications. The system resolved the requested copy, displayed the unique test topic in
  its native popover and required no launch confirmation. Native-menu exit passed; the first
  test-driver AXPress was unsupported, so the identified Quit menu item was clicked instead.
- [x] The two normal App/engine manifests and five normal configuration/state hashes remained
  unchanged. The copy's signature and bytes stayed intact, Gatekeeper still reported
  `assessments enabled`, and quarantine attributes were unchanged. No App/helper under the test
  bundle remained and no research or delivery jobs were created. No provider/search probe,
  credential-value action or sending was requested; bootstrap uses metadata-only credential
  presence queries. Unlike the earlier sandbox-entry test, this was a normal system launch,
  not a claim that LaunchServices inherited the earlier deny-network sandbox.
  Evidence: ignored `.build/system-launch-20261024/result.json` and native captures under
  an isolated temporary directory outside the repository.
- [ ] The local image had no quarantine attribute before this test. No attribute was removed,
  no Gatekeeper rule was changed, and no App was rebuilt or re-signed. This proves the scoped
  local system-launch path, not a physical Finder double-click, downloaded/quarantined
  distribution approval, notarization or final beta acceptance.
- [x] At the initial review checkpoint, verified all three supplied P2 issues against source
  and offline reproductions, without changing production implementation or committed tests.
  Evidence:
  ignored `.build/review-validation-20261024/result.json`; Python socket/Keychain guard and OS
  deny-network sandbox covered these reproductions. The npm-style launcher was a local fake,
  not the real Codex executable; PDF failures used an injected runner, not the native helper.
- [x] **Topic bootstrap route (original defect):** the App handler called `bootstrap_topic_draft()`
  without a provider/model, ignoring the configured route. Route resolution was never called; the pure
  Chinese description failed with no searchable terms. The source/offline repair is recorded
  above; no evidence policy was weakened or heuristic disguised as a model-generated topic.
- [x] **npm Codex runtime (original defect):** the engine's `/usr/bin:/bin` PATH could not resolve
  Node for an accepted `#!/usr/bin/env node` launcher. The offline launcher returned 127. The
  repair above preserves bounded process setup and resolves the configured executable's runtime
  dependency. Finding the launcher still does not establish working connectivity.
- [x] **Optional PDF figures (original defect):** helper timeout, nonzero exit and malformed JSON
  each escaped
  `app_figure_extractor()` as `PDFHelperError`; the pipeline only skips `FigureExtractionError`.
  The typed-error control correctly produced a skipped-figure diagnostic. The repair above
  restores that optional-image boundary without swallowing unrelated failures or changing
  renderer/evidence behavior.

#### Local DMG: Isolated Production Startup And Reader Acceptance (2026-10-24)

- [x] At `2203b39`, mounted the sysconfig-clean image read-only, copied its signed App to an
  independent temporary directory outside the checkout, compared all file bytes/modes/link
  targets, and detached the image. The App was not rebuilt, re-signed or installed over another
  copy. Its production entry/bootstrap ran with an explicit development-data-root override,
  sanitized PATH and an OS sandbox denying network, Keychain access, checkout reads and helper
  execution. This is the actual packaged App, not the earlier fixture UI host.
- [x] Native status-item clicks opened, hid and reopened the anchored popover. Compact/expanded
  transitions retained the selected report. One existing structured offline report rendered
  with its local figure; a second existing bilingual static fixture rendered Chinese/English,
  a local image and static formula text. Its formula contents link navigated to the local
  fragment. Screenshots and native accessibility captures record the actual reader. A second
  launch loaded the isolated persisted report index; both launches quit through the native menu.
- [x] No research jobs or schedules were created, both delivery channels and notifications stayed
  disabled, and no credential-value action was invoked. Final process checks found neither test
  App PID nor an executable under its copied bundle. The two normal App/engine manifests, five
  normal configuration/state hashes, copied report bytes and test App signature stayed unchanged.
  Test-driver compile/label/post-exit inspection errors were corrected; no product-code fix was
  warranted. Evidence: ignored `.build/dmg-launch-20261024/result.json`; native captures and the
  stopped copy remain in an isolated temporary directory outside the repository.
- [ ] This sandboxed entry launch does not establish Finder/LaunchServices, quarantine or
  Gatekeeper installation acceptance, public distribution, or active-research/resource gates.
  Hidden-state AX captures are not proof of weak-reference release or all system WebKit process
  termination. The data override is test-only; the image still defaults to development storage.
  VoiceOver and other previously open manual gates remain separate. No commit or push here.

#### Frozen Python Metadata: Relocatable Build And New Local DMG (2026-10-23)

- [x] Reproduced the privacy gap with compressed PYZ/ZIP fixtures: the old verifier inspected
  outer bytes but missed CPython's embedded builder prefix. A build-only generator now supplies
  the same sysconfig module and variable keys, preserving values except that the Python install
  prefix resolves to `sys._MEIPASS` in a frozen engine. Both production and offline-test specs
  use it. It does not modify installed Python, CLI configuration, research logic or renderers.
- [x] Bundle verification now inspects compressed Python archives and stdlib ZIP entries without
  importing their modules. The old engine is rejected for its sysconfig path; the rebuilt engine
  passes without a module exception. Generic redaction patterns are not mistaken for concrete
  temp-file paths. Tests also protect non-path values and the host sysconfig source/dictionary.
- [x] Python **892 passed**, including the newly rebuilt frozen workflows; **21** focused packaging
  tests, Ruff and the signed isolated engine's non-live sanitized-PATH preflight passed. The
  frozen offline report/PDF/simulated channel check and Swift's one frozen queue/restart test
  passed. A first OS-sandboxed measurement attempt failed because `/bin/ps` could not run; that
  evidence is retained. The successful rerun used the existing parent socket/Keychain guard and
  the test engine's socket/process audit guard, never real providers or sending clients. This
  is not a complete Swift/UI or live-service acceptance claim.
- [x] Assembled and signed only a new isolated App using the existing certificate. Its new
  **24,797,031-byte** DMG passed checksum verification, read-only mount, **61 regular-file /
  36 symlink** equality, dependency/signature and **882 archive-entry** checks, with no builder
  metadata-path exception or personal runtime artifacts found. The image was detached. Existing
  development App, original engine, installed Python sysconfig source and normal App state were
  hash-verified unchanged; the previous image is retained. No original App was overwritten.
  Artifact: ignored `dist/ResearchRadar-local-beta-arm64-20261023-sysconfig-clean.dmg`;
  evidence: `.build/sysconfig-fix-20261023/`, including `result.json`, frozen verification,
  RED/GREEN logs and protected-input manifests.
- [ ] The new image remains a locally signed development build, not an installed or notarized
  release. It still uses the development data root if later launched. VoiceOver, broader native
  acceptance and final resource/lifecycle gates remain separate. No real research, upload,
  delivery, stage, commit or push was performed in this repair.

#### Local Test DMG: Read-only Packaging Check (2026-10-23)

- [x] Packaged the existing `ac73aa4` development App into a local-only arm64 DMG without
  rebuilding, re-signing, installing or launching it. Only the App and a generic local-beta
  notice enter the image; the normal development App and its configuration/state files remain
  unchanged. Existing local certificate and designated requirements are preserved.
- [x] Image checksum verification and read-only mount checks passed. The mounted App matches
  all **61 regular-file hashes/modes and 36 symlink targets**; recursive bundle/dependency and
  deep/strict signature checks passed. Inspected files and **882 Python/archive entries** for
  runtime artifacts, developer output and credential indicators, without reading real secrets.
  No personal configuration, credential files, reports or development caches were found.
  The **24,800,084-byte** image was detached after inspection. This is not installation,
  launch, Gatekeeper or final-beta acceptance, and no reusable release-packaging command was
  added. Ignored artifact: `dist/ResearchRadar-local-beta-arm64-20261023-ac73aa4.dmg`;
  evidence: `.build/local-dmg-20261023/result.json` and command logs.
- [x] The initial image's frozen CPython `_sysconfigdata__darwin_darwin` module retained the builder's Python
  installation prefix in its build metadata. This is not copied user configuration or a
  credential, but the image is **not private-path-free**. The local-beta notice records this
  limitation. The follow-up above resolves it in a new build/image without changing this
  earlier artifact or silently treating its warning as a clean scan.
- [ ] This unchanged development build would still use `ResearchRadar-Dev` if later launched;
  mounting/copying it does not isolate existing user data. Installation/launch, VoiceOver,
  final resource/lifecycle and broader manual gates remain separate. No real service, upload,
  delivery, commit or push was performed during this packaging check.

#### VoiceOver Core Controls: Native AX Inspection, Speech Acceptance Pending (2026-10-23)

- [x] At `ac73aa4`, an isolated, certificate-signed host linked the current production RootView,
  status-item controller and anchored popover with two copied offline report fixtures. It has no
  engine; secret, notification and login-item integrations use offline substitutes. Networking
  is denied by the OS, schedules remain paused, and no real credentials or deliveries are used.
- [x] Read-only native accessibility-tree inspection in English and Simplified Chinese found the
  ResearchRadar menu extra with status help, sidebar controls and entries, Run Now, both dated
  report actions, and the settings controls. Fixture-directed page changes are inspection setup,
  not proof of VoiceOver navigation or activation. Source report bytes and normal configuration
  and state files were preserved. No product-code defect was established or fix added.
- [ ] Actual VoiceOver speech, core-control traversal and activation await user-assisted
  acceptance. VoiceOver was off during the recorded AX inspection; the App did not enable it
  or change system accessibility preferences. Do not count names in the AX tree as a successful
  screen-reader test. Ignored evidence: `.build/voiceover-20261023/`, including build fingerprints,
  per-language/page AX captures and `ax-summary.json`. Production-bootstrap, wider forms and
  multi-display acceptance remain separate.

#### Keyboard Navigation: Focus Fix And Bounded Native Acceptance (2026-10-23)

- [x] Reproduced invisible expanded-workspace controls receiving Tab focus in compact mode.
  The regression failed because the retained sidebar could still become a native key view.
  A private native container now hides the retained workspace instead of relying on opacity
  and hit testing; its hosted root remains stable and observes the existing stores directly.
  No engine, renderer, scheduler, keyboard shortcut or dependency was added.
- [x] Regressions verify the hidden sidebar leaves keyboard navigation, the same sidebar returns
  on expansion, and compact mode releases the actual reader/WebView while retaining report
  selection and unchanged HTML. A non-secret unsaved Author also survived native mode changes.
  An intermediate re-rooting implementation produced AttributeGraph warnings; it was removed.
  The final isolated launches did not produce those warnings.
- [x] The user enabled macOS Keyboard Navigation; the App did not change the global preference.
  The user then confirmed real Tab/Shift+Tab movement through Chinese Settings. Earlier isolated
  English/Chinese runs exercised safe sidebar/mode controls with visible focus; Space activated
  those controls, while Return did not activate the non-default expand button. This is not a
  claim that Return activates every macOS button or that every form was checked.
- [x] Final offline checks passed: Python **885**, Swift **280 across 48 suites**, including the
  enabled frozen workflows, Ruff, privacy and diff checks. Read-only review found no actionable
  issues. All native hosts had no engine, a forbidden secret-value backend and denied networking.
- [x] After the final-source English/Chinese automation was interrupted by transient-popover
  focus loss, the user completed manual acceptance in the isolated native popover and confirmed
  both languages worked: Tab/Shift+Tab focus movement, Space activation, sidebar toggling and
  compact/full switching. The host used the current production UI components, no engine,
  offline secret/system-service substitutes and OS-denied networking. Neither interrupted
  automation run is counted as passing. The development App was rebuilt with the existing
  signing identity and unchanged designated requirement; normal configuration and state files
  were unchanged. Evidence: ignored `.build/keyboard-manual-20261023/` and
  `.build/keyboard-qa-20261023/`, including `native-final.json` and RED/GREEN logs.
- [ ] Broader form coverage, VoiceOver, multi-display and production-bootstrap keyboard
  acceptance remain separate; this bounded manual result does not close those gates.

#### Unsaved Draft Retention: Bounded Native Acceptance (2026-10-23)

- [x] At `e41b74a`, an isolated host linked unchanged production RootView, Settings, AppStore,
  StatusItemController and the default transient WindowCoordinator. A non-secret Author field
  was edited through accessibility without pressing Save. CGEvent Escape, a click in an inert
  owned window outside the popover, and native compact/expand controls each preserved the draft
  after reopening. Settings navigation and the preselected nondefault topic/report also remained.
- [x] Eight snapshots confirmed the saved Author was unchanged, zero jobs and secret-value
  accesses, and the same topic/report selection. Networking was denied and no engine was present.
  Four real App data files and linked production objects stayed byte-identical; the QA App exited.
  No product fix was needed. Evidence: ignored `.build/draft-retention-20261023/acceptance.json`.
- This covers one field and simulated native input, not human typing, every form, production
  bootstrap, background-job continuity, unsaved drafts across process restart, VoiceOver or
  multi-display behavior. Those broader gates remain open.

#### Codex Executable Paths (2026-10-23)

- [x] The App configuration adapter encodes a literal executable path for the shared CLI provider;
  daily admission decodes and validates that single executable before research starts. Paths with
  spaces, Chinese characters, quotes or shell metacharacters are not split into extra arguments.
  CLI command strings retain quoted-path and additional-argument support.
- [x] Offline regressions cover App configuration through daily admission and provider invocation,
  plus a real local fake executable with CLI arguments. No real Codex or provider is called.
- [x] Rebuilt the development App with its existing local signing identity; bundle checks and the
  non-live frozen preflight passed. The user selected a local executable whose path contains spaces
  and Chinese characters in the production file picker hosted in an isolated native settings window.
  A new QA process restored the exact path and displayed `Executable found`; saved configuration
  bytes were unchanged. Shared configuration conversion kept it as one executable token. The selected
  executable was never started, no secret values were read, and the real config/queue/report index/schedules were unchanged.
- [x] Confirmed the production `StatusItemController`, `WindowCoordinator` and settings flow in a
  separate isolated host, retaining the default transient popover rather than using a stable window.
  Cancellation left configuration unchanged; the user selected the spaced/Chinese fixture through
  the native picker, and status-button hide/reopen preserved it. A new process restored the same
  configuration bytes; three CGEvent-based pointer open/hide cycles then passed with the path
  intact. No engine or real credentials were available, and the four real data files stayed unchanged.
  AX-driven sequences had inconsistent open/hide observations; their failure logs are retained and
  are not treated as passing automation. This does not cover production application bootstrap,
  real Codex login, model access or paper-verification quality.

#### Three-State Offline Resource Check (2026-10-22)

- [x] Reused current release module objects at `ec5a5fd` and an existing frozen offline report,
  copied byte-for-byte. The isolated native host mounts production `ResearchRadarRootView`,
  `WindowCoordinator` and the restricted reader. It has no engine, real secret store, schedules
  or notification client activation; networking is denied. Signal-driven test actions add no
  App polling loop. This is not production-bootstrap or active-research resource acceptance.
- [x] Before opening any report, 300 seconds / 61 external samples observed no reader/WebView
  or descendants. Native-process RSS ended at **52.16 MiB** (range **34.00-77.95 MiB**, including
  startup/transient variation); final sampled CPU was **0.0%**. The sampled CPU mean was 0.61%,
  including the initial 27.2% startup sample; `ps` samples are not integrated CPU/energy readings.
- [x] A first 30-second reading attempt was interrupted by transient-popover dismissal. Retained
  that failed attempt, then restarted the same signed host for the two remaining states. The
  successful 30-second reading sample kept exactly one loaded WebView; RSS ended at **100.86 MiB**.
  After explicit collapse and 60 seconds, both reader-host and WebView weak references were nil,
  the view tree had neither object, and report selection remained intact. RSS ended at **81.23
  MiB**, with sampled CPU 0.0% throughout the collapsed interval. These are two host launches,
  not a continuous same-process idle-to-reading memory curve or a long-term leak test.
- [x] No descendants or research/PDF helpers remained. WebKit XPC candidates were recorded
  separately without claiming attribution from parent PID alone; the newly observed reading
  candidates were absent by the final collapsed sample. Native RSS excludes those system
  processes and is not total reader memory. Secret-value accesses were zero; original App data,
  source report bytes and release inputs stayed unchanged. No product-code fix was warranted.
  Evidence: ignored `.build/resource-three-state-20261022/resources.json` and
  `reader-followup.json`. Wider multi-cycle, production startup and accessibility gates remain
  separate. No research, upload, delivery, commit or push was performed.
- [x] On 2026-10-23, moved only the temporary `ResourceAcceptance.app` to Trash after explicit
  user approval. The normal development App executable and Info.plist hashes stayed unchanged.
  Retained ignored measurement evidence and confirmed its values against this checkpoint;
  repository-hygiene tests passed (15 tests). Cleanup did not rerun research or send anything.

#### Report Completion/Failure Notifications: Offline And Native Acceptance (2026-10-22)

- [x] Added an explicit, default-off Settings switch. Only enabling it may request notification
  permission. Opening the App/settings, saving schedules and finishing tasks never request it.
  The App-only preference is atomically saved in runtime state; old state defaults to disabled.
- [x] Reused durable research job/report outcomes after queue persistence. Effective public reports
  and failed/interrupted research notify; empty results, cancellations and channel delivery do not.
  No engine command, pipeline change, timer, background helper or external dependency was added.
- [x] Fixed English/Chinese text and known public failure stages exclude topic/report prose,
  raw errors, credentials, accounts and paths. Click targets are UUIDs revalidated against local
  state before opening the corresponding report or Diagnostics. Reminders are session-deduplicated;
  launch reconciliation does not replay historical notifications or retry uncertain submissions.
- [x] Offline tests cover permission denial/errors, saving failure, legacy state, disabling during
  authorization lookup, private canaries, deduplication, actual queue success/failure and restart.
  Failed notification submission leaves successful reports and research errors unchanged.
- [x] Swift **274 tests across 48 suites**, Python **870 passed** with frozen workflows enabled,
  Ruff, privacy and diff checks passed. Native English/Chinese Settings controls were enabled and
  disabled with a fake notification client: no permission access before clicking, one simulated
  request, and correct persisted preferences. Evidence: ignored `.build/notifications-20261022/`
  and `.build/notifications-focused-20261022.log`.
- [x] Read-only review identified forced-cancel failure reminders and compact-mode navigation
  after a preference-write failure. Both were fixed with regressions; re-review found no new
  concrete issues. Cancellation stays observable until notification eligibility is decided;
  a transient expanded Diagnostics fallback does not pretend a failed preference save succeeded.
- [x] Reassembled and opened the development App with the existing local signing certificate;
  bundle/signature validation and non-live dependency preflight passed. The notification switch
  remains off. All existing configuration, report and job files stayed byte-identical; no engine,
  PDF helper or offline QA window was left running. Build evidence: the ignored slice directory's
  `bundle.log`.
- [x] Separate native acceptance used isolated offline reports and simulated failures with the
  existing signing identity. The user allowed the real macOS permission prompt; success-banner
  activation selected its report, and failure-banner activation opened Diagnostics. Fixed a
  navigation action clearing the notified failure code; its regression and all 274 Swift tests
  passed. The final single-instance check retained `model_transport_failed` with the popover open.
  Four local test notifications were delivered (one success and three distinct failure fixtures).
  Earlier overlapping QA instances were stopped; the clean final check is the acceptance evidence.
  Evidence: ignored `.build/notification-system-20261022/`. No research, upload or delivery ran.
- [x] Precommit reruns passed: Python **870**, Swift **274**, Ruff, privacy, bundle and signature
  checks. Staged CodeRabbit review covered all 16 files, including new services/tests. Removed
  iOS-only `ephemeral` authorization handling after checking the macOS SDK; message assertions now
  require a value before inspecting it. The suggested extra expanded-mode fallback was redundant:
  successful notification navigation already persists full mode; failed saves use the fallback.
  Evidence: ignored `precommit-coderabbit*.ndjson` and `precommit-*.log` in the native slice directory.
- [ ] Native routing evidence does not establish report-body rendering from the unavailable final
  screenshot. Partial-delivery/unknown-delivery notifications, DMG and other final gates remain
  separate; previously pending broader manual gates are not closed by this notification check.

#### Copy Redacted Diagnostics: Implementation And Acceptance (2026-10-22)

- [x] Added the bilingual copy action and local success/failure feedback in Diagnostics. A small
  App-only allowlist projection copies platform/app versions, supported configured routes,
  typed runtime/task/report/channel state and known error codes. It never serializes raw
  configuration, error prose, topic text/IDs, account details, paths or report contents.
- [x] Copying only uses existing in-memory state and local platform metadata. It does not query
  Keychain, run preflight, start an engine, write state, upload or send. Unrecorded versions and
  unknown/custom identifiers use fixed placeholders instead of raw values.
- [x] Offline tests cover selected-topic isolation, private-value canaries, unchanged App state,
  no extra credential access, empty state, bounded version parsing and bilingual layout. Native
  copy-button actions in separate English/Chinese offline windows wrote only to private test
  pasteboards with fake credentials and no engine; both returned the expected safe failure state.
  In-process SwiftUI AX traversal did not expose the control, so native clicking was checked
  outside the unit-test host, not claimed from component rendering.
- [x] Swift **260 tests across 47 suites**, Python **870 passed** with frozen workflows enabled,
  release compilation, Ruff, privacy and diff checks passed. Swift/native checks ran with OS
  networking denied. The initial Python OS-sandbox attempt passed 868 tests but blocked `/bin/ps`
  in `test_frozen_accepts_actual_swift_config` and `test_frozen_pipeline_and_delivery`; both passed
  in the full rerun using Python socket/DNS/Keychain-read guards and the existing frozen child's
  external-IO block. Original sandbox failures are retained, not counted as product regressions.
  Review was local and read-only; no networked reviewer was invoked.
- [x] On 2026-10-22, rebuilt and opened the development App using the existing local signing
  certificate. App and engine designated requirements were unchanged; configuration, reports and
  job artifacts remained byte-identical. Swift **260 tests across 47 suites**, bundle validation,
  signature checks, non-live dependency preflight and privacy scan passed. The user accepted the
  native copy button. No real credentials, research, upload or delivery were invoked for acceptance.
  Build evidence: ignored `.build/diagnostics-update-20261022.log`.
- Notifications, complete diagnostics tooling and the remaining manual/resource gates are outside
  this slice. Cross-version Keychain authorization remains a separate known limitation. Original
  offline evidence: ignored `.build/diagnostics-20261021/`.

#### App WeChat Cover Entry: Implementation And Acceptance (2026-10-21)

- [x] Added selection, a bounded local preview and explicit upload confirmation in WeChat
  Settings. PNG/JPEG inputs are limited to 2 MiB and 40 megapixels by App policy. Original images
  are not edited; the confirmed bytes are staged privately and bound to the result by SHA-256.
- [x] Reused the single engine execution gate and existing permanent-material client. A separate
  typed `upload_wechat_cover` command returns a receipt, not a research or delivery job. Only the
  App applies a confirmed media ID through its existing atomic configuration writer; reports,
  channel results, author, enabled state and CLI behavior are unchanged.
- [x] Offline tests cover invalid images/paths, stale selection/credentials, uncertain outcomes,
  wrong result hashes, persisted cover ID and retrying only local saving after upload success.
  Selection/layout performs no credential-value reads. Upload is never automatically retried.
- [x] Python **868 passed / 2 skipped**; Swift **255 tests across 46 suites**, with both frozen
  workflow tests explicitly enabled. The cover-focused suite also passed all ten tests after
  the latest JPEG and component-capture checks. Ruff, privacy, diff, release, bundle, signing
  and non-live bundled preflight checks passed. Read-only review found and verified closure of
  a path re-read race: multipart now uses the validated bytes, not a second file read. Frozen
  testing also caught and fixed equivalent system-directory aliases without relaxing job scope.
  Evidence is retained in ignored `.build/wechat-cover-20261021/`.
- [x] During offline checks, real saved cover and report/email hashes remained unchanged, with
  the same 12 historical jobs, zero new/active jobs and no leftover engine/PDF helper.
  No actual upload or delivery ran during those checks.
- [x] Native-control acceptance in an isolated host using the current production views:
  opened the file picker, cancelled before selection, selected the PNG fixture, visually checked
  its preview and dimensions, cancelled upload confirmation, cancelled replacement selection,
  and reopened the menu-bar popover with the selection retained. Existing cover ID was unchanged;
  engine starts, credential-value reads/writes and jobs remained zero. Real App configuration,
  queue and report index retain their hashes. Evidence and native-window screenshots are in
  ignored `.build/wechat-cover-native-20261021/`.
- [x] Separately authorized one live cover upload from the actual staged App's native picker and
  confirmation button, using existing configuration and the same test PNG. Cancellation was
  checked first; a one-shot guard prevented a second confirmation. WeChat returned a successful
  receipt, the image hash matched, and the native UI showed **Uploaded and saved for future
  drafts**. Only the default cover ID changed. The 12 historical queue jobs, report index and
  262 workspace-file hashes were unchanged; exactly one new engine request was for cover upload,
  not research or delivery. No engine/PDF helper remained. Evidence and native screenshot:
  ignored `.build/wechat-cover-live-20261021/`.
- No draft, research, email, automatic retry, commit or push ran in live cover acceptance.
  The uploaded test image is now the default cover; existing drafts are unaffected. Native
  automation used accessibility and guarded synthetic input, not physical-user input. Other
  manual accessibility/multi-display gates remain separate.
- [x] Precommit rerun: Python **870 passed, no skips** and Swift **255 tests across 46 suites**
  with both frozen workflow checks enabled against a freshly built, network-blocked test engine.
  Ruff, privacy, diff, release/bundle/signing verification and non-live bundled preflight passed.
  CodeRabbit reviewed all 30 changed files and raised 0 issues. No additional live operation ran;
  real queue/report/workspace hashes and the single confirmed cover receipt remain unchanged.
  Logs are retained in ignored `.build/wechat-cover-precommit-20261021/`.

#### WeChat Entry: Restart Acceptance (2026-10-21)

- [x] Cold-launched the staged development App and opened the existing report through the native
  status item. Its WeChat row still shows **Draft created**, and its email row still shows **Sent**.
  The saved queue remains at 12 historical jobs with no active or new job. All schedules remain
  paused; no research, search, credential-value read, draft creation or email was requested.
- [x] Original `article_draft.json`, `wechat.html`, `daily.md` and the prior email result retain
  their acceptance hashes. Native restart evidence is in ignored
  `.build/wechat-precommit-20261021/native-restart.json`.
- [x] Precommit checks passed: Python **856 passed / 2 skipped**, Swift **245 tests across 45
  suites** with the rebuilt offline frozen workflow explicitly enabled, Ruff, privacy, diff,
  release build, bundle verification, deep/strict signing and non-live bundled preflight.
  Independent read-only review found no concrete issue. The newly staged App was cold-launched
  and checked again: the same delivery states and queue remain, with no idle engine/PDF helper.
  Build and frozen-workflow evidence is retained in ignored `.build/wechat-precommit-20261021/`.
- This completes the successful WeChat record's native restart check, not the remaining cover
  upload, notification, packaging or broader manual/resource gates.

#### Native WeChat Draft: User Acceptance Passed (2026-10-20)

- [x] Under fresh authorization, operated the real App confirmation/cancel flow and then
  dispatched exactly one creation confirmation for the existing Chinese report and saved cover.
  One new WeChat job, `A14D5064-BCD9-48A5-8D7E-4E892778620B`, succeeded at **15:49:22 HKT**.
- [x] WeChat returned `created`, `draft_created=true` and a nonempty draft media ID. Six body
  images were uploaded, the configured cover was reused, and the request remained draft-only
  with `auto_publish=false`. No research, email, publication or broadcast was requested.
- [x] Native report UI displays **Draft created** while email remains **Sent**. The successful
  WeChat record is persisted in the report index. Original draft, preview, daily Markdown and
  prior email result remain byte-identical; the saved queue has 12 jobs, none active, with only
  one new job in this authorization. All schedules remain paused. No commit or push performed.
- Evidence is retained in ignored `.build/wechat-native-20261020-retry2/`. The previous token
  failures remain historical unknown attempts; no speculative code fix or history rewrite was
  used to mark them successful. Their root cause remains unresolved, but no longer blocks this
  successful native attempt.
- [x] After being asked to inspect the new draft's Chinese text, image placement and cover in the
  WeChat backend, the user confirmed this slice can close. This is user visual acceptance,
  separate from API/native success.
- Cover upload, notifications, DMG and earlier manual/resource gates remain separate. Native
  restart acceptance of this successful WeChat record was completed on 2026-10-21 above.

#### WeChat Token Diagnosis Follow-up (2026-10-20)

- The user confirmed account identity and that the rejected IP was already listed. Do not treat
  the previous 40164 responses as proof that the user omitted the IP or configured another account.
- Read-only inspection found the frozen WeChat client bytecode matches current source and uses
  the expected HTTPS endpoint. IPv4-mapped IPv6 denotes the same reported IPv4 address. Prior error
  request identifiers encode contemporaneous timestamps, not a replayed old local error.
- The Mac has a system HTTP/HTTPS proxy. Credentialless proxy/direct checks both returned fresh
  WeChat missing-AppID errors. Two token-only checks using existing credentials then succeeded:
  system proxy at **07:39:56 UTC**, direct at **07:42:20 UTC**. Credentials and tokens were not
  logged or persisted. No images, drafts, research, email or App queue jobs were created.
- Current token access works, but the specific cause of the earlier 40164 responses is unresolved.
  Neither a proxy defect nor whitelist propagation delay is established. No speculative runtime
  fix was made. Historical App delivery remains unknown; token success is not draft acceptance.
  Diagnostic summary is retained in ignored `.build/wechat-network-20261020/diagnostic.json`.

#### Earlier Native WeChat Attempts: Blocked (2026-10-20)

- [x] Connected the saved cover/author from an earlier confirmed WeChat success to the development
  App; reused existing Keychain names, with metadata-only presence checks before execution.
  All schedules stayed paused and there was no pending work.
- [x] Operated the actual native status item, report button and WeChat confirmation sheet.
  Native Cancel left the queue and report unchanged. Then dispatched exactly one native creation
  confirmation, protected by a local one-confirmation guard in ignored acceptance evidence.
- **Blocked at this attempt:** the one new WeChat delivery job reached the token endpoint, which
  returned error **40164** (IP whitelist rejection). It stopped before
  image upload and draft submission; no draft request/result artifact was produced. The App
  conservatively records `delivery_unknown`; no retry or second confirmation was attempted.
- No new research or email job, no publish/broadcast, and no commit or push. Original draft,
  preview, daily Markdown and prior email result remained byte-identical. Evidence is retained in
  ignored `.build/wechat-native-20261020/`; the network address is not copied into public docs.
- A later single native attempt under fresh authorization succeeded and received user visual
  acceptance; see the checkpoint above. Native restart acceptance was subsequently completed on
  2026-10-21, separately from these earlier blocked attempts.
- A subsequent user-authorized single native attempt on the same date again returned **40164**
  at token acquisition. Cancel was rechecked, exactly one new WeChat job was admitted, and no
  image/draft submission or automatic retry followed. Original report/email artifacts were
  unchanged. Evidence is in ignored `.build/wechat-native-20261020-retry1/`. The user confirmed
  the IP was already listed; the cause of these earlier rejections remains unresolved.

#### App WeChat Entry: Offline Acceptance (2026-10-20)

- [x] Existing reports now expose WeChat status, Settings navigation, and explicit creation
  confirmation using the saved cover and author. Missing configuration or credential metadata
  blocks admission. Opening/rendering a report and dismissing confirmation do not create jobs.
- [x] Reused the serialized delivery queue, `retry_delivery` bridge and WeChat application service.
  The existing first-manual-email channel-record helper now covers both supported channels;
  missing records remain `notRequested`, not automatic pending work. No new pipeline, wire command,
  renderer, publishing client or runtime dependency was added.
- [x] Verified duplicate/unknown confirmations, changed cover or App-managed credential
  invalidation, busy admission, queue-write failure and crash recovery using offline substitutes.
  Email status remains independent. First-record and credential-change tests reproduced the
  missing behavior before their fixes. No real credential values were read or written.
- [x] The Python bridge test uses the real handler and application service with an offline client:
  title/summary come from `ArticleDraft`, cover/author from settings, and only draft creation is
  requested. The existing draft, preview and no-image publish HTML remain byte-identical.
- Sixteen English/light and Chinese/dark component captures are retained in ignored
  `.build/wechat-entry-20261020/`. These are offline layout evidence, not native popover clicking
  or real service acceptance. Real App draft creation and user visual acceptance were subsequently
  completed above. Cover upload, notifications, DMG and prior manual/resource gates remain open.
  No real research, draft, email, commit or push occurred in this offline slice.
- Checks passed: Python **856 passed / 2 skipped**; Swift **245 tests across 45 suites**, including
  ten WeChat entry tests and the explicitly enabled frozen workflow. Release build, bundle and
  deep/strict signing checks, Ruff, privacy and diff checks passed. Independent read-only review
  found no concrete issue. Production Python services and all channel renderers are unchanged.

#### Native Gmail Acceptance (2026-10-20)

- [x] Copied the already verified Gmail SMTP settings into the development App's typed
  configuration, reusing `email.smtp_password` in Keychain. Schedules remained paused with no
  enabled schedule or pending job. No password was copied into JSON or source files.
- [x] Imported the selected report's real prior CLI `email_send_result.json` into its email
  delivery status, with recipient/time validation, so native UI showed Sent / Send again before
  this acceptance. This was a one-time reconciliation of an existing success, not a fabricated job.
- [x] Exercised the actual staged App via native AX: Read report, Send again and the real
  sender/recipient confirmation sheet. During acceptance the App created exactly one new email
  delivery job, `77DFEBB5-3D8E-4E7F-AD05-B17BF0C19EE4`, which succeeded at **13:27 HKT** with six
  inline images to the configured Gmail self-recipient. The final automation guard observed that
  success and did not dispatch another confirmation. No new research job was created.
- [x] Verified native Sent status, restart persistence and Cancel on the real resend sheet;
  cancellation created no additional job. `article_draft.json`, `wechat.html` and `daily.md`
  remained byte-identical. Acceptance artifacts and scoped screenshots are retained in ignored
  `.build/email-native-20261020/`; no commit or push was performed.
- Found and reproduced stale busy UI after a completed send: the final admission counter release
  was ignored by observation. Made that existing counter observable; an actual SwiftUI-hosted
  offline regression failed before the one-line fix and passed afterward. The updated signed
  development App retained Sent state and no stale busy label on reopening. No extra SMTP send.
- [x] The recipient confirmed the native-App message arrived and its Chinese text and images
  render correctly. This acceptance is separate from the preceding CLI message.
- Recovered the original full Swift diagnostics: the reported two issues were two assertions in
  **one** test, `backToBackRequestsForSameReportRenderDespiteCancelledPreparation`. A real system
  memory-pressure event correctly released the reader during a test that expected it to remain
  loaded (`reader.memoryPressure`, then nil WebView). The cause was ambient-event coupling in
  the test, not two email failures or evidence of an email-sending regression.
- Loading/lifecycle tests now inject no external pressure source; the production default still
  observes system warning/critical events on the main queue. The separate explicit-pressure test
  checks release, cleared delegates, removed view and suppression of immediate same-report reload.
  All six reader lifecycle tests passed in five consecutive runs. The recovered original output
  and follow-up logs are retained in ignored `.build/email-native-20261020/`.
- Final checks: Python **855 passed / 2 skipped**; Swift **235 tests across 44 suites passed**,
  with the frozen-pipeline/restart test explicitly enabled and passed (not skipped). The first
  enabled attempt rejected an outdated offline engine's configuration (`ui_appearance`); rebuilding
  that test-only engine from current source resolved the mismatch without a compatibility patch.
  Frozen network-blocked pipeline, production dependency preflight, development App build,
  bundle/signature verification, Ruff, privacy scan and diff checks passed. Independent read-only
  review found no concrete issue. No additional real research or send was performed; the saved
  user queue remained at nine jobs and the three accepted report artifacts remained byte-identical.
- Reader resource and other unrelated manual gates remain open; deterministic tests do not
  replace real system-pressure, VoiceOver, multi-display or final beta acceptance.

#### App Email Entry: Offline Acceptance (2026-10-20)

- [x] Full report reader provides email status, next recipient, Settings navigation and a
  sender/recipient confirmation sheet. Opening a report or dismissing confirmation sends nothing.
  SMTP settings, serialized jobs, the bridge command and publisher are reused; no new wire command,
  SMTP client, research stage or channel renderer was added.
- [x] First manual email sends create only their missing channel record; existing WeChat state and
  report bytes are preserved. Active tasks block manual admission. Report/settings/history changes
  invalidate a previously opened confirmation, and repeated confirmation cannot create a second job.
- [x] Failure, unknown outcome and prior success have distinct retry/confirmation behavior.
  Confirmed unknown outcomes pass both existing acknowledgements required by queue/publisher.
  Crash recovery between queue and initial channel-record writes is idempotent. Neither case
  silently sends another copy. The read-only review findings were reproduced, fixed and retested.
- Offline checks: Python **855 passed / 2 skipped**; Swift reported **234 tests** across 44 suites
  passed, with the pre-existing conditional frozen-workflow test not enabled in this run.
  The 10 new Swift email tests cover first send, failures, uncertainty, stale confirmation,
  duplicate clicks, missing/denied metadata access, queue-write failure and restart recovery.
  The Python bridge test uses the real publisher with a fake SMTP transport to verify unresolved
  attempt protection and explicit resend. No real provider, search, SMTP or credential values used.
- English/light and Chinese/dark component snapshots were rendered and inspected for email
  controls and confirmation states (16 images in ignored `.build/email-entry-20261020/`).
  These are view-layout evidence, not physical-click or native-popover interaction acceptance.
- Ruff, privacy, diff, release build, bundle dependency and deep/strict signature checks passed.
  The refreshed development App passed offline engine preflight in **1.506 seconds**. Signing used
  the existing local identity; no new identity or credential permissions were installed.
- [x] Native confirmation/cancel interaction and one authorized real App SMTP send were verified
  in the follow-up above; the recipient confirmed Chinese text and images in the second message.
  WeChat final actions, cover upload, notifications, DMG and prior reader resource/manual gates
  remain separate. At the offline checkpoint no live send, commit or push was performed.

#### Reader Cycle Acceptance Attempt (2026-09-20)

- Tested commit `6a6cc2c` using current release objects in the existing isolated presentation
  harness. Its native status item opened the production popover and compact view; this is a
  test-entrypoint observation, not production startup or a completed reader workflow.
- **Blocked, 0/20 cycles:** the in-process accessibility tree did not expose the compact
  `Open workspace` button, although it is visible in the captured window. CG event posting
  was unavailable; a separate read-only System Events availability check was denied with
  Apple Events error `-1743`. No permissions were enabled and no control success was inferred.
- Evidence is retained in ignored `.build/task3a-visual/ede3e9eb45284d76a86c083b2d2ce46d/`
  (`acceptance.json`, compact-popover and status-item captures). The test App terminated;
  original and copied offline report artifacts remained byte-identical. No engine, real
  credential, model, search or delivery operation was invoked. Product code is unchanged.
- Reader load, weak-reference release, memory trend and final idle-resource gates were **not
  reached**. Do not reuse previous idle measurements as evidence for this attempt.
- The original user-assisted retry request is superseded for the bounded production-App
  reopen/dismiss resource loop by **Current App: Offline Resource And Lifecycle Check** above.
  The original broader interaction request was: open the report, dismiss with
  Escape/outside click, reopen from the status item and alternate compact/full mode for 20
  cycles. Record retained selection, Chinese text, image/formula/anchor rendering and any
  blank page. Couple the session with resource/reader-lifetime observations; manual clicks
  alone do not establish memory release. VoiceOver, multi-display and file-picker gates remain
  separate. Do not trigger Run Now, connection checks or delivery during this acceptance.

#### Pre-commit Regression Follow-up (2026-09-20)

- Separate public-source family deduplication from the expanded deep-reading retry pool. A
  previously listed high-ranked v1 must not hide a newly reportable v2 from a shallow report.
- Validate PDF crop response paths by their resolved, existing regular file within the allowed
  root. Accept macOS `/var` versus `/private/var` aliases; reject mismatched files, absent output,
  invalid paths and workspace symlinks. No renderer or historic artifact is rewritten.
- Offline acceptance passed: Python 853 passed / 2 skipped; Swift 224 passed with the frozen
  workflow explicitly enabled. The freshly frozen test engine produced a valid report with a
  native PDF crop; the App queue and startup loader preserved report and independent channel
  outcomes across restart. External network access was blocked; no real credentials or sends.
- Ruff, privacy, diff checks, bundle dependency verification and deep/strict signature checks
  passed. The development App was rebuilt using the existing local signing selection. A scoped
  read-only review found no actionable issue in the two fixes. This is not GUI acceptance.
- Native interaction, real service acceptance, and cross-version Keychain authorization remain
  open. These fixes do not expand Task 3A into Task 3B or authorize live service requests.

#### Keychain Signing Follow-up (2026-09-20)

- Initial inspection found ad-hoc, cdhash-based designated requirements. With explicit user
  approval, a local-only code-signing certificate and private key were created in login Keychain;
  trust is limited to the current user's code-signing policy. No real credential values or ACLs
  were accessed or changed. The development App and engine now use that certificate.
- Build tooling accepts a certificate fingerprint via `RESEARCH_RADAR_SIGNING_IDENTITY` or
  gitignored `packaging/macos/signing.local.json`; the CLI override takes precedence.
  Validate before replacing the App, sign inside-out with the same identity, and never silently
  fall back to ad-hoc after an explicit identity fails. No credentials or runtime protocol change.
- Certificate-backed App passed deep/strict signature verification and frozen offline preflight.
  A real two-version test with a disposable Keychain item had identical designated requirements
  but different executable hashes: the original read succeeded, the updated read failed with
  OSStatus -25293 with interaction disabled, and restoring the original succeeded again. The
  item's partition metadata contained the original `cdhash`, matching Apple's client-classification
  implementation. The disposable credential was removed after the test.
- Checks: 19 signer tests and the full Python suite passed (2 skipped); Ruff, privacy, bundle
  dependency and diff checks passed. Swift UI/runtime code did not change in this signing slice.
- [ ] Repeated authorization is **not resolved** by the local self-signed certificate. Evaluate
  Apple-issued signing separately before promising update-stable access; do not silently relax
  ACLs, install more identities, or change credential storage. The three real prompt items remain
  unidentified. This acceptance finding supersedes the earlier self-signing expectation.

#### Deep Eligibility and Result Follow-up (2026-09-20)

- Code contract: listing history is not deep-reading completion. Keep `seen` and
  `is_reportable_source` unchanged; apply relevance separately before deep selection. A seen
  paper remains eligible after listing only, unavailable full text, reading failure or zero
  publishable claims. Suppress only recorded successful deep reading with positive claims for
  the same family/version, preserving success across later outcomes and alias bridges without
  rewriting JSONL or guessing missing legacy evidence.
- History review fix: check `deep_read_succeeded` before status-based eligibility. A delayed v1
  outcome after v2 success may leave v2 labelled `version_update`; that label must not override
  v2's recorded success. Do not transfer v1 or unknown-version success to v2.
- Result contract: process completion is separate from `research_outcome.status` (`ready`,
  `no_new_content`, `incomplete`). Carry structured reasons through artifacts and the App;
  distinguish discovery, full-text, reading and evidence failures. Zero claims alone does not
  prove verifier rejection; missing legacy metadata does not establish a failure stage.
- Empty results do not automatically deliver: App admission requires positive deep-read and
  publishable-claim counts and a `ready` outcome when present, including restored pending jobs.
  Retain local attempt artifacts/diagnostics and the previous useful report. Legacy missing
  outcomes use recorded counts, not inferred success or failure reasons.
- Optional keys resolve once per task-owned GitHub/Semantic Scholar connector, including missing
  and denied values; repeated queries reuse the result, anonymous discovery remains available,
  and access failures emit redacted warnings. New tasks resolve afresh. Required Keychain reads
  remain explicit/retryable; do not globally cache denials or promise prompt-free native access.
- Offline checks (2026-09-20): Python 824 passed / 2 skipped; Swift 224 tests in 43 suites
  passed. Ruff, privacy scan, diff checks, signed bundle verification and frozen-engine preflight
  passed. Read-only review found and resolved a delayed-v1 history regression; the final Swift
  integration review found no actionable issue.
- [x] Verify result propagation, optional-key lifetime, empty-result normal/recovery delivery
  admission, same-day retries, localized explanations and actual concept matching with offline
  tests. No real provider, Keychain value or publisher was used for these checks.
- [x] Generate 24 isolated outcome snapshots (English/Chinese, light/dark, compact/full).
  Inspect representative empty, incomplete-with-retained-report and partial-ready screenshots.
  Evidence: `.build/task3a-visual/3529216578d6440f9fb2475c00c22d81/acceptance.json`.
  This fixture hosts production views, not the production startup or a real research/delivery run.
  The copied existing report artifacts remained byte-identical; the fixture App exited.
- [x] Append only `memory agent` and `memory agents` to the existing development topic's
  agent-context aliases using validated atomic configuration storage; preserve other settings.
- [ ] Manually verify native Keychain permission interactions, new-task re-resolution, localized
  result presentation, previous-report retention and no automatic delivery for empty/incomplete
  attempts. Physical UI and real services remain separate gates; this follow-up authorizes no
  live calls or sends and no Git stage/commit/push. Earlier checkpoint counts below are historical.

#### Codex and Schedule Recovery Follow-up (2026-09-20)

- Code: App/CLI defaults use `gpt-5.6-luna/xhigh`. App offers high/extra-high,
  preserves a valid executable path, and separates program discovery from connection checks.
  App startup atomically migrates only the old built-in Codex Terra/high verifier combination;
  custom routes and the selected DeepSeek verifier are preserved. Existing CLI YAML remains
  explicit configuration; do not silently rewrite users' files or installed launchd snapshots.
- Code: schedule faults block automatic refresh until an explicit recheck validates persisted
  state. Quit remains final. Home and settings share schedule status; saving a plan does not
  unpause all schedules. Catch-up applies only to today after its scheduled time, never yesterday.
- Offline checks: defaults/migration, selection persistence, failed saves, stale probe invalidation,
  redacted diagnostics, explicit recovery, corrupt state preservation, Quit and date boundaries.
- Live evidence: one earlier bundled-engine Luna/xhigh short probe succeeded in about 11 seconds.
  This is not a full-paper verifier test and does not reproduce the previously reported UI failure.
- Pending: real App selection/save/reopen/check acceptance and final visual approval. No additional
  model calls or deliveries are authorized by this follow-up. Keep changes uncommitted.
- Verification: Python 702 passed / 2 skipped; Swift 185 tests. The review's active-but-unarmed
  scheduler recovery finding was reproduced and fixed with a regression test. Native navigation
  automation remains blocked on Accessibility not exposing the compact expand control, so it
  does not establish successful settings clicks or reproduce the earlier Codex UI failure.

#### Historical Task 2 And Early Task 3A Summary

The following records describe the earlier pre-release checkpoint, not the current release status.
At that checkpoint, the macOS 26 Apple Silicon App was in a Draft PR, not a released replacement
for the CLI. The bundled engine, application services, queue, scheduling, and basic onboarding existed.
Task 2 had passed the frozen offline workflow and native App restart checks. A Swift fake-runner test
alone is not treated as proof that the frozen research engine can produce a report.

- Implemented: terminal recovery, unknown delivery protection, serialized engine access,
  atomic settings, editable multiple topics, persistent credential/settings entry points,
  optional cache limits, and an isolated `ResearchRadar-Dev` workspace.
- Offline acceptance: the production protocol, application service, pipeline, and renderer
  produced a loadable `ArticleDraft`, six publishable claims, a safe PDF crop, and a persistent
  report index with fake external inputs. A separate signed test App ran the scheduled workflow
  and reopened without duplicating jobs. No real model or delivery service was called.
- The deliberate fake WeChat failure remains `unknown`; independent fake email succeeds.
  This verifies recovery behavior, not a successful real WeChat or SMTP connection.
- Resource sample: approximately 49 MB App, 0.73-second first window, and 74 MB RSS at the end
  of five minutes with the basic window open. No idle descendants or residual groups after
  20 standalone engine check/cancel cycles. These cycles are not 20 native queue runs; the
  native frozen workflow was checked separately. Restricted `leaks` diagnostics are not a
  leak-free certification.
- Revised Task 3A is the current visual checkpoint. The anchored native-popover contract
  below is implemented as reported by the main agent, including mixed system typography,
  configuration admission, metadata-only Keychain presence, and Codex confirmation.
  Native visual acceptance remains IN PROGRESS. Stop for user visual approval before committing.
- Earlier popover checkpoint: 177 Swift tests and 696 Python tests passed (2 Python tests skipped),
  including Swift schedule-recovery coverage; Ruff, privacy, and diff checks passed. The latest
  staged, signed bundle passed frozen preflight in `0.829 s`. Both read-only-review P2 findings,
  same-report reopening and schedule rearming, were fixed.
- 24 actual anchored-popover captures cover English/Chinese and Light/Dark states. The main
  agent visually reviewed compact, full, and missing-configuration views with no overlap.
  A current compositor screenshot confirms backdrop blur, not merely alpha-isolated output.
- Full AX controls remain unavailable. The reader lost focus and dismissed before the cycle
  run: `0/20` completed, NOT accepted; no full-reader resource result is available.
- Independent final-release dismissed-idle sampling completed: `300.05 s`, 61 samples;
  RSS first/last/min/max `74,629,120 / 50,200,576 / 46,989,312 / 91,504,640` bytes
  (about 50 MB last, 47-92 MB range). Sampled `ps` CPU mean `1.03%`, max `16.8%`, includes
  an early transient and is not energy usage; app termination succeeded. This isolated offline-root
  snapshot does not cover production startup, research, or full-reader resources, and is not a
  zero-CPU or leak-free claim. Twenty reader cycles and full AX remain NOT passed.
- Earlier window-based Task 3A evidence recorded 688 Python tests (2 skipped) and 161 Swift tests.
  Native screenshot and reader-release evidence is available; full keyboard/VoiceOver,
  accessibility-display combinations and the settings navigation/edit-confirmation
  visual path still require manual acceptance. No real provider or delivery was invoked.
- Those earlier results do not establish acceptance of the revised popover or credential flow.
- Task 3B remains separate: cover upload, final delivery actions, notifications, DMG, and
  user-triggered real App research/WeChat/email acceptance. Existing CLI delivery validation
  and offline visual checks do not substitute for real App acceptance.

#### Revised Task 3A: Implemented, Visual Acceptance In Progress

- Implemented follow-up: App appearance (`system` / `light` / `dark`) and four-step first-run
  setup: language/appearance, research services, reviewed topic, check/start. Existing
  configurations default to system appearance; report HTML and research settings are unchanged.
- Connection checks distinguish model routes from a minimal Tavily search probe. They run
  only on explicit request and may use service credits. Saved keys are not connection proof;
  model/search checks do not validate WeChat or SMTP. New users can defer delivery/schedules.
- This follow-up uses offline verification; real first-run service acceptance and the earlier
  manual interaction gates remain open. No commit/push or Task 3B work at this checkpoint.
- Code verification: Python 747 passed / 2 skipped; Swift reported 208 tests across 42 suites
  passed, including one conditional frozen-workflow skip. Ruff, privacy, diff, bundle and
  ad-hoc signature checks passed. The separate frozen local preflight passed in 0.746 seconds;
  it did not make provider/search requests. The development App remains approximately 48 MiB.
- Read-only review found login-item saving could overwrite a concurrent appearance change,
  and non-Tavily configurations were incorrectly treated as failed Tavily checks. Both were
  reproduced and fixed. Disabled/non-Tavily search now shows not checked, not connection success.
- Native fixture snapshots completed a 16-layout Chinese/English and light/dark matrix before
  the final wording correction. Final-build recapture produced the first three Chinese/light
  pages, then lost popover focus; its matrix is NOT passed. Those pages were visually inspected,
  original report bytes remained unchanged, and test-App termination was confirmed. Final-build
  full visual coverage, real keyboard/VoiceOver and prior interaction gates remain pending.

- [x] Implement one native `NSPopover` anchored to the status item: compact `400 x 480 pt`,
  expanded `900 x 660 pt`, clamped to the current screen's available frame.
- Draft retention across outside click, Escape and compact/expanded changes is covered by the
  later **Unsaved Draft Retention** checkpoint. Background-job and broader accessibility claims
  remain limited to their separately recorded checks; dismissal is not cancellation or Quit.
- Sidebar and bounded Chinese/English keyboard acceptance are covered by the later **Keyboard
  Navigation** checkpoint, not an outstanding duplicate of this original visual checklist.
- [x] Confirm backdrop blur in current compositor output and review compact/full/missing-config
  layouts without overlap, as reported by the main agent. Native glass/materials must retain
  the no-opacity/custom-blur-hacks contract; Tuneful, Dato, and OpenUsage remain references,
  not runtime dependencies.
- [x] Use public system font APIs: proportional UI `13-14 pt`, headers `17-20 pt`, auxiliary
  labels at least `12 pt`, and system monospaced text for technical information only.
  No external fonts. English/Chinese and Light/Dark captures are available; full manual
  visual acceptance and accessibility-display checks remain pending.
- Native file-picker and bounded keyboard checks have later acceptance records. VoiceOver,
  multi-display and remaining accessibility-display checks are now explicitly deferred above.
- [x] Implement configuration admission and credential presence through metadata-only,
  noninteractive checks. Appearance,
  reopening, and settings navigation must not read secret values or prompt for Keychain
  access. Unavailable metadata is unknown/unavailable, not confirmed missing.
- [x] Clarify existing English/Chinese credential help: saved is not authorized or verified;
  Allow covers the current access, while Always Allow remembers the requester/item permission.
  Approve only a trusted ResearchRadar requester and the correct item. Different keys/jobs
  and ad-hoc rebuilds may prompt again; no broad ACL changes or prompt-free promise.
  Inline help is limited to three short sentences; repeat-prompt details remain in docs.
  Test Connections checks only the listed model routes, not SMTP or delivery.
- [ ] Manually verify native permission prompts and the revised help layout in both languages.
  Localized copy does not establish runtime authorization or close visual acceptance.
- [x] Declare UTF-8 in the App reader's HTML response without rewriting report files.
  A real WKWebView regression reproduces the former GB18030 decoding and verifies
  mixed Chinese/English text, local images, formulas, anchors, and unchanged HTML bytes.
- [x] Verify job-local credential caching through the production bridge and daily pipeline
  with offline external IO: successful reads are shared across model stages, new jobs
  read fresh values, and denied reads produce a redacted failure artifact and remain retryable.
  This does not verify native Keychain dialogs; isolated staged-engine authorization
  acceptance still requires user interaction and must not use real API credentials.
- Keep explicit live model/search checks separate from delivery checks, with scoped
  results. Appearance starts neither; development acceptance authorizes no live call or send.
- [x] Show autodetected Codex candidates for confirmation and provide an explicit
  run-configuration check. Do not launch Codex on appearance, silently switch verifier
  routes, or treat path detection as proof of working authentication/configuration.
- [ ] Complete native AX action inspection, visual checks, and revised cycle/resource evidence,
  then obtain user visual acceptance. Passing tests and frozen preflight do not close this gate.
- [x] Separate the latest failed research attempt from the last successful report and its
  counts. Show a confirmed research retry and scoped diagnostics; a channel failure does not
  invalidate research. Legacy terminal codes do not imply an observed failure stage.
- [x] Verify bounded transport recovery through the production bridge/daily path with offline
  external IO: one automatic retry, accurate source-gist terminal stage, one credential read,
  and cancellation without a second request. No real provider or publisher was used.
- [ ] Obtain user acceptance of the revised retry/diagnostics controls. Isolated native
  snapshots do not prove physical clicks, VoiceOver, multi-display or real service recovery.
  Final English/light failure captures were inspected; final Chinese/dark capture automation
  remains blocked by popover focus/anchor checks. Code gates: Python 724 passed / 2 skipped,
  Swift 195 passed; bundle, signature, Ruff, privacy and diff checks passed.

### Research And CLI Follow-up

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
