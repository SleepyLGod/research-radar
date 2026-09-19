# Offline Frozen Verification

This fixture is synthetic test input, not a research result. It is packaged only
by `packaging/macos/research-radar-offline-test.spec`. The production entrypoint,
spec and app assembly do not import or stage it.

## Boundaries

- Real: bridge protocol/runner, production configuration loader and handlers,
  daily application service, discovery orchestration, local PDF ingestion,
  native PDF helper, reading/verification parsers, evidence gates, ArticleDraft,
  report renderers, delivery application services, MIME construction and journals.
- Injected: one discovery connector returning a synthetic local PDF, fixed model
  responses, in-memory secrets, WeChat remote client and SMTP transport.
- The entry installs a Python audit hook denying socket connections, DNS and
  network sends. Child execution is restricted to the explicitly supplied PDF
  helper. It tests its socket guard before dispatch. This is an accidental-IO
  guard for this controlled test executable, not an OS sandbox for hostile code.
- WeChat throws `PublishError` after preparing publish HTML. The Python bridge
  reports `delivery_failed`; the native resolver conservatively records unknown
  delivery outcome. Email must still complete through the fake transport.
- The reader fixture follows `tests/test_pipeline_fake.py`'s complete-reading
  structure. It does not write a draft or HTML. The PDF contains original CC0
  synthetic figure content which the native helper must actually rasterize.

## Run

From the repository root, with dependencies already installed (no network sync):

```sh
.venv/bin/python script/verify_offline_frozen.py --build \
  --output-root /private/tmp/radar-offline-fresh \
  --pdf-helper /absolute/path/to/ResearchRadarPDFHelper \
  --production-engine /absolute/path/to/production/research-radar-engine
```

Use a fresh output directory. Nothing is deleted. To reuse a frozen build, replace
`--build` with `--engine /absolute/path/to/research-radar-offline-test` and still
use a fresh output directory. PyInstaller runs via `.venv/bin/python`, never `uv`
or a dependency download. RSS sampling requires permission to run `/bin/ps`.

The script verifies renderer byte equality after loading the full ArticleDraft,
safe nonblank figure pixels, preserved report hashes across independent engine
processes, isolated channel outcomes and a separate non-live production preflight.
It writes `verification.json` with elapsed time and sampled engine-only peak RSS.
It does not claim App queue, index or GUI validation.

`FrozenDailyWorkflowTests` is the separate opt-in native test. Set
`RESEARCH_RADAR_OFFLINE_ENGINE`, `RESEARCH_RADAR_OFFLINE_PDF_HELPER` and optionally
`RESEARCH_RADAR_OFFLINE_ARTIFACTS`, then let the controller run that Swift test
filter. It uses the production AppStore/supervisor and startup loader, retains
its diagnostics and checks report/index persistence. It creates no fake report
or index. Normal Swift/Python suites skip their opt-in frozen integration tests.
For actual staged native App scheduling/restart acceptance, use the test-only
`ResearchRadarOfflineEngine.app` produced beside the collection:

```sh
.venv/bin/python script/verify_offline_app.py \
  --production-app dist/ResearchRadar.app \
  --offline-engine-app <BUILD_OUTPUT>/dist/ResearchRadarOfflineEngine.app \
  --configuration <NATIVE_TEST_ROOT>/config/app-config.json \
  --output-root .build/offline-app-fresh
```

This copies and signs a separate test App, launches it with an isolated development
root, and validates its scheduled queue and restart. It does not modify the
production App or use real delivery clients. A native window is launched, but
this is not automated interaction coverage of every UI control.

The bridge currently accepts today's report date only. The verifier checks that
the returned report and actual manifest agree; it does not claim historical
catch-up support or solve the midnight race between date check and run creation.
