# Reader Output Reliability: Diagnosis and Conservative Fix

Status: unreleased shared Python contracts, with historical provider/Reader checkpoints below.
The saved LOTUS Chinese candidate completed real final review; the later plain-review context
and failure-attribution repairs are offline-only. See [current acceptance](#current-acceptance-and-limits),
[Chinese publication scope](chinese-publication.md) and
[dated LOTUS history](acceptance-history.md#lotus-v3-checkpoints-2026-11-06).
Hosted GLM constrained-output support remains unconfirmed. Installed packages are unchanged.

The subsequent [Reader-to-report quality audit](reader-chain-audit.md) checks fixed real
papers and saved responses across evidence, review, translation and composition. It identifies
both false acceptance and missing useful context; the conservative fallback below is a safety
boundary, not proof of a coherent or factually complete research synthesis.

## Bounded Fact Amendments Before Chinese Composition

The shared paper/daily paths permit one source-selected amendment per affected paper after
factual review and before Chinese writing. Only uncertain factual units required by the
method or evaluation-condition index are eligible. Explicit model refutations are not retried;
declined, unchanged or unresolved amendments cannot start a repair loop.

The Reader receives complete source text and explicit target/source IDs. It may clarify the
same assertion or select offered source blocks, not invent quotations, alter IDs or method
roles, add unrelated results, or choose a side of a source conflict. Strict parsing, local
source/table checks, independent fact/method decisions and final-language review remain required.
A locally reviewable table ambiguity is not an automatic approval.

Both structured and plain Verifier requests carry the prior assertion and its exact evidence,
bound to the current target. They share the instruction to preserve necessary qualifications
and comparison scope. Plain requests place this history before the unchanged full-source
context and include it in budget/cache identity. An exact repeat can still hit cache; a
different prior assertion cannot reuse the same plain-review response merely because the
new sentence is identical. No output format or evidence threshold is relaxed.

Reuse requires unchanged source hashes and exact target-bound receipts. Previously assembled
receipts are rebuilt from their constituent originals; merged approval lists are not trusted.
Changed assertions and dependencies require new independent decisions. Plain Verifiers cannot
reuse old target-bound approvals and review the complete eligible set.

`fact_revision.json` preserves initial claims/readings/decisions, source hashes, candidates,
local rejections and attempt status. Failed proposal/review attempts also record the actual
`stage/provider/model`. The shared failure route keeps progress, manifest and failure artifacts
consistent: Reader proposal failures are not labelled as Verifier calls, while a subsequent
Verifier failure remains a Verifier failure. Existing exception types and transport diagnostics
are retained. No new wire stage, command, provider, retry mechanism or configuration is added.

Extra work is at most one logical Reader amendment per affected paper, then the existing
possibly batched review of pending targets. Provider-level transport behavior still applies;
this is not an exact HTTP or monetary cap. Ordinary unamended requests keep their existing
input, and the same Chinese Writer and final review remain mandatory.

## Numeric Notation And Failure Diagnostics

Anchor checking recognizes literal spaced thousands, explicit percentage ranges and matching
metric cutoffs. A cutoff is part of a named metric, not evidence for a measured score.
Coordinated cutoffs require matching repeated annotations; aliases and citation/value pairs
are not guessed. Source identity and table row/column checks remain separate.

Localization compares exact count magnitudes, such as `5.5 million = 550万`, without sorting
quantities, changing recognized physical units or dropping signs/qualifiers. Decimal exponents
avoid float rounding. Exact source quotes and evidence bindings are not rewritten.

Reader evaluation-reference failures identify the dimension, reference index, bounded/redacted
claim ID/kind and evidence count. Failed-run persistence retains attached Reader attempts and
their existing bounded excerpts, not full reasoning or credentials. The original lost LOTUS
Reader answer is still unavailable; better diagnostics do not retrospectively recover it.

## Current Acceptance And Limits

The saved LOTUS Chinese candidate completed real final-language review on 2026-11-06:
56 facts and 15 unchanged paragraphs, five Codex `gpt-6-luna/xhigh` launches, about
12 minutes 8 seconds. Its 71 targets used the shared dynamic v4 evidence schema because no v5
comparison units were present. Existing Codex login was used; there was no direct
DeepSeek/NVIDIA HTTP request or API-key backend lookup. Backend requests, serving weights,
usage and cost remain unknown. This establishes saved-candidate acceptance, not a fresh Reader,
same-version normal CLI, packaged App or independent reproduction of the paper's results.

The two subsequent repairs to plain-review amendment context and failure attribution are
offline-only. Original Chinese candidates/reports remain unchanged; no live call or App update
is part of those repairs. Eight new positive/negative regressions cover exact prior evidence,
plain approval/refusal, cache separation and both production failure routes. Full Python:
2,533 passed, with two existing opt-in frozen-engine tests skipped. Ruff, privacy, links, diff
and scoped independent review passed. Prior checkpoints and their exact test totals are preserved in
[dated acceptance history](acceptance-history.md#lotus-v3-checkpoints-2026-11-06).

c35 remains outside public facts. Original PDF page 9 contains its four values, but the current
wrapped-label table parser cannot establish a complete grid and its linear fallback assigns
the following table caption to the quoted rows. The BioDEX method-row error is misleading.
Do not repair this by guessing columns or adding a dataset whitelist. The paper's broad
attributed superiority statement is also not proof of a win on every metric.

Methods and main experimental conditions are readable, but per-metric comparisons and some
mechanical wording remain limited. Keep source conflicts, missing evidence and deferred
VoiceOver/multi-display/accessibility/help-focus checks visible. Another identical paid run
is not the next acceptance step.

## Codex Reader Schema Integration (Offline)

A separately authorized v2 batch stopped on its first MemConflict Reader answer: the complete
answer ended with an extra `]}` after its JSON root. It used one Codex start, zero DeepSeek
HTTP requests and about 159 seconds. No fact review, Chinese writer, final review or MemGuide
run occurred; no final Chinese report passed. Read-only inspection also found string lists
where experimental observations required `{subject, value}` objects. The original answer
remains unchanged; extracting its prefix for diagnosis was not a repair or publication path.

The local CLI, inspected using an isolated credential-free `CODEX_HOME`, reports
`codex-cli 0.166.0-alpha.5.1`. Its `exec --help` documents `--output-schema <FILE>` for the
final response. This establishes a local interface, not remote model availability or
schema enforcement. Neither help/version invocation started a model or read the real login.

The shared Codex adapter now supports a scoped `complete_with_schema` request. The Reader
uses the existing complete single-paper schema; normal calls remain normal, so the constraint
does not leak into Verifier, writer, probe or knowledge-organization requests. The schema is
written to a private temporary file and passed as one argument, preserving command arguments
and full stdin input. Cached wrappers retain their counters and add a canonical schema digest
to the request identity; plain/facts-only/full-schema calls do not share a cache entry. Budget
checks include the schema without truncating paper input. No configuration field or dependency
is added, and existing caches are not deleted.

The full-root prompt example now includes a complete experimental record, object-valued
observations and a matching explicit claim ID. Its factual-only explanation shape is `{}`,
matching that schema variant instead of requiring empty arrays for nine explanation fields.
Placeholders remain invalid evidence. They must not be copied into public claims.

Complete JSON and the strict production Reader still validate returned content. The extra-root
suffix is rejected before caching; malformed experimental observations remain rejected by the
business parser. Constrained Reader validation failures stop without an automatic repair call.
There is no bracket deletion, string-to-observation inference, constraint-dropping fallback or
weakened evidence gate. Historical-file compatibility and other providers' defaults remain.

Offline tests cover request scoping, exact schema files, real subprocess stdin/argument delivery
through a local fixture, cache separation, schema rejection, the two saved failure patterns and
Verifier isolation. The stopped batch is not resumed. A future authorized acceptance must use
this shared constrained path in a fresh isolated directory rather than reuse its old custom
unconstrained launcher. Actual model-side enforcement and final Chinese quality remain pending.

Validation: 1,654 Python tests passed; the two existing opt-in frozen-engine tests stayed
skipped. The focused Codex schema suite covers 11 cases, including a real local subprocess
fixture, without executing Codex model work. Ruff/privacy/diff checks passed. This slice did
not read credentials, call services, update the App/package, or publish Git changes.

## Earlier Final Chinese Publication Integration

At this earlier checkpoint, the integration changed the order, not the evidence threshold:
complete English reading and local evidence gates, Chinese publication candidates, then
the existing single Verifier call on the exact Chinese claims and paragraphs against full
original sources. The request also carries the original analysis for translation checks.
English analysis is kept separately; its claims receive the final non-promoting decisions
without pretending that an English paragraph was reviewed. Decisions record the actual
reviewed claim text. Public Chinese paragraphs retain their exact-text, same-source bindings;
missing/rejected decisions still cannot publish them. Nothing rewrites reviewed body text
after that call.

Known missing/unusable paragraph translations or altered claim quantities now fail Chinese
localization. Originals remain available for audit, but are not silently substituted as a
successful Chinese report. Candidate readings/claims are saved before review so failed
attempts can be inspected without another model call. No language detector is claimed:
an apparently complete model translation can still be semantically wrong, and the real
Verifier must evaluate it.

Figures remain selected after final review from supported original claims. Chinese figure
captions use a separate localization chunk and cannot overwrite the reviewed body. This may
add one display-translation call when figures exist, not a second Verifier call. The next live
budget must include that cost explicitly.

The source App can round-trip exact-model capacity declarations through its existing JSON
configuration and edit them under **Full-paper reading limits**. Swift and Python reject
invalid reserves and noncanonical model keys. Missing capacities remain unknown; no model
limits are invented or copied to a different model, and no real settings are migrated here.
Reader capacity errors retain actionable codes rather than becoming generic research failures.

The two-paper offline comparison uses MemConflict/MemGuide full sources, historical records,
and explicitly human-curated Chinese candidates and reviewer fixtures. It demonstrates that
coherent final-language paragraphs can survive the production pipeline, while omitted,
invalid or rejected material stays blocked. It includes experimental units, aggregation,
measurement stages and source contradictions. It is **not** a fresh Reader/Verifier result
or measured automatic quality improvement. The native report decoder reads the generated
draft, and actual Swift-encoded limits load through the strict Python converter. Installed
Apps, packages, real configuration and original reports remain unchanged. See
[current scope and comparison](chinese-publication.md).

The sections below retain earlier diagnosis/checkpoint history. Their statements about
unreviewed translated prose falling back describe the previous ordering, not the integrated
final-language path above. Hosted GLM schema enforcement and real model accuracy remain open.

## Three Different Contracts

| Boundary | Required result | What is currently established |
| --- | --- | --- |
| Provider / streaming | Complete final-answer text with an accepted termination | The last saved GLM request completed transport with `stop`; this does not prove valid JSON. |
| Reader parser | Valid JSON with the accepted reader structure | Both saved syntax-error patterns remain rejected without reconstruction. |
| Public explanation | Public text needs its own decision and valid source-bound support | Specifically reviewed paragraphs can be retained; everything else uses verified-claim fallbacks. Valid IDs alone still cannot approve prose. |

Sending a better example in a prompt is an instruction, not constrained decoding. Likewise,
an existing claim ID is a reference, not proof that its text entails the referencing paragraph.
Neither a normal `stop` nor valid JSON can establish scientific validity.

## Reproductions

An earlier separately authorized, single GLM request completed in about 438 seconds but failed
JSON parsing. The answer split `reader_explanation` fields into separate object fragments and
closed its reading array before closing the reading object. It never became an accepted reading
or public report. No bracket repair or partial-reading publication was used.

The test fixture `reader_fragmented_explanation.txt` keeps this structural pattern with synthetic
text; the earlier missing-object-close fixture remains unchanged. Tests cover strict reader
rejection, the valid neighboring form, and the daily failure path with no verifier call. SSE
replay with one-byte and larger chunks preserves both invalid answers exactly before reader
rejection. This checks the decoder implementation; original raw SSE was not retained, so it is
not an independent reconstruction of the historical wire exchange.

The separate support-ID reproduction uses a **valid synthetic reading**, not a repaired live
answer: approved claims describe an experiment, while a background paragraph about competing
systems points to their real IDs. Before the repair, the gate retained that paragraph. The same
behavior appeared in daily Markdown, WeChat HTML and the single-paper brief. Missing IDs or a rejected
supporting claim are already blocked; this defect concerns **valid but irrelevant** references.

The four initially expected-failure cases covered the public gate and three publication surfaces;
running them with `--runxfail` reproduced four assertion failures before implementation. They are
now ordinary regressions, without expected-failure markers, and pass. Positive controls retain
verified claim text, not the eligibility of an unverified explanation. Existing paper-identity
checks are not replaced by these tests.

Earlier offline pipeline coverage checked daily/public draft and single-paper output while the original
explanation text and supporting IDs remain in `readings.jsonl`. Public rendering does not mutate
the reading object. No unreviewed explanation is copied into `ArticleDraft`, no extra model call is added,
and rejected claims are not used as fallbacks. Localized claims use the same public gate; their
source evidence remains unchanged. Existing report artifacts are not rewritten.

Verification at that earlier checkpoint: 1,328 Python tests passed, two existing opt-in frozen-engine tests
remain skipped, and there are no expected failures. Ruff, privacy and diff checks are also run
for this slice. All 19 checked saved input/result files remain unchanged. This is offline
validation, not a new model-quality or installed-App acceptance.

## NVIDIA Documentation: Support Is Not Confirmed for This Endpoint

Reviewed public official pages only; no model request, credential lookup or authenticated probe:

- The [GLM-5.3-Flash build page](https://build.nvidia.com/z-ai/glm-5-3-flash) identifies
  `z-ai/glm-5.3-flash` and the hosted OpenAI-compatible endpoint.
- Its [dedicated inference reference](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)
  documents streaming and ordinary sampling fields, but does not list `response_format`,
  `json_schema` or `guided_json`. This omission is **not proof of rejection**, but it provides
  no endpoint-specific guarantee of constrained JSON support.
- The versioned [NIM 1.14 structured-generation guide](https://docs.nvidia.com/nim/large-language-models/1.14.0/structured-generation.html)
  describes schema-guided generation for NIM deployments. Its examples use a local server and
  another model. It distinguishes JSON-object mode from schema enforcement. These container
  capabilities cannot be assumed for every NVIDIA-hosted model.
- [NIM container variants](https://docs.nvidia.com/nim/large-language-models/1.15.0/nim-container-variants.html)
  document backend-dependent parameter differences. Do not blindly copy one version's
  `guided_json` or `nvext` example into this hosted request.

Conclusion: **general NIM capability is documented; this hosted GLM endpoint's support remains
unconfirmed**. No live parameter test was authorized in this slice. OpenAI compatibility alone
does not establish support for all OpenAI request fields. JSON mode, if available, would not
prove schema adherence or paragraph-to-claim support.

## Current Offline Slice: Structure, Context and Paragraph Decisions

The later saved MemGuide full-input response completed transport in about 562 seconds with
`stop` and valid JSON, but returned two readings for one paper. The second was an appendix
continuation. The production parser still rejects it; it is not merged or repaired into a
usable reading. The saved answer also contains cross-backbone generalizations contradicted
by individual rows and prose/figure disagreements. These are semantic issues, not JSON syntax.

### Reader and Request Boundary

`paper_reading_response_schema()` prepares the canonical single-paper JSON Schema: exactly
one reading, typed analysis/paragraph fields and source-anchored evaluation conditions.
The OpenAI-compatible provider accepts an explicit `response_schema` only on a separately
constructed, dedicated Reader instance. It defaults to absent, is included in the context
estimate and cache identity, and cannot silently fall back after an unsupported-parameter
error. A schema-bound Reader instance is rejected if reused for a Verifier request.

This is preparation, not a capability claim: normal routing/configuration does not enable
the schema, and NVIDIA support has not been established. Do not reuse a schema-bound
instance for localization or other tasks. The model-call cache stores transport answers,
not validated Reader objects; parsing and evidence checks still run before use, including
on cache hits. A schema request cannot make an invalid singleton answer publishable.

### Experimental Context and One Verifier Call

Reader `evaluation_context` has three optional lists: `data_construction`, `available_inputs`
and `outcome_measurement`. Each item has text and source evidence. Older records leave these
unknown; the entries are unverified proposals, never additional public claims.

Daily and single-paper production paths pass full source-addressed extracted texts, their
hashes, these proposals, eligible claims and exact explanation paragraphs into the existing
Verifier call. This adds no review round, search or automatic split. The original local
evidence/table gates still apply. Full text makes distant exclusions and counterexamples
available; it does not recover unreadable PDF figures or infer missing table cells.

This larger request must fit the Verifier model's explicit `reader_contexts` declaration
(the existing configuration name is retained). Unknown/insufficient capacity stops before
cache/provider access; it does not silently send excerpts. The output reserve must cover
claim and paragraph decisions. This can cost more tokens, even though call count is unchanged.

### Public Prose

The Verifier returns `explanation_decisions` alongside claim decisions, using request-local
paragraph IDs. Paragraph approval is bound to exact text, supporting IDs, source URL and
the reviewed supporting claims. All references must resolve uniquely within that paper,
and all supporting claims must remain publishable with explicit supported model decisions.
Reader-supplied approval is ignored. Duplicate claim decisions cannot approve a dependent
paragraph; missing/invalid/duplicate paragraph decisions fail closed.

Composition rechecks the binding. Changed prose, source, support or downgraded claims
invalidate it. The containing reading must still identify the approval's paper; single-paper
claim fallbacks are source-scoped too when that identity is available. Unapproved sections
use existing verified-claim fallbacks; originals and
decisions remain in audit readings. Translation does not inherit English paragraph approval:
changed Chinese paragraphs remain on the conservative fallback path in this slice. No
second verifier call or automatic rewrite is added. Coherent, semantically reviewed Chinese
paragraphs remain a separate acceptance/design question.

### What Offline Acceptance Establishes

Positive and negative tests cover production daily/single-paper outputs, source/ID isolation,
missing/duplicate decisions, stale approval, translation and budget stops. The saved two-paper
replay supplies complete MemConflict/MemGuide texts with previously verified claims and explicit
fixture paragraph decisions. It proves request delivery and publication handling, not that a
real Verifier can detect the MemGuide counterexamples. The real invalid two-reading answer is
still rejected, and original reports/results are preserved.

No live request, credential lookup, App change, package update or delivery is part of this
slice. Hosted schema enforcement, real paragraph-review accuracy, token/latency cost and
Chinese explanatory quality remain unverified. More prose retained is not itself a quality score.

Offline closeout: 1,474 Python tests passed, with two existing opt-in frozen-engine tests
skipped. The private saved-two-paper replay passed two additional cases. Ruff, privacy and
diff checks passed. Read-only review found a changed-paper approval bug; its regression was
reproduced, fixed and independently rechecked. The original 47 protected
input/result/report files and unrelated pending edits are preserved. No App/Swift acceptance
is claimed for this Python-only slice.
