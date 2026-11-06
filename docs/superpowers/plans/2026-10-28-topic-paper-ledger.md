# Topic Paper Ledger

## Scope And Decisions

Implement the accepted demo's cross-report paper ledger, not relation inference. Existing
reports remain the durable source of truth; the ledger is a deterministic, rebuildable
projection. Reuse source-family/version normalization in Python. Do not duplicate identity
heuristics in Swift, change report artifacts, alter research/evidence/delivery, or read credentials.

- Shared Python: read registered report references inside the configured workspace; normalize
  paper identity and explicit versions; emit source-backed occurrences and reading locators.
- Bridge/Core: add one typed, offline `read_paper_ledger` command. Preserve existing envelope
  compatibility. Ledger reads do not construct a secret manager or run providers/publishers.
- App workflow: use the existing serial engine gate. Cache topic snapshots in memory, refresh
  only on request/report changes while visible, retain results when a task stops, and rebuild
  after restart from saved reports. No idle watcher or second durable copy of paper prose.
- Native UI: topic-scoped search/filter, paper selection, versions and dated report occurrences;
  navigate to the original report or its existing public paper/evidence view and back.

Ruling: this first slice derives the index on demand and caches it for the current report set,
rather than adding an independently authoritative database or durable cache. Original reports
preserve all history; later incremental caching can keep this contract. This costs local report
reads after restart, but avoids stale duplicate state and background maintenance.

