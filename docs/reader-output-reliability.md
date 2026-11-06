# Reader Output Reliability: Diagnosis and Conservative Fix

Status: historical diagnosis and offline checkpoints, starting 2026-10-30. The unreleased
source now includes scoped Codex schemas and two-stage Chinese publication review. The
latest saved-material pair completed real fact/write/final acceptance; see
[current contracts, quality and limits](chinese-publication.md). The statements below about
pending runs and test totals describe their dated checkpoints, not the latest outcome.
Hosted GLM constrained-output support remains unconfirmed. Installed packages are unchanged.

The subsequent [Reader-to-report quality audit](reader-chain-audit.md) checks fixed real
papers and saved responses across evidence, review, translation and composition. It identifies
both false acceptance and missing useful context; the conservative fallback below is a safety
boundary, not proof of a coherent or factually complete research synthesis.

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
