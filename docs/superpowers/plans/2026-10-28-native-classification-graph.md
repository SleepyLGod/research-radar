# Native Classification Graph Implementation Plan

**Goal:** Browse the saved topic organization as a clickable classification graph, with
paper features, membership reasons and immutable source evidence.

**Architecture:** Python projects an already validated snapshot through the existing
`read_topic_knowledge` / `organize_topic` results. Swift Core owns typed data validation;
an App-owned topic-scoped model owns selection and filters. SwiftUI lays out classification
nodes and paper cards; it never infers a group or relationship.

**Tech Stack:** Existing Python services, version-1 JSON bridge, SwiftUI and Foundation.

**Spec:** [Organization design](../specs/2026-10-28-topic-knowledge-organization-design.md).
This is the first native classification view of the approved graph direction, not all three
Demo views. Structure diagrams and paper-to-paper relation rendering remain later slices.

## Constraints and choices

- Preserve existing uncommitted work, Apps, reports, configuration and snapshots.
- No providers, real credentials, search, delivery, new dependencies, commits or pushes.
- Use deterministic classification layout, not a simulated force network or embedded browser.
  Each edge is a stored group membership; shared membership does not imply scientific agreement.
- Add an optional graph projection; keep legacy summary-only results readable. No new command,
  snapshot rewrite, model call or second database is required.
- Show AI organization as interpretation; keep source statements, synthesis and unknown features
  distinguishable. References retain report identity/checksum, exact pointer and original quotes.
- No inferred thumbnails, generated recommendations, fixed taxonomy or sample papers in production.
- Keep state per topic/snapshot, preserve it on close/reopen and clear only invalid selections
  after a changed snapshot. The ledger remains available, including source-only papers.

## Review Focus

1. Multi-label membership must show one paper identity, not duplicate paper records.
2. Papers absent from the chosen facet's groups remain accessible as unclassified.
3. Missing/unknown references or cross-paper membership must fail validation, not show fake evidence.
4. Loading another topic or accepting a new snapshot must not show the previous topic's selection.
5. Long Chinese/English titles, empty groups and narrow content must remain scrollable and usable.

## Tasks

### 1. Snapshot projection and typed contract

- [x] Add failing Python projection and Swift shared-fixture tests; retain summary-only fixtures.
- [x] Project facets/groups/papers/references from validated snapshots, without private paths.
  Add `KnowledgeGraphV1` and optional `TopicKnowledgeV1.graph`; validate identities, membership,
  references, counts and public source URLs at the existing codec boundary.
- [x] Pass focused Python/Swift tests, including malformed and legacy payloads.

### 2. Native graph and details

- [x] Add failing model tests for facet selection, keyword search, multi-label membership,
  unclassified papers, topic isolation and snapshot replacement.
- [x] Extend the existing topic presentation model, not AppStore business logic. Add graph/list
  switching to the ledger, a facet picker and clickable group-to-paper nodes with native focus.
- [x] Paper detail shows full identity, keywords, feature basis, membership reasons and expandable
  saved claim/quote evidence with safe original links. Existing ledger history remains the route
  to reports; returning preserves graph selection. No direct guessed claim-to-paragraph mapping.
- [x] Pass model and native hosting checks. Keep view, layout and detail files focused.

### 3. Offline acceptance and documentation

- [x] Run regression, Ruff, privacy and diff checks and a read-only review of this slice.
- [x] Exercise native views with an isolated saved snapshot, not a real model. Record exactly
  what was observed; leave keyboard/VoiceOver/multi-display gaps explicit.
- [x] Update TODO and this plan; report results and stop without staging or publishing.

## Validation record (2026-10-28, unreleased)

- Full Python regression passed with the two existing opt-in skips. Full Swift regression passed:
  372 tests in 65 suites; optional frozen-workflow tests remain opt-in, not silently counted as
  live acceptance. Ruff, privacy and whitespace checks passed. The existing unrelated reader-test
  weak-variable warning was not changed.
- The shared fixture covers classification, overlapping group membership, unknown features and
  exact source evidence. Invalid identities, cross-paper/unknown refs, unsafe URLs, bad counts,
  malformed pointers and unsupported fields are rejected. Legacy summary-only results round-trip.
  Model tests cover unclassified papers, keyword any/all filtering, topic isolation and valid
  selection/scroll-target retention. Native host tests cover graph/detail layout, not real key presses.
- Read-only review found two valid issues: the native contract incorrectly applied the organization
  text cap to original quotes, and keyword-only papers lacked an evidence disclosure. Saved source
  text is now preserved without that new cap; keyword citations reuse the same source disclosure.
  A long-quote regression and keyword-only reference preservation check pass. An in-process host
  accessibility probe could not expose SwiftUI disclosure actions reliably; its unsuccessful click
  check was not retained as a passing test. Actual keyword expansion was checked in the QA App.
- Built independent signed production/QA candidates, keeping all previous Apps. The QA bundle
  has identical native machine code and signer but a test-only engine that allows only saved-ledger
  and saved-knowledge reads. Its network, child-process and secret-manager boundaries reject access.
  No organization/model/research/delivery job was admitted during graph acceptance.
- With a copy of the already saved two-paper offline snapshot, actual Chinese native controls
  exercised graph-to-paper, keyword and membership evidence, original-source link visibility,
  ledger history and return, and popover close/reopen. The links were not opened. Report, HTML,
  ledger index and knowledge snapshot bytes stayed unchanged. The snapshot's fixture grouping
  is explicitly not a model research judgment.
- Chinese/light graph and evidence screenshots were observed; English/dark classification was
  captured and inspected. English detail automation was blocked by control-tree/focus issues, so
  that path remains unaccepted. Manual keyboard/focus, VoiceOver, multi-display, long-graph scroll
  restoration and larger-topic layout remain pending. No full three-view Demo parity is claimed.
- Production bundle symlink/dependency/private-path and strict signature checks passed; sanitized
  PATH non-live preflight succeeded. Production contains the knowledge projection, not the QA
  entry. Idle QA had no engine/PDF helper. This is not a new five-minute resource benchmark.
- Original Apps/configuration were not replaced. Raw screenshots, test bundles and audit records
  remain ignored local artifacts. No real credential values, providers/search, sends, Release/DMG
  update, stage, commit or push occurred. Structure/relation views, facet editing, automatic and
  incremental organization, and live model-quality validation remain separate tasks.
