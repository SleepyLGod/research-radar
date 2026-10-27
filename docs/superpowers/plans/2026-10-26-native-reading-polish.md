# Native Reading And Visual Closeout

## Approved Goal

Improve native reading/navigation, evidence layout, report headings, paper previews and the placement of report-level delivery. Preserve all existing uncommitted work, the native popover, system typography and materials. No research/model/evidence/renderer/protocol change, new dependency, live service, upload/send, stage/commit/push or Release update.

## Implementation

- Use existing public `ReportContents` fields for preview selection and available chapter anchors. Chapter selection executes `ScrollViewReader.scrollTo` directly, so choosing the same chapter again remains an action, not an unchanged selection value.
- Keep a native paper picker and chapter menu above one reading scroll view; do not add a permanent third column. Hide report delivery on both paper and full-HTML reading pages.
- Hold delivery disclosure state at the report browser level and pass a binding to the existing delivery view. Reconcile snapshots even while reading without redirecting the reader.
- Centralize the friendly report-heading fallback. Keep immutable report titles available in report metadata and existing sending confirmations.
- Keep paragraphs and quotes verbatim. Use a small read-only preview presentation and section identifiers; do not infer classifications, recommendations or paragraph-to-claim mappings.
- Keep file loading and thumbnail generation in existing services. Split paper detail, evidence and reading controls into concrete views rather than enlarging the workspace root.

## Checks And Ledger

- [x] Add and observe failing tests for headings, preview fallbacks, chapters, page visibility and delivery-fold retention.
- [x] Implement the approved App-only presentation/navigation changes and bilingual labels.
- [x] Run focused and full offline regression, then one fresh-context read-only review.
- [x] Build a distinct candidate with the existing signing identity; preserve the old App and true configuration.
- [x] Capture before/after native states and exercise menus, repeated chapter jumps, paper switching, evidence, return, compact/hide restoration and confirmation cancellation where local input permits.
- [x] Record artifact hashes, bundle/signature/privacy/diff checks and remaining physical-input limits; stop without committing.

Ruling: keep one scrolling paper page with a native chapter menu rather than new tabs or a third sidebar. This fits the established popover dimensions and retains all existing content; a materially different reading workspace is not part of this slice.

## Verified Implementation

- New read-only heading/preview/chapter presentation reuses public data. Headings fall back to the immutable report title when the selected topic is missing, unrelated or blank. Sending confirmations still use that original title.
- Native controls issue a chapter jump directly on every menu action. Paper selection is scoped to the report and retains the existing scroll-to-top behavior when changing papers. No new durable state or wire types were introduced.
- Evidence is a concrete view with leading-aligned content, a small quote inset, primary-color verbatim text and separately tinted safe source links. Figures retain the existing safe loader and lifecycle.
- Delivery disclosure state moved to the report browser and is reconciled there, including while the overview child is unmounted. Research and delivery state are not rewritten by navigation.
- Focused regression passed. Full Python regression and all 317 Swift tests in 57 suites passed; Ruff, privacy and diff checks passed. The fresh-context review reported no actionable production finding, while explicitly reserving native input and narrow-layout acceptance for UI checks.
- A distinct signed candidate passed bundle verification and deep/strict signature verification. Both the previous candidate and normal development App binaries stayed unchanged. The engine was copied unchanged; no new Python environment or dependency was installed.
- Controlled native menu actions verified repeated jumps (offset 704 → manual scroll 1104 → repeated jump 704), a jump to claims, and changing to the second paper with offset reset to zero. Escape and compact/full restoration preserved the paper, and the manual delivery fold survived navigation. Original and copied report trees each retained all 31 original file hashes. These checks do not claim physical keyboard, VoiceOver or live-service acceptance.
- Fresh owned-system-window captures cover preview cards, paper reading, expanded evidence and return in English and Chinese, light and dark. A local arrow-key/Return sequence changed the real native paper picker to the second paper. Capture/focus restrictions initially blocked the extended matrix; rerunning the isolated host with the required local UI access completed all four language/appearance combinations. This is bounded native UI acceptance, not physical keyboard or accessibility certification.
- Existing WeChat and email confirmations were opened and cancelled with Escape, without enqueuing delivery. Full HTML opened with no delivery block and returned to overview; its reader was released. Final comparison retained all 31 original and 31 isolated file hashes, with zero credential-value reads and no new jobs.

