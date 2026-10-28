# Native Per-Paper Research Progress

## Scope

Implement the accepted workspace demo's current-attempt progress in the native App. Keep the
existing overview, four public stages, serialized queue, cancellation and report behavior. This
slice does not implement the cross-day paper ledger, graph, classification or synthesis.

Implementation and acceptance stay offline: no live research, credential-value reads, delivery
or signing-identity changes. Existing App/configuration/report artifacts are retained. Offline
tests use temporary roots and fake services. Candidate builds and source closeout require separate
approval; installers, screenshots and other acceptance artifacts never enter the source commits.

## Layer Contract

| Layer | Responsibility | Excluded |
| --- | --- | --- |
| Shared pipeline | Existing events report actual work; the writer hashes source identity before redaction/truncation | No new model call, selection rule, retry or evidence threshold |
| Python bridge | Map whitelisted stage/status pairs into an optional typed `paper` field | Do not parse messages or forward source URLs, raw errors, prompts or evidence |
| Swift Core protocol | Strictly decode the additive field and retain legacy event compatibility | No UI strings or business decisions |
| App workflow | Forward same-stage paper events through the existing active-job observer; merge by request/source identity | No second watcher, queue or durable JSON format |
| App presentation | Native, bilingual rows under the four-stage strip, in compact/full views | No invented totals, untouched candidate rows, resumed task or verified-claim count |

### Event Extension

`schema_version` stays `1`. Existing events are unchanged when `paper` is absent. When present,
`paper` has exactly `source_id`, `title`, `status`, on a `progress` event with outer status
`running`. The outer status describes an ongoing attempt, not whether one paper succeeded.

- `source_id`: lowercase SHA-256 of the source URL, computed by `ProgressWriter` before metadata
  redaction/truncation, so long addresses or redacted values cannot collapse distinct identities.
  The bridge forwards that identity, not a hash of the shortened audit text. It is an opaque
  runtime identity, not a paper-family/version key for the later ledger.
- `title`: inline HTTP(S) URLs are replaced, then normal redaction/truncation applies, at most
  500 characters. No source URL, query parameter or failure body is added to the progress UI.
- Acquisition states: `acquiring`, `acquired`, `acquisition_failed`, `skipped` at `acquisition`.
- Reading states: `reading`, `read`, `reading_failed` at `deep_reading`.
- `paper_text_quality.failed` maps to `skipped`; a successful read maps to `read`, never to
  verifier acceptance. The pipeline's selection, fallback and failure policies are unchanged.

The canonical fixture is `Tests/Fixtures/Protocol/paper-progress-event.json`. Python generation
and Swift strict decoding/encoding use the same fixture. Unknown fields, invalid IDs, titles,
statuses or stage/type/status mismatches fail validation. Legacy events need no migration.

### App State And Cancellation

The App holds only the most recently observed research attempt for each topic. Within that
snapshot, each source has one row, in first-observed order; later events update the row. Request
ID and monotonic sequence isolate attempts. Delivery and checks never supply paper progress.

Only papers that actually started processing appear. The candidate pool can be larger than
`deep_limit`, because a failed/insufficient paper can be followed by another candidate; neither
that limit nor an event count is presented as a completion percentage.

During cancellation, in-flight rows show stopping. After cancellation they show stopped; already
read, skipped or failed rows keep their observed result. If an attempt ends without an observed
paper result, show that uncertainty instead of leaving it running or fabricating completion.

Existing reports remain independent. Starting another attempt gets a new request and an empty
progress projection; it does not resume the stopped request. Switching topic or compact/full mode
does not rebuild the engine or discard the current snapshot.

This is an in-memory runtime projection, not progress history. It survives popover dismissal but
is not reconstructed after App restart in this slice. Existing event artifacts and durable queue
and report records remain available; the UI does not guess old per-paper outcomes.

## Verification

- RED-to-GREEN checks for typed event forwarding and canonical fixture round trip.
- Real pipeline with fake discovery/reading produces the paper event sequence. Compare draft
  data excluding its independent creation timestamp, and byte-compare daily Markdown and
  WeChat HTML, with/without the listener.
