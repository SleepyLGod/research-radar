# Reader-to-Report Offline Quality Audit

This is the historical offline baseline, not the current acceptance status. Later shared
fact/write/final results and remaining limits are summarized in [Chinese publication](chinese-publication.md).

Status: unreleased source review, 2026-10-30. This is not a new model run,
experimental reproduction, installed-App acceptance or release-quality approval.

This is the audit checkpoint, not a claim that all findings remain unfixed. The subsequent
[bounded-input and table-evidence slice](reader-input-evidence.md) records source repairs,
offline coverage trade-offs and what still needs a new model-quality acceptance.

## Conclusion

The current chain produces useful, traceable research notes, but the reviewed reports
are not yet sufficiently reliable or coherent to replace reading the papers.
Stricter code prevents several publication errors; it does not establish that an
otherwise valid verifier decision is factually correct.

Two fixed papers were checked against their complete saved PDFs:

- *MemConflict: Evaluating Long-Term Memory Systems Under Memory Conflicts*, v1,
  33 pages, 46 original claim units.
- *MemGuide: Intent-Driven Memory Selection for Goal-Oriented Multi-Session LLM Agents*,
  v2, 19 pages, 58 original claim units.

The historical route was DeepSeek `deepseek-flash` reading, Codex `gpt-5.6-luna`
verification, and DeepSeek localization. Findings do not establish the quality of
current GPT, GLM or other model routes.

## What Was Replayed

Production reading, anchor resolution/repair, rule-based review, verifier decisions,
localization and public composition were exercised with saved responses. There were
no new discovery, model, credential or delivery requests.

Reader and anchor-repair replies came from original cached responses. Verifier
decisions were reused only for identical English claims with matching paper URL and
claim ID. Newly eligible claims lacking historical decisions stayed unverified.
Original translation responses were unavailable; the localization replay reconstructed
consumed fields from saved normalized readings and draft text. This limitation prevents
claiming a byte-exact reconstruction of the historical translation exchange.

The comparison distinguishes the original report, the worktree before this audit,
and the source after this audit. Earlier pending Reader and public-content changes
are not attributed to this slice. Historical reports were not rewritten.

## Confirmed Code Repairs

### Translation quantities and record alignment

- Spaced signs, such as `- 5%`, no longer lose their sign during comparison.
- Storage units through PB/EB and larger standard magnitudes, common word scales,
  opaque uppercase units and compound-unit denominators remain distinguishable.
- Lexical `top-3` is treated as a Top-K count, not negative three. True negative
  numbers, changed bounds, units and counts still fail the existing guard.
- Quantity checks also cover structured reading text and aligned list items,
  rather than only public claim copies and explanation paragraphs. Changed list
  lengths retain original text with a finding instead of guessing correspondence.
- Translation indices must be exact integers, unique, nonnegative and cover the
  reading/claim items requested by that chunk. Invalid or missing index coverage
  fails the chunk and retains originals. Daily-path regressions confirm that failed
  Chinese localization does not produce a public Chinese article.
- Missing explanation translations preserve the original paragraph for audit;
  changed supporting IDs remain rejected. This does not approve raw reader prose
  for publication.

These are conservative checks, not a semantic translation verifier. Matching numbers
cannot establish preserved entities, attribution, conditions, negation or causal
meaning. Unrecognized lowercase units are not comprehensively parsed. Ordered
quantity comparison can reject harmless reordering; changing it to an unordered
bag would also permit swapping two methods' results, so that limitation remains.

### Invalid verifier indices

Unicode digit-like strings and oversized integer strings no longer raise an uncaught
conversion error. Invalid indices follow ordinary invalid/missing-decision handling
and cannot turn an unreviewed claim into a supported one.

### Appendix recognition

Standalone named appendix headings, including `Appendix A`, `APPENDIX A` and lower-case
variants, now end reference-continuation state. Previously, actual appendix pages
could remain classified as references and be excluded from the reading packet.
Ordinary references to an appendix inside prose do not end reference state.

Prompt instructions, character budget and ranking policy were not changed. Correct
appendix recognition can change future selected source text and therefore the full
rendered prompt hash. Replaying a saved response is not a live test of that new input.

