# Native Research Overview: First Product Slice

Historical slice record: its original no-commit stop point is retained below. The subsequent
[authorized closeout](2026-10-26-native-reading-polish.md#authorized-closeout) governs source
commits and Draft review; it does not imply a released package or completed physical acceptance.

## Scope

Bring the approved product prototype's home and coarse research phases into the native macOS
popover. This is an unreleased App presentation change, not a new research pipeline or a project
TODO dashboard. The published beta and existing development App are unchanged.

## Responsibility Boundaries

| Layer | This slice |
| --- | --- |
| Shared Python research | Unchanged: selection, reading, verifier, evidence policy and public content |
| Engine protocol and workflow | Unchanged: commands, events, serialized queue, cancellation, recovery and delivery |
| App presentation model | Derive a read-only phase snapshot and report placement from existing topic-scoped state |
| Native views | Show the research focus, report summary, actual phase, schedule and existing actions |

`ResearchProgressPresentation` uses the existing `TodayPresentation`. It is not another persisted
state machine. `ResearchProgressView` renders that snapshot; the homepage continues to invoke the
existing AppStore actions. No background polling, dependencies, browser runtime or model calls
are added.

## Display Contract

- The selected topic supplies the research focus. Existing report text stays a report summary,
  not a newly generated research judgment.
- A current effective report comes first when there is no newer active, failed or empty attempt.
  Research in progress, cancellation, failure and an empty result take precedence otherwise;
  the previous effective report remains independently readable.
- Report counts belong to that report, including when it is retained below a new attempt.
  Missing reports do not produce placeholder zero counts.
- Four phases use existing typed stage mappings: discover, read, verify and compose. Only the
  currently recorded phase is highlighted. No previous-stage completion, per-paper count,
  percentage or execution history is inferred from an ordinal phase.
- A queued job has no highlighted phase. Missing or unreliable legacy phase information remains
  unspecified rather than defaulting to discovery.
- Delivery attention stays with the corresponding report/channel. It does not turn the research
  phase strip into a research failure.
- Compact/full mode, topic/report selection, appearance, localization, configuration checks,
  rerun confirmation and safe report reading continue to use existing behavior.
- Production views contain no simulation controls, fixed paper names or manual prototype
  judgments.

## Verification And Acceptance

- Focused tests protect phase uncertainty, queued/cancelling/stopped state, topic scoping,
  independent delivery attention, retained report counts and report-first placement.
- A read-only review identified a delivery-only warning leaking into the research headline. A
  failing view-facing regression test reproduced it before the headline was corrected.
- Native UI fixtures exercise production popover/views with fake credential presence and no
  engine. Their screenshots are presentation evidence, not live research/cancellation evidence.
- A separate candidate App reuses the existing frozen engine, helpers and local signing identity.
  Bundle dependency, symlink, private-path and signature checks must pass. The old development
  App is retained; the candidate does not install over it.
- Existing offline report artifacts are fingerprinted before/after visual checks; this slice does
  not rerender or modify them. No real providers, search, credentials, uploads or delivery are used.
- Final visual and interaction results are recorded in the current TODO after verification.
  User acceptance of the new look remains separate from automated and fixture checks.

### Current Results

- Full Python regression passed; the final Swift run passed 290 tests across 50 suites. Existing
  opt-in service/system checks are not converted into live acceptance by these runs.
- Ruff, privacy scan, localization-file validation and diff checks passed.
- The separate candidate passed bundle verification and strict nested signature verification;
  its signing requirement matches the existing development App, which was not overwritten.
- Final native fixtures produced 32 bilingual light/dark home captures and 24 outcome captures.
  Representative compact/full, running, failed, empty and retained-report states were inspected.
  Existing offline report artifacts remained byte-for-byte unchanged and test Apps exited.
- Automated navigation stopped before button traversal because the test driver could not identify
  the expand control. Do not label navigation, real cancellation, cross-application focus or
  live startup accepted. Fresh manual interaction and visual acceptance are still pending.
- The read-only review's delivery-headline finding was fixed with a RED-to-GREEN regression.
  No outstanding validated finding remains in this slice; that is not a claim of exhaustive audit.

## Not In This Slice

Native paper cards and evidence views need a safe projection of existing `ArticleDraft` content.
Per-paper progress needs structured event forwarding before the App can display it. Automatic
question-oriented synthesis needs content-quality work. Persistent question records and
evidence-backed relations need their own data contracts; a manual version need not wait for
automatic synthesis. None of those are implemented or implied by the new homepage.

## Stop Point

Deliver the candidate and representative native screenshots for visual review. Keep all changes
unstaged and uncommitted; no push, release update or merge. Do not continue to paper cards,
graphs or new research capabilities in this slice.
