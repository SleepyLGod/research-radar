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
- DeepSeek `deepseek-flash` with explicit thinking and `high` reasoning effort as the default reader route.
- Codex `gpt-5.6-luna` with `xhigh` reasoning effort as the default verifier route; other
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

### macOS App Checkpoint

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

The macOS 26 Apple Silicon App remains in a Draft PR, not a released replacement for the CLI.
The bundled engine, application services, queue, scheduling, and basic onboarding exist. Task 2
has passed the frozen offline workflow and native App restart checks. A Swift fake-runner test
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
- [ ] Verify outside click and Escape dismiss without losing form drafts, navigation, topic/report
  selection, or background jobs. Reopening and compact/expanded changes retain that state;
  dismissal is not discard, cancellation, or Quit.
- [ ] Verify the sidebar toggle stays fixed leading and expand/collapse trailing, including when the
  sidebar is hidden. Verify the actual native action labels and clicks in the staged App.
- [x] Confirm backdrop blur in current compositor output and review compact/full/missing-config
  layouts without overlap, as reported by the main agent. Native glass/materials must retain
  the no-opacity/custom-blur-hacks contract; Tuneful, Dato, and OpenUsage remain references,
  not runtime dependencies.
- [x] Use public system font APIs: proportional UI `13-14 pt`, headers `17-20 pt`, auxiliary
  labels at least `12 pt`, and system monospaced text for technical information only.
  No external fonts. English/Chinese and Light/Dark captures are available; full manual
  visual acceptance and accessibility-display checks remain pending.
- [ ] Complete manual physical clicks, keyboard/VoiceOver, multi-display movement, file-picker,
  and supported accessibility-display checks in the production staged app.
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
- [ ] Keep explicit live model/search checks separate from delivery checks, with scoped
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
