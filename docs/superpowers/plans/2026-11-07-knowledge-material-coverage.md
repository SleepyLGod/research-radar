# Knowledge Material Coverage

## Goal And Boundaries

Connect saved reports to the existing topic graph: show new papers, new versions and updated
public material, then reuse explicit full-scope organization. This is not incremental inference,
automatic organization, a new research run or a scientific-quality score.

## Implementation

- Shared Python adapts reports through `build_knowledge_input` and compares versioned paper
  identities, public material and exact provenance with the validated immutable snapshot.
  New report references for an existing paper are material updates, not new papers. Source-only
  reports add no eligible paper. Missing, unsafe or unreadable material yields unknown coverage;
  cancellation remains cancellation. Neither reports nor snapshots are rewritten by comparison.
- The existing `read_topic_knowledge` command optionally accepts saved report references and
  returns optional coverage. Older topic-only requests retain their previous result shape;
  missing coverage in older results is unknown, never assumed current. No protocol version or
  persistent snapshot migration is needed.
- AppStore supplies the topic's saved report scope. The presentation model retains the old graph,
  camera and valid selection during refresh and masks outdated coverage on a failed read.
  Views do not read report files, resolve providers or access credential values.
- The native toolbar shows concise changed-material counts and an on-demand list linking to
  existing paper history, original reports, public reading and evidence. History shows coverage
  by version; source-only occurrences retain their existing status. The existing action becomes
  Update knowledge when needed and still performs full organization with cost confirmation.
- Existing queue/cancellation and atomic snapshot promotion remain unchanged. Failed/stopped
  organization retains the old graph and pending changes. Refresh follows workspace visibility,
  report scope, manual refresh and organization completion; no timer or background scan is added.

## Offline Checks

- Python regressions cover stable inputs, new identities/versions, new occurrences, source-only
  reports, changed material, missing/cross-topic reports, removed scope and cancellation.
  A scoped production bridge read forbids provider and credential construction.
- Swift regressions cover optional wire compatibility, scoped request encoding, malformed status
  rejection, unknown versions, exact-version presentation, read failure and saved report scope.
- Two synthetic dated reports reuse unchanged public MemConflict/MemGuide excerpts. A private
  native QA candidate substitutes only organizer execution with a stored-response replay and
  blocks network/process-based service access. This is not new model-quality evidence.

## Delivery Status

Implementation and offline acceptance are complete. Full Python: **2,540 passed, two existing
opt-in frozen-engine cases skipped**. Full Swift: **414 tests in 76 suites passed**. Ruff, privacy,
diff and production-candidate bundle checks passed; both independent candidates use the existing
signing certificate and pass strict signature verification.

The native offline candidate exercised old/current input, new material, the differences popover,
paper history, original-report evidence and return, cancelled confirmation without a new job,
organization failure/stop retaining the old snapshot, successful update clearing the notice,
and restart. Chinese light and English dark full layouts plus compact mode were captured.
The classifier response was a stored replay, not a live model result. Initial AX confirmation
feedback and a concurrent graphics-test attempt were inconclusive; the final isolated run used
owned control clicks and checked persisted job/snapshot state, not action return codes alone.

Read-only review reproduced stale current coverage while the preceding ledger read was still
pending. Its native regression first failed, then passed after invalidating coverage before
that read (including deferred reads). Only coverage and the obsolete response token are
invalidated; the old graph, camera and valid selections remain. Re-review found no remaining
actionable finding. The refreshed final candidate passed an additional explicit offline update
and restart; source report bytes and the ordinary development App stayed unchanged.

Implementation and offline acceptance used no live research services, real credential-value
reads or delivery. Source closeout is separate from packaging, installed Apps and the Release;
committing this feature does not update any of them.
Original reports, earlier snapshots, real configuration and older Apps remain intact. Physical
keyboard/focus, VoiceOver, multi-display and real organization quality remain unaccepted by this
task; no automatic/incremental or periodic organization has been added.
