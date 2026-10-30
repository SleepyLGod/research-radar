# Topic knowledge service: first offline slice

## Scope

Implement the shared Python service behind the approved graph demo, not the graph UI.
Consume saved public deep reads, never raw candidate prose or new PDF reads. A caller
supplies the existing `LLMProvider` and model; this slice does not resolve credentials,
add routes, bridge commands, CLI commands, schedules or deliveries.

The first operation is an explicit full organization of the supplied report set.
It is not incremental maintenance. Callers must supply the intended complete scope;
coverage and report fingerprints remain in every snapshot. Automatic refresh and
reuse of extracted features are subsequent tasks.

## Boundaries

- `storage/paper_ledger.py`: share existing paper identity and safe saved-draft loading;
  preserve the current ledger output.
- `storage/files.py`: add an optional pre-replace check to the existing atomic JSON
  writer, so cancellation/freshness can be checked after staging and before promotion.
  Callers that omit it retain the previous behavior.
- `analysis/knowledge_inputs.py`: build version-scoped paper keys and exact claim
  references from public drafts. Preserve original quotes and source pointers.
- `analysis/topic_knowledge.py`: original research-specific prompt, strict response
  validation, multi-label groups, evidence-backed relations and bounded synthesis.
- `application/topic_knowledge.py`: explicit provider call, cooperative cancellation,
  source freshness check, private snapshots and atomic current pointer.
- `tests/test_topic_knowledge.py`: exercise real adapters, validation and storage;
  replace only the model boundary with an offline provider.

The prompt adapts the structures discussed in the approved design spec (A-MEM,
Graphify and GraphRAG); it does not copy their prompts, code or dependencies.
Validation checks references and structure, not whether an AI interpretation is true.

## Tasks

- [x] Add failing tests for report identity/version/provenance, missing or unsafe
  materials, unsupported claims and preservation of original artifacts.
- [x] Implement the adapter and strict result contract. Test unknown/cross-paper
  references, malformed JSON, unknown fields, ungrounded relations and unknown features.
- [x] Add the explicit service and failure tests: model failure, cancellation,
  changed input, concurrent operation, corrupt storage and failed promotion must
  leave the previous current snapshot intact.
- [x] Run focused/full Python tests, Ruff, privacy scan and diff checks; do an offline
  smoke on the retained two-paper report and a read-only review. Record limitations.

## Service contract

`organize_topic(workspace, topic_id, reports, *, research_question, provider, model,
language="zh", cancelled=...)` returns the saved snapshot and its path.
`load_current_knowledge(workspace, topic_id)` reads a validated current snapshot or
returns `None` when no pointer exists. Invalid existing storage fails visibly.

Each paper key includes ledger family identity and explicit version (unknown stays
unknown). Each reference identifies a report ID/date, SHA-256 and exact JSON pointer.
Original reader `claim_id`s cannot be reconstructed from public drafts. Only admitted
claim entries with same-paper evidence are inputs; title-only sources are counted as
uncovered, not analyzed. The snapshot contains no local run path.

Output contains paper keywords/features, facet definitions, multi-label group
membership, conservative paper relations, topic synthesis and open questions.
Unknown features carry a missing-material explanation instead of an invented value.
`source_statement` and `synthesis` are distinct; open questions are not findings.

One operation makes one provider call (the injected provider retains its own existing
transport behavior). Cancellation is checked before/after the call and before current
promotion; the caller must bind its existing transport cancellation to the provider
for interruption during a blocking request. No new thread or polling loop is added.

Private files live under a topic-hashed `workspace/knowledge/` directory. A per-topic
nonblocking file lock serializes promotion. Write an immutable snapshot first, then
atomically replace the current pointer. Failed promotion may leave an unreferenced
snapshot, but never replaces the previous pointer. Corrupt files are not reset/deleted.
Input reports are rechecked before promotion. A later report change requires another
explicit organization; this slice does not watch files.

## Acceptance

No App changes, actual model calls, secrets, searches, sends, commits or pushes.
Offline fixtures establish workflow/provenance safety, not classification quality.
Native graph rendering, automatic refresh, confirmed user facets, incremental reuse
and real Codex/DeepSeek quality comparison remain pending.

### Implementation decisions

- Reuse the existing ledger hash rule and saved-draft path policy through two small public
  helpers; existing ledger results are unchanged.
