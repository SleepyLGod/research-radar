# Chinese Publication: Contracts And Acceptance

Status: unreleased source, updated 2026-11-06. This page describes the current implementation
and latest acceptance. Earlier failed or superseded runs remain in the
[dated history](chinese-publication-history.md); their stopping conditions are not current results.

## Current Acceptance And Request Boundaries

Two final Chinese reports, **MemConflict** and **MemGuide**, completed the same shared
fact-review, writing and final-review path using saved extractions and original sources.

| Check | Latest result |
| --- | --- |
| MemConflict | 68 retained facts, 22 retained narrative paragraphs, no fallback section |
| MemGuide | 60 retained facts, 18 retained paragraphs, one noncore verified-fact fallback |
| Requested reviewers | Codex `gpt-6-luna/xhigh`, dynamic target-bound v5 schemas |
| Requested writer | DeepSeek `deepseek-flash`, thinking/high, streaming JSON, `max_tokens=131072` |
| Actual batch total | 6 Codex starts and 4 HTTP requests, including both approved local revisions |
| Time | About 33.4 minutes of model stages and 47.9 minutes elapsed, including offline repair/waiting |
| Scope | Saved extraction → fact/method review → Chinese candidate → whole-candidate final review |
| Not exercised | Fresh Reader, ordinary hard-budget CLI end-to-end, packaged App end-to-end |

The batch stopped on a confirmed composition defect: a coherent evaluation-procedure paragraph
was rejected solely because its supported IDs spanned method and measurement indices. The offline
repair removed that organizational prohibition, not evidence checks. Explicit continuation
preserved the original counters and deadline. Subsequent source comparison used the already
authorized one local writing/final revision per paper: restore MemConflict's reviewed main settings,
remove MemGuide's internal grid diagnostic, and narrow AutoTOD/A.I.C. attribution. Only experiment
prose changed; other sections and all fact translations were preserved.

Both reports are **usable for local reading with caveats**, not proof of every factual statement.
Counts describe retained material, not a research-quality score or independent reproduction.
The reports contain no inline claim IDs. Original reports and real user configuration were retained.
Subsequent closeout fixes have offline regressions; the live batch was not rerun after them.

The isolated run used existing `ReaderContextBudget.soft_limit` warnings for conservative byte
estimates; this did not change production defaults or establish served context capacity. Actual Codex
backend identity, internal service requests, usage and monetary cost were not available.
DeepSeek reported its requested alias, not an independently attested backend revision.
The CLI was neither upgraded nor switched during the batch. No extra probe, search, Reader rerun,
transport retry, JSON/quote repair, NVIDIA request or delivery was performed.

## Shared Publication Contract

The existing single-paper and daily pipelines retain one research implementation:

1. Reader receives the complete available extracted paper, instructions and schema. Unknown
   capacity or a hard-estimate overflow stops before cache/provider access; no text is silently cut.
2. Source matching and table evidence preserve identity, exact quotations, row/column headers,
   footnotes, comparison scope and experimental conditions. Local eligibility is not approval.
3. Chinese factual composition first obtains explicit fact/method decisions against original sources.
   Method actions, materials and links retain distinct identities; two true actions do not prove order.
4. The writer uses eligible facts to prepare Chinese claims and bound narrative paragraphs. Required
   method/condition/result coverage and quantity fidelity are checked before final review. Indices
   guide organization but do not force a coherent procedure into disconnected notes.
5. Final review evaluates the exact Chinese assertions and paragraphs, including translation,
   scope and source contradictions. A valid claim ID alone does not approve a paragraph. Missing,
   foreign or invalid required decisions cannot be cached as a complete review or publish the prose.
6. Public rendering retains approved paragraphs and conservative, final-language fact fallbacks.
   Original explanations, rejected material and candidates remain audit records, not public approval.

English retains one Verifier stage; structured Chinese uses fact review before writing and final
review after writing. Each stage can require multiple requests if production hard-budget planning
splits targets. Full original source and cross-paragraph context are retained in those requests;
no target or comparison evidence may be silently dropped to fit. One target that still exceeds
the declaration stops the plan before any request. Exact supported fact receipts may be reused
only while their target and evidence binding remain unchanged; final prose is reviewed afresh.

For an uncached successful Chinese run, composition uses one body request per paper plus a shared
claim/display request when needed. Daily figure-caption translation can add a later request.
Reader, search, optional quote repair and provider transport retries are separate costs.
These are stage descriptions, not a fixed call budget for arbitrary inputs.

## Remaining Quality Limits

- MemConflict retains K=3, conflict-type macro-averaging, query-time history and scoped rankings.
  The EUG body definition and Table 7 note disagree; the disputed assertion stays withheld.
- MemGuide retains retrieval/filter/generation distinctions, mixed metrics, pre/post-correction
  stages and generalization limits. Table 4's AutoTOD is a **simplified pipeline** according to
  the footnote. The report limits comparison to the paper's baseline; the separate source-review
  note records that qualification rather than inventing an absent reviewed implementation fact.
- A.I.C.'s body/appendix descriptions are not silently reconciled or independently recalculated.
  Table 6 (5.09 versus 5.05) and Table 12 (10.09 versus 10.90) contain source conflicts. A report
  must attribute discrepancies rather than select the preferred number.
