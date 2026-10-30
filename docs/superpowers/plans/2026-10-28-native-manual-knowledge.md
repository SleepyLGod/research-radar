# Native manual topic organization

## Scope

Connect the shared knowledge service to the existing App engine and durable queue.
No native graph, automatic refresh, new scheduler, new research, delivery or live-provider acceptance.
Keep the previous uncommitted model/service changes intact. Do not commit or push.

## Contract and boundaries

- Python service owns source adaptation, model interpretation, reference validation and snapshots.
- Bridge adds `organize_topic` (topic plus saved report references) and `read_topic_knowledge`
  (topic only). Both return a small typed `knowledge` projection: topic, optional current
  snapshot metadata/counts. The subsequent [native classification slice](2026-10-28-native-classification-graph.md)
  extends that result with an optional read-only classification/evidence projection; it does not
  add a command or a second knowledge database.
- Manual organization uses the configured `deep_reading` provider/model, explicitly disclosed
  before admission. No verifier reuse, fallback route, new default model or credentials field.
  The topic's saved research focus and report language supply the organizing question/language.
- Swift Core adds one non-delivery job kind with captured report references. Existing queue,
  single-engine gate, cancellation and artifact reconciliation remain the execution path.
- App exposes an organization action/status beside the topic paper ledger. It reads snapshots
  only when that workspace is opened/refreshed or an organization terminates, never by polling.
- Repeated admission coalesces an active organization for that topic; a new explicit operation
  is allowed after a terminal state. No same-day research deduplication applies to organization.
- Failure/cancel leaves the previous snapshot readable. Missing terminal artifacts after a
  crash mean interrupted, not automatic retry. A snapshot committed just before a crash may
  still be read; terminal job state is not proof that committed knowledge was rolled back.
- Existing research reports, delivery records and notifications must not be changed by an
  organization. User-triggered cancellation after snapshot commit does not undo that commit.

## Steps

- [x] Add offline failing tests for bridge payloads/dispatch, credential-free reads and model
  injection; implement the two bridge commands and bounded summary projection.
- [x] Add Swift round-trip, queue/recovery and App admission tests; implement typed protocol,
  organization jobs and small native status/action surface with English/Chinese text.
- [x] Run Python/Swift regression, lint, privacy/diff and offline workflow checks; review the
  changed slice. Record what is code-tested vs. not manually or live accepted.
- [x] Build separate signed production/QA candidates and exercise the native organization,
  confirmation cancellation, stop, failure and restart paths with an offline model boundary.

## Acceptance

Use temporary roots and injected offline engine/model boundaries. Cover queued/running,
success/failure/cancel, old snapshot preservation, repeated clicks, topic isolation and restart.
No real secret values, network requests, sends, App replacement or Release modification.
Native graph, automatic organization and real model-quality comparison remain separate tasks.

## Implementation notes

- The App captures report IDs/dates/directories, question and language in the durable job before
  starting. Question/language are request fields because the shared research `TopicConfig`
  deliberately does not carry App display/research-focus fields. No second configuration loader.
- `OrganizationJobScopeV1` uses the existing durable JSON naming contract and translates to the
  wire payload once. Wire types are not directly nested in durable state: their explicit coding
  keys conflict with the durable decoder's snake-case conversion. A save/reopen test caught this
  during implementation; no real App data was involved.
- The read projection includes snapshot identity/date, report IDs, input fingerprint, provider/
  model and four counts. It omits local paths and raw evidence. This is status/coverage data,
  not a substitute for source-backed graph records. The subsequent classification slice adds
  their typed projection while keeping legacy summary-only results readable.
- The UI lives beside the topic ledger, with explicit cost confirmation and an active-task stop
  button. It does not present the counts as quality scores. An older snapshot stays visible if
  another operation fails. Completed results update the App's topic-scoped presentation cache
  directly; reads deferred by a busy engine resume on its idle transition, not a polling loop.