- The first adapter intentionally uses only admitted, anchored public claim entries. It
  excludes explicitly non-supported entries and does not infer facts from title-only sources.
  Coverage records selected reports, deep-read entries and excluded claims/readings, not the
  size of the whole topic literature.
- Public claim provenance is an exact report hash plus JSON pointer, not an invented original
  reader claim ID. Versions remain separate even within one paper family.
- Safety limits are 512,000 request characters and 1,048,576 response characters. These prevent
  unbounded payloads, not guarantee that a chosen model's token/context budget is sufficient.
  Oversized material fails visibly; it is never silently truncated.
- Each operation is a full organization of its explicitly selected scope. It does not merge
  previous summaries or pretend to implement incremental maintenance. Prior snapshots remain
  on disk, but are not inputs to the model in this slice.
- Metadata retains provider/requested/returned model and recognized returned inference settings;
  missing inference settings remain unknown rather than invented. Arbitrary diagnostics are
  not persisted. Snapshot and input fingerprints are provenance checks, not signatures.

### Offline acceptance record

- The initial test run failed because the service modules did not exist; the implementation
  then passed the focused adapter/contract/persistence and existing ledger tests.
- A retained Chinese public report with two deep reads adapted into two version-scoped papers
  and 85 exact public-claim references. A network-blocked echo provider exercised save/reload;
  original and copied report bytes remained unchanged. No new research was performed.
- The echo output is a workflow fixture, not AI organization. Native cards/graph views and
  actual organization quality remain unverified.
- Final checks: 45 knowledge-service cases plus 13 existing ledger cases passed; the full
  Python suite passed with 1,030 tests and two existing skips. Ruff, privacy scan and tracked/
  untracked whitespace checks passed. No Swift or bundle changes are in this slice; prior
  native acceptance is not being re-claimed.

### Final read-only review

- One valid issue: cancellation arriving during current-pointer staging could still promote the
  new snapshot. Two reproducing tests failed first (cancellation and source mutation at that
  exact boundary). The shared atomic writer now runs an optional pre-replace check after staging;
  both tests pass, preserving the previous pointer byte for byte. Existing callers are unchanged.
- A stop or source change observed before promotion prevents promotion. A cancellation arriving
  after the atomic replacement is a completed operation, not a rollback request.
- This check is cooperative, not a transaction against unrelated external report writers. The
  snapshot always retains exact source hashes; no background watcher claims perpetual freshness.
- No other actionable findings in this slice. Semantic interpretation and real provider quality
  were not accepted by the code review or the offline echo test.

## Prompt Revision After The First Real Check

`topic-knowledge:2` tightens only the organization instructions. The JSON schema, validator,
provider routing, research/evidence gate, App presentation and snapshot-reading behavior are
unchanged. Historical `topic-knowledge:1` results remain readable and are not silently repaired.

The prompt now asks for groups before facets, no unused facets, discriminating classifications
and nonexclusive contribution roles. Relationships need a specific same-question or same-operation
connection: orthogonal assumptions are not a disagreement, synthetic multi-session data alone
does not establish shared evaluation, and a recommendation is distinct from an implemented method.
Each factual clause needs the actual supporting references; an existing reference ID from each
paper is not enough. Uncovered details should be shortened/omitted rather than filled in, with
no quota of groups or edges and no new model stage or automatic retry.

The fixture `tests/fixtures/topic_knowledge_real_case.json` is a public, distilled excerpt of the
first real MemGuide/MemConflict result: 34 selected input references, retained feature/group/edge
text and its original evidence. It omits the rest of the 85-claim input and unrelated output fields.
It contains no local paths, configuration, credentials or raw logs. Its original-result checksum
records provenance; the original private snapshot and acceptance artifacts remain unchanged.

The separately labelled reviewed replay is hand edited: it removes unused facets/two weak edges
and attaches missing protocol/retrieval references. It is not a new model result. Six offline
regression cases exercise prompt-version provenance, unchanged legacy snapshots, request/evidence
preservation through the actual service/projection, and rejection of invented, one-sided or
wrong-paper citations without replacing the previous pointer. Network and Keychain boundaries are
forbidden in these cases. The version-provenance test first failed against revision 1, then passed
after the prompt update; the tests do not assert that wording alone fixes semantic interpretation.