Identity is based on existing arXiv/DOI/canonical URL rules, never title similarity. Generic URL
identity also preserves query parameters (for example OpenReview's `id`) to avoid merging
distinct papers. References are included; older untyped seen entries reuse explicit paper
identity from other saved reports, not guessed classifications. Opaque stable
paper IDs exclude the version; occurrence IDs include report, paper and explicit/unknown version.
Mirrors repeated within that report/family/version form one occurrence, preferring the public
reading's source URL and index; the original report retains its full source listings. Generic
query strings retain their original order and encoding until provider-specific equivalence is
established. They are not decoded or sorted as form fields.
Missing versions remain unknown. Runtime progress URL hashes and report-local integer paper
indices are not global identities. Public reading pointers stay tied to their report/version;
v1's reading cannot label v2 as read. Dates mean inclusion in saved reports, not publication dates
or first discovery on the web. Future graph nodes can reuse paper IDs and occurrence provenance;
no inferred edge, classification or cross-paper claim is introduced.

## Implementation And Verification

1. Write failing shared-service tests using two offline dated reports: merge arXiv mirrors,
   retain v1/v2 and source-only/public-read occurrences, deterministic IDs/order and topic isolation.
   Cover duplicate inputs, unsafe paths/symlinks, incomplete legacy data and unreadable reports.
2. Implement the shared projection and strict bridge request/result, with Python/Swift canonical
   fixtures. Prove the command never resolves credentials or invokes research/delivery handlers.
3. Add typed native ledger/filter/selection state and the offline command client; test stale
   loads, busy state, restart reconstruction and preservation of earlier topic data.
4. Add the native ledger entry and report/paper/evidence return navigation. Reuse the reader,
   safe links, chapter IDs and selected-report state; keep UI copy concise and bilingual.
5. Run two-report offline integration, navigation/reader and existing artifact byte checks;
   inspect rendered bilingual layouts. Run Python/Swift, Ruff, privacy and diff checks, then one
   fresh-context read-only review. Record actual results and remaining input limitations.

## Initial Implementation Stop Point

Leave source changes unstaged and uncommitted. Do not push, merge, replace the normal App,
update a Release, call real services, read real secrets, upload or send. Generated fixtures and
acceptance artifacts stay in ignored build/temporary directories. Existing help dismissal/focus,
VoiceOver and other deferred manual checks are not silently accepted by this feature.

## Approved Source Closeout (2026-10-28)

The user subsequently authorized pre-commit checks and review, followed by signed-off commits
and a push to the existing Draft PR. Split the shared projection/protocol from native browsing,
evidence positioning and acceptance documentation; keep protocol dependencies buildable together.
Do not include Apps, installers, private configuration, credentials or acceptance artifacts.
Manual input/accessibility gates remain pending. No merging, Release update, live research or
delivery is authorized. This approval supersedes the initial no-commit stop point above.

## Implementation Record

- Shared projection, strict bridge command, native Papers browser, and report/reading/evidence
  return navigation are implemented in source. There is no relation inference or pipeline change.
- Two dated report fixtures are processed by the production frozen engine through the native
  AppStore/client/supervisor. The startup loader reconstructs the same ledger; original draft
  and HTML bytes remain unchanged. The fixture includes public v1 and source-only v2.
- The native evidence-entry test checks real scroll offset, not only a selected-paper property.
  Topic filters/selections, stale responses, busy state, and completed offscreen loads are covered.
  A pending read is reused on quick reopening; changing topics cannot replace the visible ledger
  with an older response. Successful offscreen results remain cached per topic/report set.
- Independent read-only review identified query-ID collisions, reference-only omissions, legacy
  seen-entry omissions and discarded offscreen results. Each has a focused regression and fix.
- Validation is offline. Rendered bilingual light/dark views are layout evidence, not proof of
  physical menu-bar input, focus behavior or accessibility acceptance. The normal installed App
  has not been replaced for this slice. Independent candidate control-path acceptance follows.

Final checks: Python **985 passed, 2 existing opt-in checks skipped**; Swift reported
**350 tests in 61 suites passed**, with the ledger's frozen-engine check explicitly enabled.
The separate existing frozen-daily/cover opt-ins were not enabled by this task. Ruff, localization
syntax, privacy and diff checks passed. The independent frozen engine passed symlink, private-path,
arm64 dependency and signature checks. Eight bilingual light/dark list/history renders were
inspected. Read-only review corrections were rechecked with no remaining finding. No live
services, real credential values, delivery, Git staging, commits or pushes were used.

## Independent Candidate Acceptance (2026-10-28)

Built a separate production candidate with current native code and a fresh bundled Python
engine, using the existing certificate and the same designated signing requirement. Bundle,
private-path, dependency, symlink and signature checks passed; logical size is 50.08 MiB.
The normal App and both previous candidate bundle trees remained byte-for-byte unchanged.
No certificate, credential or personal configuration was imported into the test workspace.

The actual candidate was launched with a separate owner-only data root, disabled schedules,
disabled delivery, and a local provider configuration without secret-backed routes. Two synthetic
Chinese reports cover one paper's public v1 and source-only v2 plus a source-only second paper.
They are interface fixtures, not new research findings or real cross-day history.

Accepted with actual candidate AXPress/owned-control mouse events:

- Topic paper merging, dated version occurrences and unknown-version copy.
- All/with-reading/source-only filters.
- Each original report, its full HTML, public v1 reading, evidence quote/location and safe source
  link display. External source links were not opened. Returning preserves the ledger selection.
- Menu-bar collapse/reopen, compact/full retention and restart reconstruction/evidence lookup.
- The evidence disclosure expands; an owned-pane scroll-wheel event makes the original quote
  and location visible without hiding the return controls.
- Within a session, navigation/reopening reused the ledger cache. Restart produced one new
  offline read. All observed requests were `read_paper_ledger`, never research or delivery.
- Original draft/HTML/index and isolated configuration bytes remained unchanged. The candidate
  exited, with no candidate helper remaining.

Limits: native control automation is not a physical-user sign-off. AX search value assignment
did not update the binding, and synthesized keyboard text was inconclusive; keyboard search
remains pending rather than a declared product defect or a passed test. Initial focus loss and
the broad disclosure-frame click were observer limitations; the actual disclosure control action
and scroll-wheel path passed. Help dismissal/focus, VoiceOver, multiple displays and accessibility
appearance gates retain their previous status. No product-code repair, normal-App replacement,
real service call, real credential-value read, sending, Git staging, commit, push or Release update.

Ignored artifacts include the independent candidate, explicit isolated-launch helper, owned-window
captures, input/bundle fingerprints and structured acceptance record. They are not committed.

Initial post-acceptance regression status: the candidate engine's targeted ledger run passed seven tests
but failed `evidenceEntryScrollsToTheExistingEvidenceSection` with an observed offset of zero.
An isolated repeat failed at the same assertion. Content and paper selection loaded correctly;
the native candidate's evidence entry, disclosure and manual-style scroll had passed separately.
These are different observations: the real control path does not erase the test failure, and the
test-window failure alone does not establish its cause in the production popover. Initial-scroll
timing/layout needs a bounded follow-up before declaring this slice's current checks fully green.
No retry was used to hide the failure, and no speculative product repair was made in this
candidate-acceptance task. The earlier full-suite result above is historical, not a replacement
for this latest targeted result. Do not proceed to commit on the assumption that all tests pass.

## Evidence Positioning Follow-Up (2026-10-28)

The isolated failure was reproduced before changing production code. The report and selected
paper were correct, and the native scroll document was taller than its viewport, but its offset
remained zero. Lifecycle tracing showed that the evidence view could appear before the scroll
layout accepted the one-shot request; `Task.yield()` was not a layout-readiness contract.
A diagnostic later request reached the same target. That diagnostic delay and all trace prints
were removed, not retained as a fix or hidden by a longer assertion timeout.

The fix is App-only: position from the native scroll-content geometry update, then consume the
initial evidence target once. Manual chapter jumps retain their existing path. There is no
fixed-delay retry, background polling, new protocol, artifact rewrite or research-flow change.

The native regression now covers four English/Chinese and fresh/preloaded-content cases. It
checks that the viewport reaches the short evidence section at the end, not merely any positive
offset; subsequent manual scrolling and width changes cannot reapply the initial jump, and
switching papers starts at the top. Draft and HTML bytes are preserved.

Current offline checks: Python **985 passed, 2 existing opt-in checks skipped**; Swift **350 tests
in 61 suites passed**, including the explicitly enabled ledger frozen-engine test. Ruff, privacy
and diff checks passed. A separate candidate updated only the native binary, reused the existing
frozen engine and signing selection, and passed bundle/dependency/symlink/private-path and strict
signature checks. The normal App and prior candidate remained unchanged.

Actual isolated popover controls reached the evidence section without a scroll-wheel action,
expanded its original quote, and returned through the original report to the selected paper's
history. The initial landing was visually checked in an owned-window capture. Fixture report,
HTML, index and configuration bytes were unchanged; the only new engine request was an offline
ledger read. The candidate exited with no helper residue. The observer initially ran before the
menu-bar control was ready; its readiness wait was corrected without changing the App startup.

Native control automation is not physical-user sign-off. Keyboard search, help dismissal/focus,
VoiceOver and the previously deferred manual gates remain pending. No real service, credential
value, delivery, staging, commit, push or Release update was used. Generated candidates, traces
and captures remain ignored; this follow-up does not authorize source closeout.

## Source Closeout Corrections (2026-10-28)

Pre-commit review reproduced three edge cases and added offline regressions:

- Preserve raw generic query identity: repeated-key order and literal `+` versus `%20` can
  identify different resources. No new provider-specific inference was introduced.
- Match the reader and ledger using Foundation URL values; raw provenance strings stay intact.
  Chinese, accented and space-containing paths can open their original public reading/evidence.
- Mark local image loading as settled, then wait for the resulting native scroll layout before
  consuming the initial evidence request. Late images cannot displace its target. The eight
  native cases combine language, initial content loading and images; they also check user
  scrolling, resize, paper switching and unchanged draft/HTML bytes.

The user-scroll check now delivers an actual native scroll-wheel event. Directly editing the
clip-view coordinates bypassed SwiftUI's scroll state and could be undone by a resize even
without another App positioning call; temporary tracing distinguished that harness behavior.
No trace prints, fixed delay, runtime polling or repeated scroll attempts remain.

A fresh isolated candidate contains the corrected native code and frozen Python engine, with
the existing signing selection and bundle checks. Old Apps and real configuration are retained.
Earlier captured physical-input limitations remain pending; these regressions and packaging
checks are not new physical-user acceptance. The strict protocol still rejects malformed
results. No credential, research, delivery, merge or Release operation is part of closeout.