- MemConflict c46 and MemGuide c4 were excluded by pre-model depth/entity checks, not rejected
  by the actual reviewer. They remain documented gaps, not newly resolved acceptance.
- Selected method facts are not an exhaustive workflow. Minor wording and renderer repetition
  remain. Source spot checks do not replace human verification of all retained material.

## App Boundary

Provider records carry optional `reader_contexts` keyed by exact model. The source App can
atomically save declared context capacity, output/thinking and overhead reserves; Python converts
them into the same shared CLI budget type. Failed saves retain the previous valid configuration.
Capacity failures use stable localized errors rather than a generic engine-crash message.
Chinese topics include the independent `report_localization` model in admission checks and
the budget editor; English topics do not require that unused writer budget. Scheduling checks
the scheduled topic, not whichever topic happens to be selected. Metadata-only preflight checks
the writer declaration when Chinese topics are configured, without constructing a provider.

Declarations are operator-supplied planning limits, not measured counts or discovered capacities.
Old configurations without declarations stop before complete-input work; they are not silently
migrated. A connection check does not establish sufficient reading capacity.
The installed v0.3.0b1 App/DMG has not been updated. Offline configuration/decoder checks do not
establish native interaction or real App end-to-end acceptance.

## Verification And Next Gate

Local closeout review reproduced and repaired these engineering defects without another model call:

- Source-block selections keep their original offsets through quote and positioned-table binding;
  identical text on another page is not interchangeable evidence.
- Reader, Chinese composition and legacy fact-review responses are validated before cache writes
  and when reading old entries. Invalid historical replies are misses, not persistent bad hits;
  a later explicitly requested run can therefore incur a new call. Valid abstentions remain distinct
  from malformed or incomplete receipts. Provider errors do not become Reader-format retries.
- Daily fact/final failures retain a failure envelope. If completed final review blocks required
  coverage, its feedback and reviewed claims/readings remain private audit artifacts; no public
  report is produced merely to preserve the failure evidence.
- Missing exact-model reading/review budgets prevent App admission and preflight readiness, without
  probing models to discover a capacity. Swift rejects unknown nested budget fields instead of
  dropping data that the shared Python loader would reject.

The follow-up repair also validates legacy translation replies before cache writes and on old
cache hits, using the same existing completeness, support-ID and quantity checks. Rejected replies
remain available to the audit projection but cannot become reusable successes. Optional source
gists and figure translations keep their existing fallback behavior. This is an offline repair,
not a new model-quality or packaged-App acceptance result; an explicit later run may make a fresh
request instead of reusing an invalid cached reply.

Follow-up verification: **2,403 Python tests passed**, with two opt-in frozen-engine cases
initially skipped. The test-only engine was then rebuilt from the same source and its nine-test
Python suite passed with both opt-in cases enabled. **410 Swift tests in 75 suites passed**,
including mixed-language budget admission, the frozen workflow and ledger, saved Chinese report
decoding and Swift configuration export. No additional product-code change was needed for this
rerun. Ruff, changed-file privacy scanning and diff checks passed; independent read-only review
found no further actionable defect.

The earlier restricted Swift attempt failed on temporary-file permissions and clipboard access;
it is retained as a failed attempt, not counted as a passing run. Its 128 logged temporary
directories were subsequently moved to Trash after explicit authorization. The successful rerun
used normal local system access, fake credentials and an engine that blocks network access.
These are offline integration results, not native manual interaction or real-model acceptance.
The distributed App/DMG and real configuration were not changed; earlier deferred manual checks
remain open.

The latest report-delivery checkpoint passed 44 isolated-entry/scope guards. The unchanged shared
source passed 2,344 Python tests with two existing opt-in frozen-engine skips; Ruff, privacy and
diff checks passed. Those results describe that checkpoint, not future edits or skipped tests.

The later closeout review passed **2,395 Python tests**, with the two opt-in frozen-engine tests
then enabled separately in a **nine-test passing run**. **408 Swift tests in 75 suites** passed,
including the explicitly enabled frozen workflow, ledger, report decoding and configuration export.
The actual Swift-encoded declarations also loaded through the production Python converter.
Ruff, source/test/document privacy scans, changed-document links and diff checks passed. The two
latest report HTML hashes are unchanged. No additional real model, search, secret-value access or
delivery was used. Source-ID test fixtures were corrected explicitly where partial-source fixtures
had retained full-paper IDs; strict foreign/stale-selection rejection remains tested.

These are offline engineering checks, not renewed live acceptance of the closeout changes.
Source commits exclude private reports, screenshots, credentials, App/DMG and acceptance runners.
Native accessibility/input checks remain manual; a later packaging or release needs separate approval.

The next live product gate is a normal-configuration CLI run including fresh Reader work, with
explicit routes and an agreed budget. It is not permission to rerun these two final reports,
change models or send content. Deferred App accessibility/multi-display/help-focus checks remain
listed separately in the [roadmap](todo.md).

## Historical Evidence

- [Dated publication checkpoints](chinese-publication-history.md): original failures, fixes,
  request counts, source conflicts and the earlier hard-budget investigation.
- [Reader input and evidence](reader-input-evidence.md): complete-input and source-table boundaries.
- [Reader output reliability](reader-output-reliability.md): schema preparation and historical probes.
- [Reader-to-report audit](reader-chain-audit.md): earlier offline quality baseline, not current status.

No document grants service access or guarantees that any model will always produce a reliable report.