## Handoff And Limits

- The candidate is a separate local build, not a Release or a replacement for the normal development App. Existing signing selection was reused, and the package contains no new runtime or engine behavior.
- No live research, search, provider check, upload or delivery was performed. Current public previews and original evidence were reused, not regenerated.
- Physical cross-application mouse/keyboard routing, VoiceOver, multiple displays, actual missing-image behavior across repeated hide/remount cycles and a new resource-soak measurement remain outside this bounded acceptance. Existing safe-image and reader lifecycle regression passed; no new comprehensive resource claim is made.
- Stop for the user's visual review. Do not stage, commit, push or update the published beta from this task.

## Follow-up: Consistent Content Panes And Reading Typography

Approved after visual review: keep system proportional fonts for interface and prose, system
monospaced text for technical labels, and monospaced digits for statistics. Do not add 0xProto,
Nerd Font assets, a font selector or a new dependency. Unify detail-pane background, remove the
extra outer frame around grouped settings/diagnostics, align topic/report toolbars, and improve
paper typography and section rhythm. Keep system materials on navigation; do not paint the
whole popover opaque. Clarify Full report as Full daily report. Existing report content, research,
delivery, native navigation and previous uncommitted work remain unchanged.

- [x] Reproduce grouped-form inset with a hosted layout regression.
- [x] Apply the scoped pane/typography changes and verify narrow reading layout.
- [x] Run offline checks, fresh read-only review, and bilingual native visual acceptance within the recorded local-input limits.
- [x] Deliver a separate candidate with existing signing; keep old Apps/configuration and pause.

Ruling: native grouped forms keep their own row groups and content insets, while their scroll
surface fills the detail pane. Do not introduce a generic styling framework for these few views.

### Implementation And Regression

- The hosted settings/diagnostics regression failed on all four edges with a 20-point inset in both
  languages, then passed after removing the extra outer padding. Native grouped rows retain their
  own insets; only the shared detail pane receives a stable adaptive reading background. Sidebar,
  popover and toolbar materials are not covered by that fill. Topic/report toolbars share 20-point
  horizontal and 14-point vertical padding; the topics toolbar now has the same divider boundary.
- Paper title/body/section sizes are 22/15/16 points. Body line spacing is 6 points; source quotes
  use a separate 14-point proportional style, while locations and technical labels remain system
  monospaced. Card question text uses 14-point primary text rather than treating it as metadata.
  No font file, custom blur, dependency, new persistent field or content transformation was added.
- A new hosted regression uses long bilingual titles/prose at 540- and 700-point pane widths.
  It checks wrapping, bidirectional native scrolling, reserved navigation space, no preloaded
  WebKit and unchanged draft bytes. Chapter anchors, selection and evidence safety remain covered
  by the existing tests. The English full-report label now explicitly says Full daily report.
- Full Python regression passed. Full Swift regression passed with 319 tests in 58 suites; a final
  card text style adjustment was then compiled and rechecked with the nine focused tests in five
  suites. Ruff, privacy and diff checks passed. One fresh-context source-only review found no
  actionable issue; it did not substitute for native visual acceptance.
  Two existing opt-in frozen-engine workflow/upload tests were skipped by their default guards;
  this presentation-only run does not claim a new frozen research/upload acceptance.
