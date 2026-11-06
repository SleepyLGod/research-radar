# Complete Reader Inputs and Table Evidence

Status: unreleased shared Python changes, updated 2026-11-01. Offline verification only;
no new model, search, credential or delivery request and no App/package update.

## Responsibility Boundaries

The input builder decides what source text is actually supplied. Evidence handling
preserves literal source context and checks simple, unambiguous row/column bindings.
The Reader interprets that material; the Verifier evaluates whether it supports the
complete claim. Neither prompt instructions nor valid JSON establish factual accuracy.

This slice builds on the [fixed-response quality audit](reader-chain-audit.md).
It does not automatically repair that audit's disputed scientific conclusions.

The latest offline boundary repair distinguishes explicit names/versions from ordinary
hyphenated descriptions and symbolic parameters. Local quote/numeric/identity checks remain
necessary, but a successful literal match is not semantic verification. Existing Verifier
review still determines whether the exact assertion follows, including method roles and
experimental qualification. Self-dependencies fail the method structure contract; a true
setting is not automatically an action. See the
[historical evidence/role boundary](chinese-publication-history.md#local-evidence-and-method-role-boundaries-offline-repair).

## Reading Input

- Recognized numbered/named sections and conservative title-shaped boundaries split
  page text into smaller source-addressed excerpts. Continuations retain their section
  role instead of being reclassified from the frequency of words on each page.
- Section headings only index the text; they no longer decide what is retained. The
  complete `Artifact.text` is supplied once, with inline source-block labels for new Reader
  calls. Removing the labels reconstructs every original character, including page markers,
  whitespace, references and appendices. Stored text remains unchanged. The fixed 24,000-character selection and
  role-sharing algorithm have been removed. An explicitly supplied character cap
  rejects the whole input instead of returning a shortened packet.
- Section-index warnings mean a heading was not identified, not that text is missing.
  A caller-supplied packet with different source text is rejected before a model call.
- Daily and single-paper pipelines save `paper_reading_inputs.jsonl` before invoking
  the Reader, including on a later reading failure. It records source identity, full
  text, warnings and section coverage. A context rejection also records the budget
  decision; completed Reader attempts carry their request estimate in existing records.
  It contains no credentials and adds no model call.

Complete extracted text is not visual PDF inspection or proof of semantic coverage.
Extraction can still lose table layout, figure labels, or text embedded in images.

New Reader evidence selects one literal `source_id` from prebounded blocks bound to the exact
URL and text; the program retrieves the original quote and location. The actual single-paper
schema enumerates the offered IDs once. Blocks follow existing section/numeric-row boundaries,
blank lines and line lengths. One block is at most 1,200 characters on one physical page,
with separate selections for discontinuous support. The model does not calculate endpoints
or character counts. Bracketed IDs and obsolete start/end selections are rejected, not repaired.
This is an evidence-span bound, never a full-input cap. The existing Verifier must still judge
entailment, table interpretation and experimental conditions. See the
[source-selection and named-material contract](chinese-publication-history.md#bounded-source-selections-and-named-method-materials-offline).

Offline checks against complete MemConflict and MemGuide sources preserve 116,752 and 74,344
characters, with 217 and 174 offered blocks. Their maximum block lengths are 1,200 and 1,199
characters. These counts describe the current extracted input, not measured model quality.
The existing Verifier still receives the complete source: selecting a real block establishes
provenance, not the truth of an assertion or the semantic role of a named material.

Every Reader request, including the existing JSON-repair attempt, is checked before the
cache/provider boundary. `model_providers.<provider>.reader_contexts.<exact-model>` must
declare positive integer `context_window_tokens`, `output_reserve_tokens` and
`overhead_reserve_tokens`. Reserves must leave room for input; an explicit provider
`max_tokens` cannot exceed the output reserve. Switching model does not inherit the old
model's capacity. Unknown capacity or an over-limit request stops the daily/paper run,
saves the failure and does not continue into Verifier, translation, or an empty report.

The current estimator counts UTF-8 bytes of the complete rendered messages as a
conservative input-token planning estimate, plus the declared output and overhead
reserves. It is **not an exact tokenizer measurement** or proof a remote service will
accept the request. Reserves cover framing, provider/CLI-added instructions and applicable
reasoning budget; declared capacities must come from the actual endpoint/model, not from
a successful short prompt. Underestimation of hidden overhead remains possible.

Old configurations without these declarations stop explicitly at Reader. The subsequent
[Chinese publication integration](chinese-publication.md) adds optional App JSON declarations
and Settings controls for exact-model budgets, without editing real configurations.
No model capacities are guessed or prepopulated; absence is still unknown.
Codex receives UTF-8 input through `codex exec -` stdin, not a large command argument;
its configured executable/arguments, sandbox, timeout and process-group behavior remain.
Full-input messages naturally have different cache keys from old excerpt messages;
identical complete requests still hit, and existing cache files are not changed/deleted.

## Complete-Input Offline Acceptance

Both saved full texts were passed through the production Reader and local evidence chain
with fixed historical responses, then repeated through the existing cache. MemConflict's
116,752 characters and MemGuide's 74,344 characters were present verbatim in outgoing
messages, including their previously omitted portions. The complete rendered input sizes
were 141,696 and 94,913 UTF-8 bytes, respectively, with the current instructions/index.
These are bytes, **not billed tokens**. Tests used explicitly synthetic capacity/reserve
declarations; they are not claims about GLM, Codex or DeepSeek limits.

Unknown/insufficient capacity produced zero Reader requests; oversized Codex Unicode input
was delivered unchanged to a local test executable through stdin. Production daily/paper
tests cover initial budget rejection and repair rejection after one malformed response:
the latter retains the preceding attempt and never claims the run made zero calls. The
existing Anthropic 4,096-token output setting also participates in the reserve check,
including through the cache, without changing its requested output limit.

Code verification: 1,435 Python tests passed; two existing opt-in frozen-engine tests remain
skipped. The private saved-two-paper acceptance passed two additional cases. Ruff, privacy
and diff checks passed. The original 31 saved files, App/bridge sources, unrelated pending
work, HEAD and Git index were retained. No live service, credential access or App build
was performed. Native full-input operation, endpoint acceptance, model reading quality
and real-process cancellation remain unverified by these offline results.

## Table Context

The shared extractor handles literal numeric row blocks, not arbitrary PDF tables.
It preserves a bounded set of exact header, row and caption/note source spans. A distant
quoted row can keep its header without concatenating the intervening table into a fake
continuous quotation. The original evidence quote is unchanged.

For regular single-header layouts with unique column labels and consistent numeric
cells, checks bind an explicitly named metric to its column. Column checks do not depend
on capitalization of the method name. Values present in another column of the same row
do not support the asserted metric. Clauses mixing multiple metric assertions are
ambiguous and must be split rather than bypassing validation.

One quotation cannot silently combine different pages, headers or model groups and
inherit the first header's column order. Same-table multiline quotations remain valid.
Cross-block bindings are rejected rather than inferred. Model/group labels and footnotes
are supplied as source context, not claimed as automatically validated semantic roles.

The previous literal-quote, method-row, numeric and source-identity checks still apply.
Irregular spacing, merged decimals, multi-level/duplicate headers, compound cells and
unclear layouts are not reconstructed. Ambiguity is reported; there is no table-specific
model retry, method whitelist or fallback service.

## Targeted Reader and Verifier Instructions

The Reader must distinguish missing input from paper-wide absence, preserve experimental
units/conditions and cite comparison headers plus both baseline and target rows. Supplied
prose/table/figure discrepancies must remain unresolved rather than selecting a preferred
number. Existing JSON structure and evidence requirements are unchanged.

The Verifier checks the entire assertion, including method/model, baseline, metric,
conditions, aggregation and outcome stage where relevant. Table extraction labels do
not mean semantic approval. Conflicting supplied evidence or insufficient comparison
context requires `needs_review`; author attribution is not a resolution of a conflict.
Existing status values, failure handling and non-promoting decision rules are reused.

The subsequent [structure/context/paragraph-review slice](reader-output-reliability.md)
supplies full source-addressed extracted texts and exact paragraphs in that same Verifier
call, subject to an explicit capacity check for its model. Reader evaluation conditions
are unverified proposals, not public facts. Only explicitly reviewed, still-bound paragraphs
may supplement the conservative claim fallback. This is not automatic cross-paper reasoning
or a guarantee of model accuracy; translation does not inherit paragraph approval.

## Earlier Bounded-Input Acceptance (Historical)

Saved MemConflict/MemGuide artifacts and fixed historical model responses provide the
before/after comparison. A source-backed checklist records newly present and still absent
passages; broader page coverage is not counted as better semantic reading. The new packet
can recover sample-size/limitations or construction restrictions while losing a passage
that the previous selection happened to include. These trade-offs remain explicit.

Synthetic layouts cover numbered and unnumbered headings, mixed sections on one page,
continuations, references/appendices, scarce budgets, captions above/below tables, distant
headers, model groups, swapped rows/columns, lowercase method labels and cross-block quotes.
Production-path tests check input persistence before Reader failure and review downgrades
through public composition.

Verification: 1,415 full Python tests passed, with two existing opt-in frozen-engine tests
skipped. Ruff, privacy and diff checks passed. The two code-review findings about lowercase
method/column bypass and cross-block header reuse were reproduced, fixed and independently
rechecked; the bounded independent set passed 98 tests. These counts describe code checks,
not research quality or new model acceptance.

Replaying a saved verifier decision proves only decision-handling behavior. A canned
reviewer in tests does not prove contradiction detection, and historically unreviewed
claims do not become independently verified during replay. Raw translation responses
were not retained in the historical run; normalized saved display fields are used for
that part of the comparison. Source reports and original audit outputs remain unchanged.

Before claiming better research quality, a separately authorized real run must check
whether the Reader uses the newly supplied material and whether the Verifier correctly
handles qualification and conflict. The full-input change described above supersedes the
historical excerpt selection, not these semantic quality limitations. No extra model
stage or automatic section processing is introduced.