- Same-stage events, per-paper failure inside a successful attempt, topic/attempt isolation,
  stale events and no invented rows.
- Existing observer drains final events and stops at job completion; no new idle watcher.
- App queue-to-observer cancellation: stopping, cancelled, retained report, new pending attempt
  with a different identity and no previous rows. All services and credentials are fakes.
- Full Python/Swift tests, Ruff, privacy and diff checks, plus a separate read-only review.

## Status And Stop Point

Implementation and offline verification are complete locally: Python **963 passed, 2 skipped**
(opt-in frozen integrations not enabled), Swift **338 tests in 60 suites passed**, Ruff, privacy
and diff checks passed. Swift's screen/clipboard/WebKit tests require normal graphical access;
the initial restricted-environment failures were resolved by that rerun, not by weakening tests.

A separate read-only review found two issues: hashing the already-shortened/redacted audit URL
could merge different sources, and a title could contain a raw URL with query parameters. Both
were reproduced in tests and fixed at their owning boundaries: identity before audit transforms,
URL removal before the wire title. No unresolved finding from that review remains.

The subsequent source-closeout review reproduced a third privacy edge case: an apostrophe inside
a title's URL could leave its query suffix visible. The URL token now includes apostrophes; two
additional path/query regressions first failed and then passed through the real progress-to-wire
path. The earlier signed candidates and UI captures predate this source-only follow-up; this
closeout does not rebuild or replace those Apps. Final Python regression is **965 passed, 2 opt-in
checks skipped**; the unchanged Swift slice passed **339 tests in 60 suites**.

Eight native rendered-view captures cover English/Chinese, light/dark and compact/full layouts,
with the real App queue/observer driven by a fake runner. They are not a real popover interaction,
system-material, accessibility or live-provider acceptance. No updated signed App or release is
implied. Existing manual acceptance gaps remain deferred; they are not silently marked complete.

After offline verification, report results and stop. Cross-day paper identity/indexing belongs
to the next approved slice; do not add it to this feature.

## Candidate And Bounded Native Acceptance (2026-10-28)

- Built a fresh, independent candidate with the current native executable/resources and frozen
  Python engine. Existing bundle, Mach-O, symlink and private-build-path checks passed, as did
  deep/strict signature verification. The candidate retains the existing development certificate
  and designated requirement. The previous development App's complete file fingerprint is
  unchanged; no installed App, real configuration, DMG or Release was replaced.
- Separately built an isolated QA App from the current production RootView, WindowCoordinator,
  AppStore, queue and observer sources. Its runner and secret backend are test-only replacements.
  Event templates come from the actual Python progress writer and bridge. The QA App contains no
  production engine, and the candidate contains no QA runner or test state. This is not an
  end-to-end production-engine/provider acceptance.
- Observed the actual owned native popover showing acquisition, first-paper reading, then the
  first paper read while the second was reading. After stopping, the completed read remained and
  the second paper showed stopped; the existing report identity and copied file bytes remained.
  Compact/full, Escape dismissal and the existing show entry retained the snapshot. A new request
  started with no old rows; its first event added only its own first paper. Topic switching did
  not mix those rows. Both offline attempts terminated as cancelled, with no delivery jobs.
- Owned-window captures and state records were retained locally under ignored build output.
  Credential-value reads were zero. No model, search, upload or send was performed. The QA App
  exited without leaving its process or helper behind.
- Input limits remain explicit: native AX button presses were unavailable, so run/stop used the
  same public AppStore actions as the controls. Local status-item mouse simulation bounced back
  open; Escape plus the existing controller show method exercised hide/reopen instead. Physical
  mouse/status-item routing, VoiceOver and multi-screen behavior are not newly accepted by this
  run. No production navigation change was made to work around the test-driver limitation.

The user also confirmed that the next topic workspace must include cross-day accumulation and
a paper/question graph, not a list alone. TODO records the shared-index, provenance and explicit
relation prerequisites. No cross-day index, graph or automatic classification was implemented here.