## Content Problems That Code Repairs Do Not Solve

### Source-backed but disputed results still appear

MemGuide claims c42/c43 repeat the ablation prose on physical PDF page 7: Qwen JGA
from 0.74 to 0.41 and GPT-4o-mini DTE from 3.19 to 4.30. Figure 4 on that page instead
shows Qwen 0.66 versus 0.41, and GPT-4o-mini DTE 3.19 versus 3.54. The plotted 0.74 is
associated with Mistral. The page was rendered and visually checked, not interpreted
only from flattened figure text.

The discrepancy originates in the source; Reader and Verifier did not resolve or flag
it. The saved supported decisions remain supported during replay. No paper-specific
code silently replaces them with whichever number appears preferable.

MemGuide's reported 99% task success also needs its outcome boundary: Table 10 on
physical page 12 describes final success after proactive clarification. It is not
99% first-pass memory correctness. Adapted baselines and mixed outcomes further
limit blanket superiority claims.

### Missing source coverage is not necessarily a reader failure

Before the appendix repair, reconstruction with the current 24,000-character packet
builder omitted important parts of the complete saved papers. MemConflict's actual
limitations, 12-instance evaluation scale and macro-averaging rule were not selected.
MemGuide's clarification boundary and task-goal prompt details were outside the
selected material. Some selected pages were also prefix-truncated before relevant
subsections. Current reconstruction is not proof of the original historical prompt.

The appendix fix restores eligibility, not guaranteed inclusion under a finite budget.
For MemGuide, reconstructed selection now includes pages 11/12 and the clarification
boundary, but page 5's scoring/supervision details are no longer selected. MemConflict's
selection is unchanged. This observed trade-off is not a complete coverage fix.
Coverage warnings currently describe broad section roles, not complete retained
content. A separate packet-coverage improvement needs explicit design and tests; this
audit does not claim the default packet contains the entire paper.

### Conservative table guards also reject useful material

Six historically supported claims are excluded by the current table-row checks.
Some metric/model labels are treated as method entities; other saved quotations omit
baseline rows or model-group context needed to bind a comparison. Missing quoted
context is not factual refutation, but finding the same numbers somewhere in the
table is not sufficient support either. No whitelist or general weakening was added.

Three newly eligible MemGuide items have no saved verifier decisions. They remain
unverified, including the reader's useful observation that Table 6 and prose disagree
on 5.05 versus 5.09. Improving eligibility cannot manufacture an independent decision.

## Readability and Measured Dispositions

The historical report contained 85 public claims. Fixed-response replay before and
after this audit contains 79; this is a disposition count, not a quality score.
Current records total 121: 104 original claim units plus 17 separately retained
rejected audit records. Those rejected records are not additional public facts.

The earlier conservative public gate removes all 33 unapproved explanation paragraphs
from public output and uses six claim-derived sections per paper. It closes a real
publication path, but loses narrative continuity and does not repair wrong supported
atomic claims. Methods remain identifiable; experimental scope, substantive limitations
and some caveats are still incomplete. Original prose remains available for review.

The smallest useful next quality step is a fixed source-backed acceptance set covering
method inputs/outputs, evaluation units, baselines, outcome stages and contradictory
results. Evaluate omission and false acceptance together. If fluent explanations are
restored, their own support needs explicit checking, not just membership of referenced
claim IDs. This is separate from transport, JSON validity and deterministic guards.

## Verification and Limits

Offline regressions cover production daily/public failure paths as well as helper
boundaries. Full Python tests block network and system credential access; two existing
opt-in frozen-engine tests remain excluded. Verification: 1,386 tests passed and two
were skipped; the focused set passed 111 tests. Ruff, privacy and diff checks passed.
Independent read-only review reproduced and checked the boundary fixes without an
external review service. It does not replace a new semantic evaluation of model answers.
The private comparison retains claim-by-claim dispositions, source locations, original
and regenerated reports, and integrity checks; raw acceptance data is not included here.

No App, package, prompt instruction, model route, normal configuration or historical
report was changed. No new semantic decision was invented. Manual App acceptance,
new model-quality acceptance and release publication are outside this audit.
