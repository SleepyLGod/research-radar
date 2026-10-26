# Native Home And Reader Visual Alignment

Historical slice record: its original no-commit stop point is retained below. The subsequent
[authorized closeout](2026-10-26-native-reading-polish.md#authorized-closeout) governs source
commits and Draft review; it does not imply a released package or completed physical acceptance.

## Goal And Boundaries

Bring the existing native home and reading area closer to the approved local prototype without
replacing the App. Preserve the earlier uncommitted overview slice. Only App presentation changes:
no research, evidence, protocol, renderer, configuration-schema or delivery-policy changes.

## Implementation

- Keep the anchored 400-by-480 compact and 900-by-660 expanded popover, including existing
  screen clamping. Sidebar and toolbar retain native materials; only home/list/reader detail
  surfaces receive the adaptive system text background.
- Use system proportional text: research focus 18/22 pt in compact/full, descriptions 13/14 pt,
  auxiliary text at least 12 pt. Counts remain monospaced at 18/20 pt. Keep report-versus-attempt
  placement, topic scoping, known counts and current-stage semantics unchanged.
- Replace the two permanent delivery panels above the reader with one native Delivery disclosure.
  Its summary always shows WeChat and email states from the existing channel presentations.
- Store only an ephemeral fold preference. Quiet reports start collapsed; pending, sending, failed
  and unknown outcomes start expanded. A channel's newly observed attention state reopens it once.
  A repeated render, or another channel merely completing, does not override manual collapse.
- Switching report resets that preference. Existing channel views and their confirmation sheets
  remain responsible for preparing, confirming and cancelling actions; no send logic is copied.
- Do not rewrite HTML, inject CSS/JavaScript, force report inversion or change the restricted
  reader lifecycle. Paper cards, graphs and automatic briefs remain separate future slices.

## Verification

- RED-to-GREEN tests cover fold defaults, both channel states, one-time attention expansion,
  manual overrides, report switching and unrelated-run isolation.
- Run existing email/WeChat confirmation and queue regressions, reader lifetime, report selection
  and language/appearance tests. Add native offline checks for disclosure controls and cancelling
  confirmation without sending.
- Compare current native captures against the approved prototype in both languages, light/dark,
  compact/full and long-title/empty states. Use existing report bytes and verify no artifact changes.
- Run Python and Swift regression, Ruff, privacy, localization/diff checks, bundle verification,
  signature verification and a private read-only review. Do not mistake fixture screenshots for
  live research or system-input acceptance.

## Delivery And Stop

Produce a separate signed candidate and comparison captures; keep the old App and real data
unchanged. Report verified results and remaining input limitations accurately. No real service,
credential-value, upload or delivery access. No staging, commit, push or Release changes.
Pause after this slice rather than starting cards or evidence views.

## Initial Implementation And Acceptance Record (2026-10-25)

- Implemented presentation-only delivery folding, independent channel summaries, adaptive detail
  backgrounds and home typography. Existing channel views and their confirmations are reused.
- Seven new test functions cover fold state and report isolation. Full Swift regression passed
  with 297 tests in 51 suites; Python regression passed with two skips. Ruff, privacy,
  localization syntax, bundle, nested signature and diff checks passed. A fresh local read-only
  review found no actionable issue in this slice; this is not an external service review.
- A separate approximately 49 MB candidate uses the existing signing identity. The normal App
  and the earlier candidate were retained. No production engine or real credentials were used
  by the isolated UI host. All 31 original report artifacts and their isolated copies retained
  their hashes, including the Chinese report and draft.
- Own-process native view snapshots cover eight bilingual light/dark compact/full home layouts,
  four reader layouts and representative empty/failure/unknown fixtures. They help inspect text
  and reading space, but can omit composited surfaces: they are not system-window screenshots
  or proof of the Liquid Glass appearance. The existing Chinese HTML remains unchanged and is
  not forced into dark mode.
- **Native interaction acceptance remains incomplete.** System window and region capture both
  failed. The isolated popover was not reliably active/key for input, so disclosure clicks,
  confirmation cancellation, Escape and cross-mode restore were not accepted as passed in this
  run. Automated state/confirmation/reader regression is not a substitute for these operations.
  Do not change recording permissions or relax the popover just to satisfy the test harness.
- No model/search/credential-value/upload/send operation, staging, commit, push or Release update
  was performed. Stop here for visual/input acceptance before starting paper cards or evidence.

## Reader Follow-up (2026-10-26)

- The reported return/scroll problem was reproduced in the native popover. When delivery
  expanded, split-view minimum-size measurement could wrap its text at a near-zero width,
  inflating the entire column beyond the window. The return controls left the viewport and
  the reader no longer had a correctly bounded scrolling area. State-only tests missed this.
- The production correction is limited to a 320-point minimum content width on the Delivery
  disclosure (352 points including its existing horizontal padding). It prevents that pathological
  measurement; it does not enlarge the window, change report HTML or replace navigation/WebKit.
  Ineffective experimental reader/hosting changes were removed.
- New regression covers the actual direct and retained workspaces in English and Chinese,
  expanded delivery, the existing 696-by-508 small-screen content size, WebKit scrolling in both
  directions and unchanged HTML. An animated disclosure case also checks the reader cannot
  overlap return controls. Full Swift regression passed with 299 tests in 52 suites; the final
  focused rerun includes the small-screen addition.
- In an isolated popover using production views, local native clicks expanded delivery and
  reduced the reader from 513 to 380 points while keeping the split bounded. Scroll position
  moved 0 to 400 and back to 0. Return released the reader; reopening retained the same report.
- Both channel confirmation dialogs opened and were cancelled without adding jobs. Escape,
  popover reopening and compact/full switching retained the report and fold state and released
  the reader when hidden. A test-owned outside window closed the popover through local input.
  The test runner rejects all engine execution and the fake credential store performed zero
  value reads. No actual provider, search, upload or delivery was used.
- System-window capture succeeded in this follow-up: four real popover captures cover English,
  Chinese and light/dark appearance, rather than only own-view snapshots. Original HTML remains
  white in dark mode by design. Physical mouse/trackpad routing across other applications remains
  a separate manual check; these local-event results do not assert it passed.
- A new separately signed candidate retains the old App/candidates and existing engine. No
  configuration, published package or Release was changed. No staging, commit or push.

## Home Hierarchy Follow-up (2026-10-26)

- Only home/compact presentation changes: the report title is secondary 13/14-point text,
  limited to two lines with the complete title in its tooltip. Research-focus text and report
  content remain unchanged. Compact spacing is reduced and its duplicate focus caption removed.
- A larger native glass-prominent reader button is the main action. Quiet reports no longer
  repeat the completed attempt headline and four unreported phases. New, active, stopped,
  incomplete and configuration-attention states retain the attempt section; an occupied engine
  also keeps its controls visible. Channel attention remains attached to the retained report.
- Existing action builders are reused beside the reader action. When today's effective report
  already exists, the redundant Run Now entry is omitted, while the existing More / confirmed
  Run Again flow is retained. Without today's effective report, Run Now remains available.
  No application-service, queue, duplicate-run or confirmation semantics changed.
- RED-to-GREEN regression covers both modes, channel attention, missing credentials, six task
  states and empty outcomes. Full Swift regression passed: 301 tests in 52 suites.
- Fresh real-popover captures include matched before/after states, both languages and appearances,
  compact/full, running, failed, empty, missing credentials and channel-unknown fixtures. Content
  dimensions remain 900-by-660 and 400-by-480; no window enlargement was used.
- Native local mouse events opened the selected existing report from both new reader buttons,
  returned to its list and released WebKit. Jobs were unchanged and credential-value reads zero.
  Physical cross-application pointer input and VoiceOver remain separate manual acceptance.
- This slice does not implement question briefs, paper cards or evidence comparisons and does
  not alter long-form report HTML. It improves hierarchy, not complete prototype feature parity.
  Old Apps/configuration are retained; no real service, sending, staging, commit or push.