- The candidate reuses the unchanged frozen engine and existing signing selection. Bundle and
  deep/strict signature verification passed; the previous candidate and normal App binaries stayed
  unchanged. Its measured on-disk package size is approximately 49.5 MiB, about 20 KiB above the
  previous candidate. This is not a fresh CPU/RSS or long-running memory-soak measurement.

### Native Acceptance And Remaining Limits

- Owned-system-window captures compare unchanged report inputs before and after on English/dark
  and Chinese/light screens: home, topics, history, settings, diagnostics, previews and paper reading.
  Additional captures show expanded original evidence. Grouped forms no longer appear as a second
  inset rectangular surface; the sidebar and toolbar retain their native materials.
- Local native input verified scrolling, paper return, Escape/reopen, compact/full restoration of
  the selected paper, and opening/returning from full HTML with reader release. No new jobs or
  credential-value reads occurred. Both original and isolated report trees retain all 31 hashes.
- The extended repeated-menu script again met intermittent menu-tracking/focus limits. Individual
  chapter selection and expanded evidence were captured, but this follow-up does not claim a new
  fully completed repeated-menu loop. The earlier closeout's accepted results remain historical,
  not a substitute for this run. Physical input, VoiceOver, multiple displays and onboarding/sheet
  appearance are still separate manual checks. No speculative product fix was made for a test-host
  focus or menu-observation failure.
- The isolated host's in-memory settings fixture needed a real temporary support directory before
  its storage panel could be shown without an unrelated fixture warning. The fixture was corrected
  outside product code and the before/after captures were regenerated; real configuration was not
  read or repaired. No upload/send confirmation was accepted and no live service was called.

## Authorized Closeout

The user subsequently approved all proposed closeout steps: finish the bounded native reading
and new-topic-sheet checks, review the accumulated changes, make up to three signed-off commits,
and prepare a pull request. Earlier no-commit stop points above describe those historical slices;
this section is the current authorization. No merge, Release update, live research, API credential
read, upload or delivery is authorized. Existing user data and prior Apps remain untouched.

- [ ] Verify repeated section selection, paper switching/scroll/return, hide and compact/full
  restoration, and opening/cancelling the new-topic sheet with isolated local data. Record native
  automation and actual physical input separately; do not convert a blocked interaction to a pass.
  **Remaining physical click confirmation deferred by the user.** The bounded native observations
  below remain valid, but this checkbox is not complete and does not block a Draft review only.
- [x] Review all accumulated App presentation, public-draft/image loaders, tests and documents.
  Keep real service, pipeline, evidence and channel-renderer behavior unchanged.
- [x] Run fresh checks, record skipped optional tests and resolve valid findings with focused tests.
- Delivery split: native public-report browsing, research/workspace presentation, and the bounded
  acceptance documents. Use explicit file staging and signed-off commits only.
- Publication boundary: push the feature branch and create a Draft PR for review; do not merge or
  publish packages. The PR and commit history record actual publication rather than marking manual
  acceptance complete here.

### Closeout Evidence In Progress

- The local starting tree and updated remote main tree were identical after the documentation PR's
  rebase merge. A new feature branch starts from that remote main without rewriting history or
  dropping any working files. The former feature branch is retained.
- A fresh read-only review covered all 34 accumulated files and found no verified production defect.
  Its commit-dependency correction is applied: the retained-workspace preview test belongs with the
  new reader, while the grouped-form layout test belongs with the form changes. A restricted cached
  test attempt by the reviewer was not used as evidence; the current-source suite was run separately.
- Fresh Python regression, Ruff and privacy checks passed. Current-source Swift regression reports
  319 tests in 58 suites with two existing opt-in frozen-engine tests skipped. Those skips are not
  frozen workflow/upload acceptance. The first staged slice passed the cached whitespace check
  after removing one extra EOF blank line from a new test; no behavior was changed.
- Chinese/light and English/dark new-topic sheets were opened and cancelled through real native
  controls, keeping two fixture topics and one historical fixture job unchanged. Credential-value
  reads stayed zero. Repeated section jumps reached their assertions, but menu/paper-selection
  automation remained unreliable; final physical click confirmation was requested from the user.