Validation: 64 focused cases and the full Python suite passed (1,049 tests, two existing opt-in
skips), as did Ruff. Privacy/whitespace and protected-file checks are recorded in the matching TODO
checkpoint. No Swift, wire or UI code changed, so no App rebuild or new native acceptance is claimed.
The parser still validates structure/provenance, not semantic entailment; even a new response can
violate these prompt-only quality instructions while being structurally valid. Actual improvement
remains unverified until a separately approved real comparison. This slice calls no live service,
reads no real credentials, sends nothing and does not stage, commit or push.

## Single Real v1/v2 Comparison

A subsequent authorized comparison reused the saved v1 result and ran v2 exactly once. Both
operations have byte-equivalent adapted inputs: the same MemGuide v2/MemConflict v1 public deep
reads, 85 references, question/language and input fingerprint. Both request/record DeepSeek
`deepseek-flash` with thinking enabled/high effort. The new isolated native candidate reused the
existing UI/signing identity and updated only its bundled engine; one organization job and one
model HTTP request succeeded. No discovery, PDF reading, report regeneration or delivery occurred.

Observed improvement in this pair:

- Empty facets decreased from three of six to zero of five; the new eleven groups distinguish
  problem focus, mechanism roles, evaluation targets, testbeds and assumptions. Group count is not
  a quality score, and two papers cannot establish large-topic taxonomy quality.
- The broad shared_evaluation edge was omitted. Related-mechanism evidence became more focused
  while preserving implemented reranker versus design-recommendation roles. Three edges remain.
- The diagnostic-protocol group now cites the explicit two-level-protocol claim; metric/human
  evaluation descriptions select the corresponding supplied references.

Unresolved or worsened in this same result:

- different_assumption still largely compares research/modeling focus, not clearly different
  choices on the same assumption. It remains a weakly typed reading connection.
- The input's example `K=5` became an unqualified fixed setting in a mechanism/assumption
  description; v1 had retained the example qualifier. Accurate digits alone are not enough.
- Some factual qualifications still lack their direct selected references, and some inferred
  assumptions are labelled source_statement rather than synthesis. Do not call citation coverage
  or interpretation attribution fully accepted. A newly mentioned DTE value was checked against
  the provided original quote and was present; it was not labelled invented merely because the
  atomic claim's short text omitted it.

The actual native App rendered the new classification and each saved relation reason with both
reference sets. Both endpoint actions of the mechanism relation opened their correct local paper;
the exact source quotations were matched in the accessibility tree, with return to the same relation.
Final screenshot/frame review did not accept automatic source positioning: one quotation remained
below the visible window after layout settling. Subsequent scroll automation lost the transient
popover. Correct content/routing is not proof of on-screen positioning; its cause and manual scroll
remain a separate check, with no UI fix attempted in this comparison. The old result/reports, normal
configuration, previous Apps and product source hashes remained unchanged. Package checks passed
and normal Quit left no owned App/helper process. Raw comparisons/screenshots remain in ignored
local acceptance output, not public fixture data or a Release package.

Conclusion: useful improvement in this example, not uniform accuracy improvement or a reliable
autonomous-organization gate. One pair cannot rule out sampling/service variation; no fixed random
seed, expert annotation, independent full-paper verification or broader-topic benchmark is claimed.
No extra organization was requested to obtain a better answer. This checkpoint changes no product
code, does not rerun Python/Swift regression for an unchanged source tree, and does not commit,
push, modify real settings, send or update Release/DMG artifacts. Broader semantic/manual gates
remain open; the old snapshot remains the comparison baseline.

## Cumulative Review: Scope And Capacity

The 2026-10-29 closeout review covered the cumulative source, tests and documentation, not a new
organization. CodeRabbit raised one major-labelled suggestion to add report/date-window selection
and validate multi-week capacity. The current App intentionally submits all saved reports for the
selected topic. Source-only entries contribute to coverage, not invented deep-read features;
the service fails visibly on unusable reports rather than silently changing the selected scope.

No scope picker was part of this first explicit full-organization contract. Adding one, filtering
out report records silently, or implementing batching/incremental maintenance at closeout would
change user-visible scope rather than repair the current contract. The existing size regression
verifies oversized input is rejected before the provider call without truncation. The suggestion
is therefore deferred, not claimed fixed: long-lived topics can reach the 512,000-character limit,
and useful large-topic behavior remains unaccepted. Both user guides now state the missing picker
and the capacity limit. A future bounded scope/capacity task must preserve coverage and provenance.
Two independent local code reviews found no confirmed actionable defects; this is not a guarantee
of semantic correctness or complete manual-interaction acceptance.
