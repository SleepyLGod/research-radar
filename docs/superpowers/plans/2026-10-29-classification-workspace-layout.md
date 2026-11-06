# Classification Workspace Layout

This records the initial layout checkpoint. The subsequent
[partitioned workspace slice](2026-10-29-partitioned-classification-workspace.md) replaces its
connector rendering and fixes the remaining empty-state layout; retain this earlier evidence as history.

## Scope

Refine the existing native classification workspace, not the knowledge contract or research.
Keep all previous uncommitted work, Apps, reports and real configuration. No live services,
credential reads, sends, stage, commit or push.

## Display changes

- Two normal toolbar rows: topic/organization/refresh, then view/facet/keywords/search.
  Align controls and canvas to the same 20-point content margin. Hide redundant persistent
  captions; keep snapshot counts/date and facet definitions in an explicit information popover.
- Keep pending/running/stop/error notices and the existing cost confirmation. No changed
  admission, cancellation, snapshot, filtering or sending behavior.
- Give group and paper columns the same header height and spacing. Put the group icon beside
  its title, give counts a unit, and reduce paper title weight without changing its identity.
- Use solid shared-stem classification connectors with distinct lanes. Derive every branch
  from visible stored membership and current node bounds; unclassified papers have no line.
  No new relation inference, colors as quality scores, animations, graph engine or dependencies.
- Paper/detail/ledger navigation and topic-scoped selection remain the existing implementation.

## Verification

- [x] Add and run failing connector-geometry tests, then implement the small display-only layout.
- [x] Add an offline fixture with several facets/groups, overlapping membership, an unclassified
  paper and long English/Chinese titles; verify filtering does not invent or duplicate nodes.
- [x] Inspect native layouts and controls in both languages/appearances at normal and narrow
  workspace sizes, using a separate signed QA App and blocked service/secret boundaries.
- [x] Preserve original report/snapshot bytes. Run appropriate Swift/Python, Ruff, privacy, bundle,
  signature and whitespace checks; review this slice without sending code to external services.
- [x] Record observed results and remaining manual checks, provide screenshots/candidate, stop.

Only App views/layout, their tests/localization and this acceptance documentation are in scope.
Do not reuse test-only layout classifications as a claim about real research quality.

## Recorded results (2026-10-29)

- Normal state now uses two toolbar rows. Topic, mode selector and graph share the same
  leading edge; group and paper nodes share a top edge. Saved counts/date and facet definitions
  moved into on-demand information, without hiding running/error notices or the stop action.
- Six synthetic papers cover two facets, five groups, overlapping membership, an unclassified
  paper and long English/Chinese titles. Native hosted workspace captures were explicitly run
  for both languages and appearances at 640- and 720-point content widths. These are layout
  checks, not model-quality evidence or full popover acceptance in every combination.
- A separate locally signed, read-only QA App exercised the Chinese/light native popover:
  measured toolbar/node alignment, switching facets, selecting/clearing a group with no matching
  results, retaining its search text, opening an unclassified paper's saved keyword evidence and
  returning to the graph. It admitted zero jobs; its engine accepted only local snapshot/ledger
  reads. No model, service, credential-value access or delivery was used.
- Read-only review found two display regressions, both corrected: history must keep active
  organization controls/notices, and an empty paper result must not hide the selected-group
  clear action. The history regression test was observed failing before the fix, then passing;
  the empty-result case was reproduced and rechecked in the native QA App.
- Full Swift regression: 377 tests passed. Full Python regression passed with two existing
  opt-in skips. Ruff, privacy scan and whitespace checks passed. Static QA bundle checks covered
  signatures, contained symlinks, Mach-O dependencies and private paths in native code/resources.
  The QA bundle deliberately contains its isolated test root; it is not a distributable package.
- Protected Python/Core sources and previous App executables remained byte-identical; saved
  fixture reports/snapshots were unchanged. Re-signed helper code digests matched the previous
  candidate, and no QA App/helper process remained after exit. No new resource benchmark is claimed.

### Still pending

Physical keyboard focus and clearing input, long-list mouse-wheel behavior/scroll-position
restoration, information-popover dismissal, VoiceOver and multiple displays still need manual
acceptance. Native automation encountered input/timing and transient capture limitations; a
successful hosted layout or AX action is not proof that those interactions passed. Automatic
classification quality, incremental organization and relation/structure views remain outside
this display-only slice. Existing Apps, real configuration and Release artifacts were not updated.