- Code/offline tests are distinct from native mouse/keyboard acceptance. The initial source slice
  did not rebuild a candidate; the later isolated candidate acceptance is recorded below.
  No live organization quality or new resource benchmark is claimed.

## Review and acceptance notes

- Python and Swift use the same canonical summary fixture. Unknown fields, secret-like fields,
  malformed counts and missing successful snapshots are rejected. Saved-read dispatch does not
  even construct a secret manager. Whole bridge execution uses an offline provider; no real
  model, search or send is part of these checks.
- Queue tests cover same-topic coalescing, terminal retry, private durable scope round-trip,
  legacy jobs and recorded-result reconciliation from a running state. App tests cover explicit
  confirmation changes, no material, cancellation, failure, topic isolation and unchanged reports.
  Delivery admission and notification policy remain research/delivery-only.
- Two review findings were addressed: busy topic reads could be dropped, and a global organization
  label could replace another topic's research-failure title. A native SwiftUI hosting test now
  holds topic A's engine read, switches to B, then verifies B's ledger and knowledge read complete
  after A is released. A separate status test protects B's failure title while A is organizing.
- Native hosting tests are not manual menu-bar/button acceptance. At the end of the source slice,
  a refreshed candidate and native controls were still unverified; see the later acceptance below.
  Real organization quality remains unverified.
- A few isolated test roots initially could not reach Trash under restricted permissions; the
  known test-only directories were subsequently moved to Trash with normal permissions. No
  permanent deletion or real configuration change was used.
- Final checks: Python 1,038 passed with two existing skips; Swift 364 tests in 63 suites passed,
  including the new native-host/deferred-read and cancellation cases. Optional frozen-workflow
  tests remain opt-in; they were not rebuilt/run for this slice. Ruff, privacy scan and diff
  whitespace checks passed. A preexisting weak-variable warning in reader tests was left alone.
- No stage, commit, push, installed-App/DMG rebuild, real provider/search, credential-value read
  or delivery took place. Existing model-name and shared-service work remains uncommitted.

## Isolated candidate acceptance (2026-10-28)

- Built a separate production candidate with the existing local signing identity, without
  replacing the normal development App or any earlier candidate. The frozen engine passed
  symlink, Mach-O dependency, private-path and strict signature checks. Sanitized-PATH preflight
  succeeded without a live probe. The production engine contains the organization service,
  not the acceptance-only entry point.
- A separately identified QA App used the same native machine code and signer, an isolated
  data root and a test-only frozen engine. It retained the production bridge, handlers, queue,
  validation and snapshot service; only model resolution and the credential boundary were
  replaced. Network/process-launch attempts inside that engine were blocked and audited.
  No real credential values were read. This proves the workflow, not model classification quality.
- Used one existing saved Chinese report containing two public deep reads. Native controls
  exercised: cancel confirmation without creating a job; organize successfully; stop another
  organization; fail another explicitly; quit and reopen. The three admitted organization jobs
  ended succeeded, cancelled and failed. Stop and failure left the successful current snapshot
  byte-identical; the snapshot and job records remained readable after restart. No retry, research
  or delivery job was added. Original draft, HTML and report-index bytes were unchanged.
- The actual confirmation exposed an untranslated `common.cancel` key. The only additional
  product fix reuses the existing `action.cancel` translation; the rebuilt native dialog showed
  the localized cancel button and its click created no job.
- Final focused Swift checks passed: 13 tests in two suites. Bundle/signature checks passed;
  old protected App hashes were unchanged and the isolated App had no idle engine/PDF helper.
  This was not a five-minute resource benchmark. Screenshots and raw test artifacts remain in
  ignored local build output, not in the public documentation.
- Mouse actions were automated against the actual isolated menu-bar popover. Manual keyboard,
  focus, VoiceOver and multi-display checks remain pending; real-provider organization quality,
  native graph rendering and automatic organization remain separate work. No DMG/Release,
  normal configuration, credential permissions, stage, commit or push was changed.