- Old Apps, actual configuration and published packages remain untouched. No live service, upload
  or delivery was used. No commit or push has yet been made at this checkpoint.
- The user subsequently deferred the final physical click confirmation. Keep it explicitly pending
  while completing the already-authorized reviewed commits and Draft PR. No product workaround,
  new feature or additional native input experiment is added for that deferral. The isolated test
  App is closed; its fixture files remain available for a later authorized acceptance.
- The final pre-commit run again passed Python regression and all enabled Swift regression checks
  (framework summary: 319 tests in 58 suites, two existing opt-in frozen-engine skips), plus Ruff,
  privacy, deep/strict candidate signing and staged whitespace checks. No new production defect
  was reproduced and no product workaround was added for native automation limits.
- Source changes are split into signed-off commits `8bb2fa2` (public report browsing and its retained
  workspace test) and `dfc920d` (research progress and grouped workspace surfaces). The final
  documentation commit records this evidence and the manual deferral. Push/PR outcome is recorded
  by the feature branch and Draft PR itself; no merge or Release is authorized.

## Follow-up: Public Content And Available Figure Chapters (2026-10-27)

Approved scope: fix only the two presentation findings from the final PR review, add offline
regression and record the actual verification. Keep this follow-up uncommitted and unpushed.
Do not change research, evidence policy, report files, engine protocol or channel renderers;
do not call live services, read real credentials, send, rebuild an App/DMG or update a Release.

### Implementation

- The public draft projection now preserves legacy motivation, assumptions, mechanism, prior-work
  notes, inferred weaknesses, future work, assessment details and the plain-language example.
  Existing narrative keeps its main-section priority. Optional supplemental details have distinct
  bilingual headings; empty values produce no chapters and exact duplicate prose is shown once.
  Only saved public fields are projected, never raw readings or audit metadata. Original claim
  text and evidence remain unchanged.
- Native figures retain their existing public explanation and expose a distinct original caption
  under a disclosure when a translated caption is shown. No new explanation or claim is generated.
- One ephemeral visible-paper model calls the existing bounded, descriptor-rooted raster loader.
  The body and chapter menu use the same successfully decoded images, not figure metadata alone.
  Missing, malformed, unsafe or excluded images cannot leave a heading, chapter action, caption
  or explanation. A mixture of valid and invalid images keeps only the valid image blocks.
- Hide, compact mode, leaving a paper and changing papers cancel the view-owned load and release
  its thumbnails. A generation check rejects stale completions; an already-cancelled load cannot
  clear a newer selection. There is no report-wide image preload, permanent image cache, polling
  or new dependency. A synchronous image decode already in flight remains bounded and completes
  before cancellation can discard it; this is not a new peak-memory or resource-soak acceptance.

### Verification And Limits

- Regression first reproduced omitted public prose, missing figure explanation and a metadata-only
  figure chapter. The focused checks passed after the fix, including all-invalid and mixed image
  sets, unsafe/symlink paths, hide/switch release, pre-cancellation and recovery after cancellation.
- A narrow regression also reproduced a cancelled stale hide clearing current thumbnails; the
  early cancellation guard fixes it. Existing report and delivery state are not part of this model.
- Hosted native view checks observe figure explanations only when a local image loads. Their
  temporary draft and HTML bytes remain unchanged. These checks use generated offline data and
  fake credential metadata; they are not physical menu input, VoiceOver or live research evidence.
- Final full Python regression passed. Final Swift regression passed with 327 tests in 59 suites;
  the two existing opt-in frozen-engine workflow/upload tests remain skipped, not newly accepted.
  Ruff, both localization catalogs, privacy scan and whitespace checks passed. Scoped source
  review found no additional actionable issue; no external review service was used for this slice.
- The user's deferred physical reading-click confirmation remains pending. No candidate App,
  DMG, real report, configuration or published package is replaced by this source-only follow-up.

