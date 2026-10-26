# Native Paper Reading

Historical slice record: its original no-commit stop point is retained below. The subsequent
[authorized closeout](2026-10-26-native-reading-polish.md#authorized-closeout) governs source
commits and Draft review; it does not imply a released package or completed physical acceptance.

## Scope

After generating a report, show its existing deep-read papers as previews before opening an individual paper. Keep the dated report list and an explicit full-report action. This is not source selection before research, a cross-day paper library, or a knowledge graph.

## Boundaries

- Read only the public projection in the existing `article_draft.json`: deep-read entries, their filtered explanations, public claims and evidence, and separately listed additional sources.
- Reuse the descriptor-based report resource boundary for JSON and local images. Never read raw readings, root claim audit metadata, or remote resources.
- Keep models and decoding separate from native views. Do not add an engine command, provider call, database, dependency, or evidence policy. Native images retain the existing exclusion of legacy full-page PDF screenshots.
- Opening a report defaults to paper previews. Paper detail and full HTML have explicit back navigation. Preserve report and paper selection across popover hiding and compact/full transitions; reset when changing reports.
- Keep report-level delivery and existing confirmation/protection rules. Do not add per-paper delivery.
- Legacy, missing or invalid structured data must show a clear fallback to the existing full report, not invent paper content.

## Checks

1. Test the public projection, topic isolation, missing/invalid JSON, unsafe links, symlink/path rejection, and distinct paper selection.
2. Implement previews, native sectioned detail, original evidence disclosure, and safe local figures. Load the full HTML reader only on explicit request while visible.
3. Verify native navigation, scrolling, selection retention, bilingual layout, and reader release using isolated offline data. Compare source artifact hashes before/after.
4. Run Swift/Python regression, Ruff, privacy, bundle/signature and diff checks; perform a read-only code review.

## Stop

Deliver a separate candidate App, screenshots and bounded acceptance notes. Preserve previous Apps and real configuration. No live service, credential reads, upload/send, staging, commit, push or Release changes.

## Layer And Capability Map

| Capability | Existing foundation | This candidate | Later work |
| --- | --- | --- | --- |
| Several deep-read papers in one report | Public draft entries already exist | Preview cards, select a paper, native sections and evidence | No new research stage needed |
| Additional discovered sources | Source title, gist and link already exist | Separate lightweight list; never labeled verified deep reads | Research-before-run source selection is outside this slice |
| Reports on several dates | Topic-scoped report index already exists | Keep the dated report list and return navigation | No claim of paper-level accumulation |
| Same paper across several days | History stores discovery/outcome facts, not a browsable knowledge model | Not implemented | Needs a durable paper identity/index and provenance-preserving updates |
| Cross-paper relations and evolving research judgments | No verified relation or synthesis contract | Not implemented; no dummy graph buttons | Define evidence-backed relations and incremental synthesis before adding a graph |
| Per-paper live progress | Existing events expose coarse pipeline stages | No fabricated per-paper progress | Requires a separate event/data contract |

## Candidate Acceptance (2026-10-26)

- Added a bounded, descriptor-rooted public draft loader and a small report browsing model. Unknown audit fields are not decoded or displayed. Topic mismatch, malformed JSON, unsafe links and symlink/path escapes fail closed, with an explicit full-report fallback.
- Native previews use only existing filtered paper entries. Detail has background, method, experiments, limitations and original evidence where those fields exist; absent sections are omitted. Local raster thumbnails load only on paper display, including PNG/JPEG/GIF/WebP; missing or unsafe images and their captions are omitted together. Existing public page-screenshot exclusion remains in force.
- A read-only review found and resolved blank-string fallbacks, legacy page screenshots and raster-format omissions. Regression also checks thumbnail bounds and malformed raster rejection. No further actionable production finding was reported; rapid hide/remount during figure loading remains a stress-test gap.
- Full Python regression, full Swift regression (313 tests in 55 suites), focused image tests, Ruff, privacy and diff checks passed. Bundle and deep/strict signing checks passed using the existing identity and unchanged frozen engine. No live service acceptance is inferred from these tests.
- The real isolated native popover was exercised in both UI languages and appearances. Local input opened both actual paper entries, scrolled detail, returned to previews, dismissed with Escape, restored the selected paper, explicitly opened full HTML and returned with WebKit released. Four sets of owned system-window screenshots were inspected. No new jobs were started and credential-value reads stayed at zero.
- All 31 original report artifacts and all 31 isolated copies stayed byte-identical. This fixture has no paper figures; image-format/bounds acceptance used generated offline raster fixtures, not a live paper-image run.
- The separate signed candidate is about 49.3 MiB allocated on this machine, about 0.6 MiB larger than the retained development App. This is not a new idle-RSS baseline: the private acceptance host includes test polling and screenshot instrumentation.
- Physical mouse/trackpad, VoiceOver and multi-screen behavior are not newly accepted here. A synthetic status-item close click was unreliable in one pass; Escape and controlled reopen passed. No production workaround was added for an unconfirmed physical-input bug.
- The old development App, true configuration, published beta, renderer artifacts and research pipeline are unchanged. No commit, push or Release update was made.