### Independent Candidate And Bounded Native Check

The user subsequently authorized building a separate candidate with the existing signing identity
and checking these two fixes against isolated reports. This supersedes the source-only packaging
stop above for this local candidate only; commit, push, merge and Release updates remain forbidden.

- The current release-mode native product builds successfully. The existing frozen engine is reused;
  no new environment or dependency is installed. Bundle verification and deep/strict signing pass,
  with the same designated requirement as the retained candidate. Complete retained-candidate and
  normal-App file-tree checks show no changes. The new package is about 49.6 MiB on this machine;
  this is not a new runtime resource measurement.
- The isolated host compiles the current production views directly from source, uses fake secrets
  and a rejecting runner, and contains no research engine. A conservative object timestamp check
  rejected cached inputs, so those inputs were not used for its acceptance. No product build rule
  or production view was changed to accommodate the test.
- Chinese/light and English/dark owned-window captures were inspected. Existing mechanism prose,
  plain-language examples and a valid raster's public explanation are visible. The original-caption
  disclosure entry is present; its physical expansion is not newly accepted. A second paper with
  only missing or malformed rasters has no figure heading and no figure action in the real native
  chapter menu. Native menu selection, returning to previews and opening the second paper used
  controlled local input, not user hardware input. AX labels were unavailable in this host; capture
  inspection and observed native menu actions are recorded rather than claiming AX traversal passed.
- Generated report fixtures stayed byte-identical, secret-value read count stayed zero and the
  one historical fixture job was unchanged. The host started no engine or channel operation and
  was closed after the check. Existing optional frozen-engine checks remain skipped; four focused
  image-visibility tests also passed with the App-bundle build definition.
- The separate production candidate was launched with an isolated data root, paused topic/schedules,
  notifications disabled and both delivery channels disabled. Process startup, an empty queue,
  no child processes, unchanged isolated config/reports and normal process exit were verified.
  Automated checks did not observe its popover, including with a popover-aware observer. This is
  explicitly **not accepted as visible packaged-reader startup**. Actual status-item interaction
  and the user's earlier deferred physical reading confirmation remain pending. There is no
  production workaround, permission change or claim that a running PID proves working navigation.
- The candidate and safe isolated launcher are retained locally. No normal App, real configuration,
  report, installed task, DMG or published package was replaced, and no live service was called.

### Authorized Source Closeout (2026-10-27)

The user subsequently authorized the pre-commit scope/privacy/status review, signed-off commits
and push to the existing Draft PR. Earlier uncommitted/unpushed stop points above remain historical
records, not current publication instructions. No new functionality, live research, external review
service submission, upload/send, merge, package publication or Release change is authorized.

- Keep the App-only fixes and their regression tests together so each source commit builds.
- Commit the bounded acceptance notes separately, retaining the deferred physical input and
  unaccepted candidate-popover visibility. Process startup is not visual or reading acceptance.
- Include only the 13 reviewed code, localization, test and document files. Exclude App/DMG bundles,
  screenshots, local launchers, configuration, credentials, certificates and raw runtime artifacts.
- Run fresh offline Python/Swift regression, Ruff, localization, privacy and whitespace checks.
  Existing optional frozen-engine skips remain skips, not passed checks or live-service evidence.
- Push only the feature branch to the existing Draft PR. Do not merge, update main or publish;
  remote check results belong to the actual PR rather than being inferred from local tests.

The 13-file local review found no further actionable issue or unintended configuration/runtime
artifact in the change set. Fresh full Python/Swift regression, Ruff, localization, privacy and
diff checks passed; the Swift summary remains 327 tests in 59 suites with two existing optional
frozen-engine skips. The source/test slice is signed-off commit `7419e92`; this separate document
commit retains the acceptance limits. Push status is recorded by the feature branch and PR history,
not by converting any pending manual check into a pass.
