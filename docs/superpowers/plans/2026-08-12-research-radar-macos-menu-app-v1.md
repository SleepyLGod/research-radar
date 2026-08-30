# ResearchRadar macOS Menu Bar App v1 Implementation Plan (Lightweight v2.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native, menu-bar-first macOS app that lets a non-CLI user configure reviewed research topics, run or schedule evidence-gated daily reports, read the resulting local article, and independently deliver it to WeChat Drafts and private email.

**Architecture:** Keep the existing Python research system as the only research and publishing engine. A SwiftUI/AppKit app owns user interaction, UI localization, scheduling, the durable single-job queue, process supervision, and local state; it launches one bundled Python engine process per command and communicates only through a versioned JSON file protocol. A small native PDFKit helper replaces App-only Poppler dependencies, while the existing CLI, renderers, evidence gate, and run artifacts remain valid and independently usable.

**Tech Stack:** Swift 6.3, SwiftUI, AppKit, Observation, WebKit, PDFKit, Security, ServiceManagement, UserNotifications, SwiftPM, project-compatible Python `>=3.12`, the current local Python 3.13.x for the frozen beta engine, PyInstaller `onedir`, pytest, XCTest, and macOS shell tooling for local arm64 bundle staging and signing.

## Global Constraints

- Target macOS 26 on Apple Silicon arm64 only. v1 makes no compatibility claim outside that exact platform.
- The native app must not require the user to install Python, `uv`, Homebrew, Poppler, or a shell environment.
- The existing CLI, `ArticleDraft`, evidence policy, WeChat HTML, Archive/RSS, Email renderer, Zhihu renderer, and source-history semantics remain authoritative.
- The app never parses human-readable CLI output and never writes YAML; it uses typed JSON and calls a dedicated bundled engine executable.
- The app does not add a model stage, generate claims, weaken anchors, or modify renderer content.
- Secrets remain in macOS Keychain service `ResearchRadar`; JSON requests, state, logs, notifications, and UI contain secret names or presence only, never values.
- All app-owned directories are mode `0700`; state/request/result files are mode `0600`, written through temporary files followed by atomic rename.
- The app is menu-bar-only by default (`LSUIElement=true`), with one singleton main window. Sheets are allowed only for file selection, secret entry, and destructive/cancellation confirmation.
- App UI language and report language are independent. UI supports `system`, Simplified Chinese, and English; each topic retains its own existing `en | zh` report language.
- The app owns daily scheduling while it is running and may register itself at login only after explicit user consent. Explicit Quit stops future schedules and leaves no hidden scheduler helper.
- The global queue runs one engine process at a time across every topic and delivery channel.
- Every engine process is supervised by the native App. During an active job it watches the App process with event-driven macOS `kqueue`; losing the App terminates the engine process group and records `parent_lost` rather than allowing unsupervised research or delivery.
- Idle means the native App is the only ResearchRadar process. Python, PDFKit helper, Codex, event tailing, and report WebKit content are all demand-loaded and released when their work is no longer visible or running.
- There is no fixed-interval scheduler polling. One one-shot timer represents the next due schedule and is recomputed after configuration, clock, time-zone, sleep, or wake changes.
- Reports and source history are durable user data. Model responses are explicitly separate, rebuildable cache data; automatic cache eviction is disabled until the user supplies a positive limit.
- WeChat and Email delivery are independent. A delivery failure never reruns research and never invalidates a successfully generated local report.
- Archive/RSS, Zhihu publishing, multi-topic evaluation, weekly reports, YAML editing/import, raw claim audit, automatic app updates, and a TUI are outside v1.
- Use signed-off commits and no more than three implementation commits, matching the three tasks below.

---

## 0. Sequencing Rationale

The implementation order is risk-driven:

1. Prove that a real native App can launch a self-contained Python engine, localize a result, and stop the entire process tree.
2. Add the durable research workflow only after that macOS 26 arm64 bundle is reproducible and its idle resource baseline is recorded on the current Mac.
3. Add the full editorial UI, delivery, DMG, and final macOS 26 arm64 resource check last.

PyInstaller packaging is a real risk, but the current project does not depend on NumPy or PyTorch. The concrete frozen inputs exercised in Task 1 are the Python runtime, `cryptography`, `keyring` with macOS backend discovery, Pillow, `pypdf`, PyYAML, the foundation bridge, and their transitive libraries. Verification imports those dependencies from the frozen engine and inspects the actual tree rather than declaring success from an empty bridge executable. App Sandbox remains off for the local beta; that is separate from Hardened Runtime. Static, JavaScript-disabled ResearchRadar reports are an intentional, demand-loaded `WKWebView` fit, not a temporary browser implementation. The plan does not invent package-size, RSS, or cache limits before measuring a real Task 1 bundle.

`NSStatusItem` is intentional. The product requires a dynamic tooltip, distinct left/right click behavior, a native contextual menu, and one explicitly coordinated window. `MenuBarExtra` is not introduced unless those requirements change.

---

## 1. Product Contract

### 1.1 Daily user flow

1. On first launch, ResearchRadar opens the main window and checks local storage, required model credentials, the optional Codex executable, and enabled delivery services.
2. If the user already ran the CLI, the app may copy only `data/source_history/*.jsonl` from a user-selected legacy root into the empty App workspace. It never imports YAML, secrets, schedules, cache, or run artifacts, and never removes the legacy files.
3. The user describes a research topic in plain language. The Python engine generates a reviewable topic profile; the app shows its focus, search phrases, paper phrases, inclusion concepts, and exclusions without exposing YAML.
4. The user confirms the topic, chooses a daily local time, chooses zero or more delivery channels, and optionally enables Start at Login.
5. The menu-bar icon remains available. Hovering shows one concise status line. Left-click opens the same main window; right-click exposes Open, Run Now, Pause All, and Quit.
6. At the due time, or after Run Now, one queue item starts. The window shows Discover, Read & Verify, Prepare report, and Deliver as an expandable operational timeline.
7. A successful research run always creates the existing local report artifacts first. Enabled WeChat and Email deliveries then run as separate queue jobs against that fixed report.
8. The user reads the report inside a restricted `WKWebView`, opens it in the default browser when desired, or reviews the WeChat draft in WeChat.
9. A failed channel shows Retry for that channel only. A failed research job shows the failed stage, a localized actionable explanation, and Retry Research; the underlying redacted message stays in Diagnostics.

### 1.2 UI language and report language

The native interface has its own language preference:

```swift
public enum AppLanguagePreference: String, Codable, Sendable {
    case system
    case simplifiedChinese = "zh-Hans"
    case english = "en"
}

public enum ResolvedAppLanguage: String, Codable, Sendable {
    case simplifiedChinese = "zh-Hans"
    case english = "en"
}
```

- The default is `system`. If the first supported language in `Locale.preferredLanguages` starts with `zh-` or equals `zh`, v1 resolves to Simplified Chinese; every other unsupported language resolves to English.
- While the preference is `system`, the app observes `NSLocale.currentLocaleDidChangeNotification` and refreshes visible copy when the resolved language changes.
- A manual language change immediately refreshes SwiftUI views, the menu-bar tooltip, the native right-click menu, user-facing errors, and notifications scheduled after the change. Notifications that macOS already delivered are not rewritten.
- `en.lproj/Localizable.strings` and `zh-Hans.lproj/Localizable.strings` are the only user-interface string tables. SwiftUI and AppKit both read them through one `@MainActor @Observable LocalizationStore`; AppKit does not maintain a second menu-string table.
- The Swift package declares `defaultLocalization: "en"`. Unsupported or missing keys fall back to English and are test failures in the catalog audit.
- `AppConfigurationV1.uiLanguage` persists the preference. Raw redacted diagnostics remain in their original technical form; only field labels and the user-facing explanation are localized.
- Paper titles, provider and model names, benchmark and metric names, formulas, URLs, and evidence quotes are content, not UI chrome, and are never changed by UI localization.

Report language remains topic-owned:

- `TopicRecordV1.reportLanguage` remains exactly `en | zh`.
- `RunDailyPayloadV1.language` is copied from the selected topic and never inferred from the current window language.
- A new topic initially maps resolved `zh-Hans -> zh` and `en -> en`, then exposes an independent report-language control before approval.
- Changing App UI language never mutates an approved topic or an existing report.

### 1.3 Status language

| State | Menu-bar tooltip | Compact window primary message |
| --- | --- | --- |
| Idle with schedule | `Next: agent-memory at 09:00` | `Next report tomorrow at 09:00` |
| Queued | `agent-memory is queued` | `Waiting for the current job to finish` |
| Discovering | `Finding new sources` | `Finding papers and source updates` |
| Reading | `Reading paper 1 of 2` | `Reading and checking the selected papers` |
| Verifying | `Verifying evidence` | `Checking claims against source passages` |
| Preparing | `Preparing the report` | `Building the local article` |
| Delivering | `Creating WeChat draft` | `Report ready; creating selected deliveries` |
| Complete | `Report ready` | `Today's report is ready` |
| Partial delivery | `Report ready; delivery needs attention` | `The report is safe; one delivery needs retry` |
| Failed | `Run failed at Verify` | `No report was published; review the error and retry` |
| Paused | `Schedules paused` | `Automatic runs are paused` |

Status text is product copy, not raw pipeline stage names. Keep tooltip text to one line and at most 70 characters.

Every row in the table above is represented by localization keys rather than stored English text. The English copy defines the semantic and length contract; the Simplified Chinese catalog supplies the equivalent user-facing text.

### 1.4 Scheduling and retry semantics

- A schedule is daily local wall-clock time for one reviewed topic. Weekly and arbitrary cron syntax are not exposed.
- Before enabling an App schedule, inspect `~/Library/LaunchAgents/ai.research-radar.daily-draft.*.plist`. If a legacy CLI schedule exists for that topic, block the App schedule and show migration instructions; never run two schedulers for the same topic and never unload the old job without explicit user action.
- `Calendar.autoupdatingCurrent` defines the report date and due time so travel follows the user's current local time.
- On launch or wake, schedule evaluation enqueues only the latest missed report date. It never creates a multi-day backlog.
- Scheduling uses one one-shot timer for the nearest enabled schedule. Topic or schedule edits, pause/resume, clock or time-zone changes, and sleep/wake invalidate that timer and compute a replacement. With no enabled schedule, no timer exists.
- The coalescing key is `(job kind, topic_id, report_date, delivery_channel)`. A queued or running key cannot be inserted twice.
- A successful research job for the same topic and report date opens the existing report instead of silently generating a duplicate. An explicit `Run Again` confirmation may create a new attempt only from the full diagnostics view.
- A failed or cancelled research job may be retried with the same report date and a new job/request UUID. Existing outcome-based source history continues to decide whether a source is new.
- Cancellation before `run_daily()` returns a run directory containing a valid `article_draft.json` terminates the process group, creates no delivery jobs, and must not create a successful daily history outcome.
- Once research has committed a successful `ArticleDraft`, cancellation may stop pending deliveries but must not roll back the valid report or its daily history outcome.
- If delivery completion is unknown after a crash, mark the channel `delivery_unknown`; do not retry automatically. For WeChat, tell the user to check the draft box before choosing Retry.

### 1.5 Visual contract

- Use the approved Editorial Radar plus Operational Timeline direction: an editorial report surface, not an operations dashboard and not a wall of cards.
- Compact window: `440 x 580 pt`, with a minimum of `400 x 500 pt`. Full window: default `1040 x 760 pt`, minimum `820 x 620 pt`.
- The same `NSWindow` animates between compact and full frames; it is never duplicated.
- Use system typography. Suggested hierarchy: title `22 pt semibold`, report headline `17 pt semibold`, section heading `15 pt semibold`, body `13 pt regular`, metadata `11 pt regular`.
- Keep article text at a maximum readable width of `720 pt`, left aligned. Letter spacing stays at the system default.
- Use restrained teal for the active research state, system blue for links/actions, green only for completed delivery, amber only for attention, and red only for failure.
- Use native controls and SF Symbols. The status item uses `scope`; buttons use familiar symbols such as `play.fill`, `pause.fill`, `stop.fill`, `arrow.clockwise`, `envelope`, and `square.and.arrow.up`.
- Avoid decorative gradients, floating color blobs, nested cards, oversized hero text, and opaque custom backgrounds over native sidebars/toolbars.
- macOS 26 uses system Liquid Glass only through native APIs; there is no compatibility implementation for older systems.
- Support Light, Dark, Increase Contrast, Reduce Transparency, Reduce Motion, keyboard navigation, VoiceOver labels, and Dynamic Type-equivalent system text sizing.

---

## 2. Module And File Boundaries

### Python engine boundary

| File | Responsibility |
| --- | --- |
| `src/research_radar/application/daily.py` | Shared typed orchestration used by both the CLI and app bridge; builds connectors/routes and invokes the existing daily pipeline. |
| `src/research_radar/application/wechat.py` | Shared WeChat draft service extracted from CLI orchestration without changing rendered HTML or artifacts. |
| `src/research_radar/application/__init__.py` | Public exports for application services only. |
| `src/research_radar/app_bridge/protocol.py` | Strict v1 request, event, result, error, configuration, preflight, and topic payload types. |
| `src/research_radar/app_bridge/events.py` | Redacted, sequence-numbered JSONL event writer. |
| `src/research_radar/app_bridge/configuration.py` | Convert app JSON configuration to existing `AppConfig`; reject secrets and unknown schema versions. |
| `src/research_radar/app_bridge/pdf_helper.py` | Invoke the bundled native PDF helper through JSON request/result files. |
| `src/research_radar/app_bridge/runner.py` | Dispatch the four allowed engine commands and write exactly one terminal result or error. |
| `src/research_radar/app_bridge/__main__.py` | Narrow executable entrypoint accepting only protocol file paths and the helper path. |
| `src/research_radar/pipeline/progress.py` | Add an optional sanitized event listener; existing progress artifact behavior remains unchanged. |
| `src/research_radar/analysis/figures.py` | Route App-engine PDF bbox/render operations through the injected helper; retain existing CLI fallback. |

### Native app boundary

| File | Responsibility |
| --- | --- |
| `apps/macos/ResearchRadar/Package.swift` | SwiftPM products, targets, resources, and macOS 26 arm64 platform contract. |
| `Sources/ResearchRadarCore/Protocol/*.swift` | Codable mirrors of the Python v1 engine protocol. |
| `Sources/ResearchRadarCore/Models/*.swift` | App configuration, topic, schedule, job, report, and delivery state value types. |
| `Sources/ResearchRadarCore/Localization/AppLanguage.swift` | UI-language preference, system-language resolution, and report-language default mapping. |
| `Sources/ResearchRadarCore/Persistence/AtomicJSONStore.swift` | Owner-only atomic JSON reads/writes with schema checking. |
| `Sources/ResearchRadarCore/Queue/JobQueue.swift` | Pure durable queue transitions and coalescing. |
| `Sources/ResearchRadarCore/Scheduling/ScheduleEvaluator.swift` | Pure due-job and wake catch-up decisions. |
| `Sources/ResearchRadarExecutable/ResearchRadarMain.swift` | Thin `@main` executable that constructs the app feature scene. |
| `Sources/ResearchRadarAppFeature/App/*.swift` | AppKit delegate, singleton-window coordination, and dependency container. |
| `Sources/ResearchRadarAppFeature/Stores/AppStore.swift` | Main-actor observable source of UI truth. |
| `Sources/ResearchRadarAppFeature/Localization/LocalizationStore.swift` | One observable source for SwiftUI and AppKit localized strings. |
| `Sources/ResearchRadarAppFeature/Localization/UserFacingErrorCatalog.swift` | Stable engine-error code to actionable English/Simplified Chinese copy. |
| `Sources/ResearchRadarAppFeature/Services/EngineProcessSupervisor.swift` | One process at a time, event tailing, cancellation, and crash reconciliation. |
| `Sources/ResearchRadarAppFeature/Services/KeychainStore.swift` | Generic-password writes/presence checks under service `ResearchRadar`. |
| `Sources/ResearchRadarAppFeature/Services/LoginItemService.swift` | `SMAppService.mainApp` registration state and errors. |
| `Sources/ResearchRadarAppFeature/Services/LegacyStateMigrationService.swift` | Detect old launchd schedules and explicitly copy source-history JSONL into an empty App workspace. |
| `Sources/ResearchRadarAppFeature/Services/NotificationService.swift` | Completion, partial-delivery, and failure notifications. |
| `Sources/ResearchRadarAppFeature/Services/ReportReaderPolicy.swift` | Restricted local `WKWebView` navigation and external-link handling. |
| `Sources/ResearchRadarAppFeature/Services/StorageUsageService.swift` | On-demand usage snapshots and explicitly confirmed cleanup of app-owned model cache only. |
| `Sources/ResearchRadarAppFeature/Views/*.swift` | Onboarding, compact Today, full report/history/settings/diagnostics, timeline, and delivery status UI. |
| `Sources/ResearchRadarAppFeature/Resources/en.lproj/Localizable.strings` | English App UI string table and development-language fallback. |
| `Sources/ResearchRadarAppFeature/Resources/zh-Hans.lproj/Localizable.strings` | Simplified Chinese App UI string table. |
| `Sources/ResearchRadarPDFCore/PDFOperations.swift` | Testable PDFKit word-bbox extraction and point-based PNG crop rendering. |
| `Sources/ResearchRadarPDFHelper/PDFHelperMain.swift` | Thin native helper executable that decodes a request and calls `ResearchRadarPDFCore`. |
| `Tests/ResearchRadarAppFeatureTests/Fixtures/ProcessTreeFixture.swift` | Test-only engine/child/grandchild process fixture; never included in the App bundle. |

### Build and packaging boundary

| File | Responsibility |
| --- | --- |
| `packaging/macos/research-radar-engine.spec` | Reproducible PyInstaller `onedir` build of the app bridge. |
| `packaging/macos/Info.plist` | Bundle identity, `LSUIElement`, executable, version, and macOS 26 arm64 floor. |
| `packaging/macos/ResearchRadar.icns` | Native app icon derived from the approved radar visual direction. |
| `script/build_macos_engine.sh` | Freeze the Python engine; never installs dependencies at app runtime. |
| `script/assemble_macos_app.sh` | Assemble already-built Swift products and a frozen engine with `/usr/bin/ditto`, preserving symlinks. |
| `script/verify_macos_bundle.py` | Compare symlink manifests, reject escaping links/private paths, and validate Mach-O dependencies. |
| `script/stage_macos_app.sh` | Build local Swift/engine products, then invoke the deterministic assembler. |
| `script/build_and_run.sh` | Canonical local kill, build, stage, launch, and optional verify/log workflow. |
| `script/package_macos_beta.sh` | Deepest-first ad-hoc signing, verification, and local beta DMG creation. |
| `.codex/environments/environment.toml` | Codex desktop Run action pointing to `./script/build_and_run.sh --verify`. |
| `dist/macos-resource-report.json` | Ignored local measurements for toolchain identity, logical build/bundle sizes, launch/preflight timing, idle RSS/CPU samples, repeated-cycle RSS, leak summary, and descendant checks. |

No HTML renderer is shared between channels. The app reads the already-produced `wechat.html` for its local reader; it does not create a new article renderer.

SwiftPM, PyInstaller, XCTest, and staged App outputs remain local and rebuildable. Before implementation, `.gitignore` adds `.build/`, `.swiftpm/`, and `*.xcresult`; existing `build/` and `dist/` rules remain authoritative. Task 1 creates a new `app-build` optional dependency group containing PyInstaller rather than referring to a group that does not yet exist.

The local toolchain preflight records `uname -m`, `sw_vers`, `swift --version`, and `xcrun --show-sdk-version`. It requires arm64, Swift 6.3 or newer, and the macOS 26 SDK. Command Line Tools 26.5 has already failed a generated empty SwiftPM build because its `PackageDescription` installation is inconsistent. Before Task 1, install only the offered Command Line Tools for Xcode 26.6 update, then prove both a generated executable package and a package using `swift-tools-version: 6.3`, `.macOS("26.0")`, AppKit, SwiftUI, and English/`zh-Hans` localization can build and run. If that gate still fails, stop and retain the exact manifest/linker diagnostics; do not install full Xcode or start App implementation implicitly.

SwiftPM scratch/module caches stay under ignored project `.build/` directories, and PyInstaller work/dist trees stay under ignored `build/` and `dist/`. `uv sync --extra app-build` adds PyInstaller to the existing project environment instead of creating a second App-specific virtual environment; resyncing without that extra removes the development-only dependency when App work is paused. The project remains compatible with Python `>=3.12`, while the local beta frozen engine records and reuses the existing Python 3.13.x patch version. It does not install a second Python runtime for development. The installed App contains only the staged Swift products and frozen engine, not any of these development caches. Rebuildable project directories may be moved to Trash independently and never contain user reports or source history.

The CLT-only build intentionally uses localized `.strings` files instead of `.xcstrings`. Apple ships `xcstringstool` with full Xcode, not the standalone Command Line Tools package; requiring String Catalog compilation would silently add the large Xcode dependency that this lightweight plan excludes. `LocalizationStore` performs explicit `lproj` bundle lookup so manual UI-language changes remain immediate and independent from the report language.

---

## 3. Versioned Data Contracts

### 3.1 Application Support layout

```text
~/Library/Application Support/ResearchRadar/
├── config/
│   └── app-config.json
├── state/
│   ├── app-state.json
│   ├── queue.json
│   ├── schedules.json
│   └── report-index.json
├── jobs/
│   └── <job-uuid>/
│       ├── request.json
│       ├── progress.jsonl
│       ├── result.json
│       ├── error.json
│       ├── stdout.log
│       └── stderr.log
└── workspace/
    ├── runs/
    ├── data/
    │   └── source_history/
    └── cache/
        └── model_calls/
```

`result.json` and `error.json` are mutually exclusive. A partially written last line in `progress.jsonl` is ignored during recovery. Logs are bounded to 1 MiB per job and contain redacted diagnostics, not prompts, model output, article bodies, headers, or secret values.

The layout distinguishes durable data from rebuildable data even though both remain under the contained App workspace:

- `config/`, `state/`, `workspace/runs/`, and `workspace/data/source_history/` are durable user data and never participate in cache cleanup.
- `workspace/cache/model_calls/` is app-owned, rebuildable model cache. Its default limit is disabled; a user-supplied positive byte limit authorizes oldest-used-entry eviction within this directory only.
- Storage usage is calculated only when Settings requests a snapshot, immediately before an explicit cleanup, or after a cache hit/write when a user limit is enabled. No background disk scanner exists.
- A successful job keeps request/result metadata but discards its stdout/stderr after reconciliation. A failed job keeps at most 1 MiB per stream, and only the newest failed diagnostic for a `(topic, job kind)` remains available after a later failure replaces it.
- Task 1 tests use temporary directories. Manual foundation runs use `~/Library/Application Support/ResearchRadar-Dev/`; they do not create or mutate the production root above.

### 3.2 Engine request

Python and Swift define the same field names and enum values:

```json
{
  "schema_version": 1,
  "request_id": "0b5f8bc4-f934-4d86-b513-265e950fb44d",
  "command": "run_daily",
  "created_at": "2026-08-12T09:00:00Z",
  "app_support_root": "/Users/example/Library/Application Support/ResearchRadar",
  "config_path": "/Users/example/Library/Application Support/ResearchRadar/config/app-config.json",
  "payload": {
    "topic_id": "agent-memory",
    "report_date": "2026-08-12",
    "limit": 5,
    "deep_limit": 2,
    "language": "zh",
    "model_cache": true,
    "model_cache_limit_bytes": null
  }
}
```

Allowed `command` values are exactly:

```python
class EngineCommand(StrEnum):
    PREFLIGHT = "preflight"
    BOOTSTRAP_TOPIC = "bootstrap_topic"
    RUN_DAILY = "run_daily"
    RETRY_DELIVERY = "retry_delivery"
```

Command payloads are exact dataclasses:

```python
@dataclass(frozen=True)
class PreflightPayloadV1:
    live_probe: bool


@dataclass(frozen=True)
class BootstrapTopicPayloadV1:
    description: str
    language: str


@dataclass(frozen=True)
class RunDailyPayloadV1:
    topic_id: str
    report_date: str
    limit: int
    deep_limit: int
    language: str
    model_cache: bool
    model_cache_limit_bytes: int | None


@dataclass(frozen=True)
class RetryDeliveryPayloadV1:
    run_dir: str
    channel: str  # "wechat" or "email"
    allow_resend: bool
    acknowledge_unknown_outcome: bool
```

This section describes the final schema frozen in Task 2. Task 1 implements only the common envelope, terminal types, and `preflight` payload; it does not add placeholder decoders for bootstrap, daily, or delivery. Task 2 adds and freezes the remaining command payloads before any beta is published.

`request_id` and job directory UUID must match. `config_path` is nullable only for the local-only foundation preflight in Task 1; every Task 2 production command and every live provider preflight requires it. A present `config_path`, `run_dir`, PDF input, or helper output must resolve under `app_support_root`. The request protocol rejects unknown keys, unknown enum values, symlink escapes, and secret-value fields such as `password`, `secret_value`, `api_key_value`, `token_value`, or `cookie`. App configuration may contain validated symbolic names ending in `_secret`, such as `deepseek.api_key`; it never contains the corresponding value. `model_cache_limit_bytes` is either null or a positive integer; null performs no automatic eviction.

`allow_resend` is used only by Email and is false unless the user confirms a resend after an existing success. `acknowledge_unknown_outcome` is required before retrying either channel from `unknown`; the engine rejects an unacknowledged retry rather than risking a duplicate delivery. The bridge derives WeChat title and digest from the immutable `ArticleDraft`, and reads author and thumbnail media ID from app configuration.

### 3.3 App configuration

`app-config.json` is a user-interface-owned schema, not a serialized Python dataclass and not YAML:

```json
{
  "schema_version": 1,
  "project_name": "ResearchRadar",
  "ui_language": "system",
  "workspace_root": "/Users/example/Library/Application Support/ResearchRadar/workspace",
  "providers": [
    {
      "id": "deepseek",
      "kind": "openai_compatible",
      "base_url": "https://api.deepseek.com/chat/completions",
      "api_key_secret": "deepseek.api_key",
      "command_path": null,
      "timeout_seconds": 900,
      "thinking": "enabled",
      "reasoning_effort": "high"
    },
    {
      "id": "codex",
      "kind": "codex_cli",
      "base_url": null,
      "api_key_secret": null,
      "command_path": "/absolute/path/to/codex",
      "timeout_seconds": 900,
      "thinking": null,
      "reasoning_effort": "high"
    }
  ],
  "routes": [
    {"task": "deep_reading", "provider_id": "deepseek", "model": "deepseek-v4-flash"},
    {"task": "verifier", "provider_id": "codex", "model": "gpt-5.6-terra"}
  ],
  "topics": [],
  "discovery": {
    "trusted_domains": [],
    "web_search_provider": "tavily",
    "web_search_secret": "web_search.api_key",
    "web_search_endpoint": null,
    "web_search_max_results": 5,
    "web_search_depth": "advanced",
    "web_search_timeout_seconds": 30
  },
  "delivery": {
    "wechat": {"enabled": false, "author": "", "thumb_media_id": "", "app_id_secret": "wechat.app_id", "app_secret_secret": "wechat.app_secret"},
    "email": {"enabled": false, "smtp_host": "", "smtp_port": 465, "security": "tls", "username": "", "password_secret": "email.smtp_password", "from_address": "", "to_address": "", "timeout_seconds": 30}
  },
  "storage": {
    "model_cache_limit_bytes": null
  },
  "start_at_login": false
}
```

The onboarding preset also creates routes for `source_gist`, `anchor_repair`, `report_localization`, and `topic_bootstrap` using the current defaults. The app UI exposes the default DeepSeek plus Codex path and the explicit DeepSeek-verifier fallback; arbitrary custom provider editing remains a CLI feature in v1.

`ui_language` is consumed only by the Swift app. `configuration.py` removes it before converting the remaining research settings into `AppConfig`; it cannot alter topic language or a model prompt. Missing `ui_language` in a pre-release fixture defaults to `system`, but persisted v1 App configuration always writes the field explicitly.

`storage.model_cache_limit_bytes` is App-owned policy. Swift copies it into `RunDailyPayloadV1`; the Python bridge passes it to the existing cache wrapper without adding it to public CLI configuration. The value defaults to null, is never inferred from disk size, and does not apply to reports, source history, delivery artifacts, configuration, or job state.

Python does not duplicate the research configuration model. It uses one thin bridge wrapper for the App-only delivery fields that have no existing `AppConfig` counterpart:

```python
@dataclass(frozen=True)
class AppWeChatConfigV1:
    enabled: bool
    author: str
    thumb_media_id: str
    app_id_secret: str
    app_secret_secret: str


@dataclass(frozen=True)
class LoadedAppConfigurationV1:
    research: AppConfig
    wechat: AppWeChatConfigV1
    email_enabled: bool
```

`load_app_configuration(path, require_topics=...)` validates the complete App JSON once, converts provider/routes/topics/discovery/Email/security into `research`, and returns the three App delivery values above. Command handlers receive `LoadedAppConfigurationV1`: daily uses `.research`; WeChat uses `.wechat`; Email uses `.research.email` only when `email_enabled` is true. No handler reopens or indexes raw JSON.

Before the first topic exists, provider preflight and topic bootstrap convert provider, discovery, and delivery settings with `require_topics=false`. `configuration.py` always injects `security.secret_backend=keychain`; it maps `delivery.email` to the existing top-level Email config and keeps WeChat settings in `LoadedAppConfigurationV1`. The App JSON cannot select another secret backend. `run_daily` always parses with `require_topics=true`. Implement this as an explicit keyword-only parameter on the existing parser:

```python
def parse_config(data: dict[str, Any], *, require_topics: bool = True) -> AppConfig:
    """Parse configuration, allowing an empty topic list only during onboarding."""
```

The public YAML loader continues to call the default strict form, so existing CLI behavior cannot accept a topic-less config by accident.

### 3.4 Progress events

All JSONL events use one flat, forward-readable envelope:

```swift
struct EngineEventV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let sequence: Int
    let requestID: UUID
    let emittedAt: Date
    let type: EngineEventType
    let stage: EngineStage?
    let status: EngineEventStatus?
    let message: String?
    let completed: Int?
    let total: Int?
    let deliveryChannel: DeliveryChannel?
    let runDirectory: String?
    let error: RedactedEngineErrorV1?
}
```

```swift
enum EngineEventType: String, Codable, Sendable {
    case started
    case stageChanged = "stage_changed"
    case progress
    case deliveryResult = "delivery_result"
    case completed
    case failed
    case cancelled
}

enum EngineStage: String, Codable, Sendable {
    case preflight
    case topicBootstrap = "topic_bootstrap"
    case discovery
    case sourceGist = "source_gist"
    case acquisition
    case deepReading = "deep_reading"
    case anchorRepair = "anchor_repair"
    case verifier
    case localization
    case compose
    case wechatDraft = "wechat_draft"
    case email
    case complete
}
```

Supporting wire types are fixed for schema v1:

```swift
enum EngineCommand: String, Codable, Sendable {
    case preflight
    case bootstrapTopic = "bootstrap_topic"
    case runDaily = "run_daily"
    case retryDelivery = "retry_delivery"
}

enum EngineEventStatus: String, Codable, Sendable {
    case running, succeeded, failed
}

enum DeliveryChannel: String, Codable, Sendable {
    case wechat, email
}

enum ReportLanguageV1: String, Codable, Sendable {
    case english = "en"
    case chinese = "zh"
}

enum EngineResultStatus: String, Codable, Sendable {
    case succeeded
    case partialSuccess = "partial_success"
}

struct RedactedEngineErrorV1: Codable, Equatable, Sendable {
    let code: String
    let message: String
    let retryable: Bool
}

struct PreflightCheckV1: Codable, Equatable, Sendable {
    let id: String
    let status: PreflightCheckStatus
    let message: String
    let provider: String?
    let model: String?
}

enum PreflightCheckStatus: String, Codable, Sendable {
    case ready, optional
    case actionRequired = "action_required"
    case unavailable
}

struct PreflightSummaryV1: Codable, Equatable, Sendable {
    let checks: [PreflightCheckV1]
    let ready: Bool
}

struct TopicDraftV1: Codable, Equatable, Sendable {
    let id: String
    let displayName: String
    let researchFocus: String
    let queries: [String]
    let paperQueries: [String]
    let webQueries: [String]
    let exclusionTerms: [String]
    let requiredPhrases: [String]
    let conceptGroups: [String: [String]]
    let negativePhrases: [String]
    let prioritySources: [String]
    let sourceIntent: String
    let reportLanguage: ReportLanguageV1
    let warnings: [String]
}

enum DeliveryResultStatus: String, Codable, Sendable {
    case created, sent, dryRun = "dry_run"
}

struct DeliveryResultV1: Codable, Equatable, Sendable {
    let runDirectory: String
    let channel: DeliveryChannel
    let status: DeliveryResultStatus
    let completedAt: Date
}

struct EngineReportSummaryV1: Codable, Equatable, Sendable {
    let runDirectory: String
    let reportDate: String
    let articleDraftPath: String
    let reportHTMLPath: String
    let title: String
    let summary: String
    let sourceCount: Int
    let deepReadCount: Int
    let publishableClaimCount: Int
}

struct PreflightPayloadV1: Codable, Equatable, Sendable {
    let liveProbe: Bool
}

struct BootstrapTopicPayloadV1: Codable, Equatable, Sendable {
    let description: String
    let language: ReportLanguageV1
}

struct RunDailyPayloadV1: Codable, Equatable, Sendable {
    let topicID: String
    let reportDate: String
    let limit: Int
    let deepLimit: Int
    let language: ReportLanguageV1
    let modelCache: Bool
}

struct RetryDeliveryPayloadV1: Codable, Equatable, Sendable {
    let runDirectory: String
    let channel: DeliveryChannel
    let allowResend: Bool
    let acknowledgeUnknownOutcome: Bool
}

enum EnginePayloadV1: Equatable, Sendable {
    case preflight(PreflightPayloadV1)
    case bootstrapTopic(BootstrapTopicPayloadV1)
    case runDaily(RunDailyPayloadV1)
    case retryDelivery(RetryDeliveryPayloadV1)
}
```

`EngineRequestV1` implements custom `Codable`: it decodes `command` first and then decodes `payload` into the matching case. Encoding performs the inverse operation. A mismatched command/payload is an error; it never falls back to an untyped dictionary.

`sequence` starts at 1 and increases by one. The Python bridge maps existing sanitized pipeline stages to this enum; unknown internal stages become a `progress` event under the last known public stage rather than extending the wire enum without a schema version.

The v1 mapping is fixed and tested:

| Existing progress stage | Engine stage | Four-step UI row |
| --- | --- | --- |
| `run/created` | no stage, `started` event | Discover |
| `discovery`, `relevance`, `history`, `reportable_sources`, `deep_selection` | `discovery` | Discover |
| `source_gist` | `source_gist` | Discover |
| `ingestion`, `paper_text_quality` | `acquisition` | Read & Verify |
| `reader` | `deep_reading` | Read & Verify |
| anchor repair callback | `anchor_repair` | Read & Verify |
| `verifier` | `verifier` | Read & Verify |
| `localization` | `localization` | Prepare report |
| `artifacts`, `explanation_policy`, `public_style` | `compose` | Prepare report |
| WeChat service event | `wechat_draft` | Deliver |
| Email service event | `email` | Deliver |
| `run/completed` | `complete`, `completed` event | Complete |

If a late source-history warning occurs while artifacts are being written, it remains under `compose`; it does not move the UI back to Discover.

### 3.5 Terminal result and error

```swift
struct EngineResultV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let requestID: UUID
    let command: EngineCommand
    let status: EngineResultStatus // succeeded or partialSuccess
    let completedAt: Date
    let report: EngineReportSummaryV1?
    let preflight: PreflightSummaryV1?
    let topicDraft: TopicDraftV1?
    let delivery: DeliveryResultV1?
}

struct EngineErrorV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let requestID: UUID
    let status: String // always "failed"
    let stage: EngineStage
    let code: String
    let message: String
    let retryable: Bool
    let completedAt: Date
}
```

The error `message` is redacted and capped at 500 characters. Python tracebacks may be written only to the bounded redacted diagnostic log. They never enter notifications or the report.

`EngineErrorV1.code` is a stable machine identifier. Schema v1 recognizes these codes:

```text
invalid_request
command_unavailable
unsupported_schema
invalid_configuration
missing_secret
missing_executable
provider_unavailable
invalid_report_date
research_failed
delivery_failed
engine_crashed
parent_lost
protocol_error
cancelled
```

The native app never places `EngineErrorV1.message` directly in the normal UI. It maps the code through:

```swift
public struct UserFacingError: Equatable, Sendable {
    public let title: String
    public let explanation: String
    public let actionTitle: String?
}

@MainActor
public struct UserFacingErrorCatalog {
    public func error(
        for code: String,
        retryable: Bool,
        language: ResolvedAppLanguage
    ) -> UserFacingError
}
```

Known codes receive localized, actionable copy. An unknown code maps to a generic localized failure and an `Open Diagnostics` action. The original redacted message is visible only in Diagnostics and copied only through the diagnostic allowlist; Python exception names and tracebacks never enter alerts, tooltips, menus, or notifications.

### 3.6 Localization contract

Localization is a presentation service, not a second configuration or content pipeline:

```swift
public enum AppStringKey: String, Sendable {
    case menuOpen = "menu.open"
    case menuRunNow = "menu.run_now"
    case menuPauseAll = "menu.pause_all"
    case menuQuit = "menu.quit"
    case preflightReady = "preflight.ready"
    case diagnosticsOpen = "diagnostics.open"
}

public enum AppLanguageResolver {
    public static func resolve(
        preference: AppLanguagePreference,
        preferredLanguages: [String]
    ) -> ResolvedAppLanguage

    public static func defaultReportLanguage(
        for language: ResolvedAppLanguage
    ) -> ReportLanguageV1
}

@MainActor @Observable
public final class LocalizationStore {
    public private(set) var preference: AppLanguagePreference
    public private(set) var resolvedLanguage: ResolvedAppLanguage

    public func setPreference(_ preference: AppLanguagePreference)
    public func handleSystemLanguagesChanged(_ preferredLanguages: [String])
    public func text(_ key: AppStringKey) -> String
}
```

`LocalizationStore` resolves the requested `en` or `zh-Hans` localization directory from `Bundle.module`, creates the corresponding language bundle, and reads `Localizable.strings` from that bundle. `AppDelegate`, `WindowCoordinator`, SwiftUI views, `NotificationService`, and `UserFacingErrorCatalog` all receive the same store instance from `AppContainer`. They never cache localized strings in durable state. Durable jobs and reports store enum/state values and content only, so changing UI language re-renders existing state without rewriting it.

The catalog audit requires every `AppStringKey` to have both `en` and `zh-Hans` values. Dynamic values use localized format entries with typed arguments; code must not build sentences by concatenating translated fragments.

### 3.7 Native durable model contract

These names are shared by Tasks 2 and 3 and must not be redefined in view files:

```swift
enum JobTrigger: String, Codable, Sendable {
    case schedule, runNow = "run_now", retry
}

enum JobKind: String, Codable, Sendable {
    case research, delivery
}

enum JobState: String, Codable, Sendable {
    case pending, running, cancelling, succeeded
    case partialSuccess = "partial_success"
    case failed, cancelled, interrupted
    case deliveryUnknown = "delivery_unknown"
}

enum WindowMode: String, Codable, Sendable {
    case compact, full
}

enum DeliveryState: String, Codable, Sendable {
    case notRequested = "not_requested"
    case pending, sending, created, sent, failed, unknown
}

enum LoginItemStatus: String, Codable, Sendable {
    case notRegistered = "not_registered"
    case enabled, requiresApproval = "requires_approval", unavailable
}

struct TopicRecordV1: Codable, Equatable, Identifiable, Sendable {
    let id: String
    var displayName: String
    var researchFocus: String
    var queries: [String]
    var paperQueries: [String]
    var webQueries: [String]
    var exclusionTerms: [String]
    var requiredPhrases: [String]
    var conceptGroups: [String: [String]]
    var negativePhrases: [String]
    var prioritySources: [String]
    var sourceIntent: String
    var reportLanguage: ReportLanguageV1
    var sourceLimit: Int
    var deepReadLimit: Int
    var modelCacheEnabled: Bool
    var isPaused: Bool
}

struct DailyScheduleV1: Codable, Equatable, Identifiable, Sendable {
    let id: UUID
    let topicID: String
    var hour: Int
    var minute: Int
    var isEnabled: Bool
    var deliveryChannels: [DeliveryChannel]
}

struct DeliveryRecordV1: Codable, Equatable, Sendable {
    let channel: DeliveryChannel
    var state: DeliveryState
    var lastAttemptAt: Date?
    var completedAt: Date?
    var error: RedactedEngineErrorV1?
}

struct ReportRecordV1: Codable, Equatable, Identifiable, Sendable {
    let schemaVersion: Int
    let id: UUID
    let topicID: String
    let reportDate: String
    let runDirectory: String
    let articleDraftPath: String
    let reportHTMLPath: String
    let title: String
    let summary: String
    let sourceCount: Int
    let deepReadCount: Int
    let publishableClaimCount: Int
    var deliveries: [DeliveryRecordV1]
    let createdAt: Date
}

struct ProviderRecordV1: Codable, Equatable, Identifiable, Sendable {
    let id: String
    var kind: String
    var baseURL: String?
    var apiKeySecret: String?
    var commandPath: String?
    var timeoutSeconds: Int
    var thinking: String?
    var reasoningEffort: String?
}

struct RouteRecordV1: Codable, Equatable, Sendable {
    let task: String
    var providerID: String
    var model: String
}

struct DiscoverySettingsV1: Codable, Equatable, Sendable {
    var trustedDomains: [String]
    var webSearchProvider: String?
    var webSearchSecret: String?
    var webSearchEndpoint: String?
    var webSearchMaxResults: Int
    var webSearchDepth: String
    var webSearchTimeoutSeconds: Int
}

struct WeChatDeliverySettingsV1: Codable, Equatable, Sendable {
    var enabled: Bool
    var author: String
    var thumbMediaID: String
    var appIDSecret: String
    var appSecretSecret: String
}

enum EmailSecurityV1: String, Codable, Sendable {
    case tls, starttls
}

struct EmailDeliverySettingsV1: Codable, Equatable, Sendable {
    var enabled: Bool
    var smtpHost: String
    var smtpPort: Int
    var security: EmailSecurityV1
    var username: String
    var passwordSecret: String
    var fromAddress: String
    var toAddress: String
    var timeoutSeconds: Int
}

struct DeliverySettingsV1: Codable, Equatable, Sendable {
    var wechat: WeChatDeliverySettingsV1
    var email: EmailDeliverySettingsV1
}

struct StorageSettingsV1: Codable, Equatable, Sendable {
    var modelCacheLimitBytes: UInt64?
}

struct StorageUsageSnapshot: Equatable, Sendable {
    let modelCacheBytes: UInt64
    let reportsBytes: UInt64
    let jobDiagnosticsBytes: UInt64
    let totalBytes: UInt64
    let measuredAt: Date
}

struct AppConfigurationV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    var projectName: String
    var uiLanguage: AppLanguagePreference
    var workspaceRoot: String
    var providers: [ProviderRecordV1]
    var routes: [RouteRecordV1]
    var topics: [TopicRecordV1]
    var discovery: DiscoverySettingsV1
    var delivery: DeliverySettingsV1
    var storage: StorageSettingsV1
    var startAtLogin: Bool
}

enum OnboardingStep: String, Codable, Sendable {
    case storage
    case providers
    case topicDescription
    case topicReview
    case delivery
    case schedule
    case preflight
    case complete
}

struct AppRuntimeStateV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    var onboardingStep: OnboardingStep
    var windowMode: WindowMode
    var selectedTopicID: String?
    var schedulesPaused: Bool
    var legacyHistoryImportedAt: Date?
    var updatedAt: Date
}

struct JobQueueSnapshotV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    var jobs: [JobRecordV1]
}

struct ScheduleSnapshotV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    var schedules: [DailyScheduleV1]
    var lastEvaluatedAt: Date?
}

struct ReportIndexV1: Codable, Equatable, Sendable {
    let schemaVersion: Int
    var reports: [ReportRecordV1]
}

struct DueResearchJob: Equatable, Sendable {
    let topicID: String
    let reportDate: String
    let trigger: JobTrigger
}

enum EnqueueResult: Equatable, Sendable {
    case enqueued(UUID)
    case coalesced(UUID)
}

enum ReconciledJobState: Equatable, Sendable {
    case terminal(JobState)
    case interrupted
}

enum ReconciledEngineTerminalState: Equatable, Sendable {
    case result(EngineResultV1)
    case error(EngineErrorV1)
}

protocol EngineArtifactResolving: Sendable {
    func terminalState(for job: JobRecordV1) throws -> ReconciledJobState?
}

enum JSONCoding {
    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }

    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        decoder.keyDecodingStrategy = .custom { path in
            let raw = path.last!.stringValue
            let parts = raw.split(separator: "_").map(String.init)
            let first = parts.first ?? raw
            let rest = parts.dropFirst().map { part in
                switch part {
                case "id": return "ID"
                case "url": return "URL"
                default: return part.prefix(1).uppercased() + String(part.dropFirst())
                }
            }
            return JSONKey(stringValue: ([first] + rest).joined())!
        }
        return decoder
    }
}

struct JSONKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}
```

The custom decoder keeps standard Swift acronym names (`requestID`, `topicID`, `baseURL`) compatible with Python snake-case keys (`request_id`, `topic_id`, `base_url`). Every persisted and wire file uses these shared coders; no feature creates its own `JSONEncoder` or `JSONDecoder`. `app-config.json`, `app-state.json`, `queue.json`, `schedules.json`, and `report-index.json` map one-to-one to `AppConfigurationV1`, `AppRuntimeStateV1`, `JobQueueSnapshotV1`, `ScheduleSnapshotV1`, and `ReportIndexV1`; schedules are never duplicated into App configuration. `deliveryChannels` is a validated, duplicate-free array written in `wechat,email` order so durable JSON stays deterministic.

For bootstrap results, `researchFocus` is the trimmed original description supplied by the user. `displayName` is that description trimmed to 80 characters; the user may edit it before approval. Neither value is inferred as a research claim, and both are ignored when converting the approved record to the existing `TopicConfig` fields used by the pipeline.

### 3.8 PDF helper contract

The native helper accepts a request file and writes a result file:

```text
ResearchRadarPDFHelper --request <request.json> --result <result.json>
```

Allowed operations are `extract_page_words` and `render_crop`:

```json
{
  "schema_version": 1,
  "request_id": "b2d4a9fd-15fc-4020-939d-1213c1267917",
  "operation": "render_crop",
  "allowed_root": "/Users/example/Library/Application Support/ResearchRadar",
  "pdf_path": "/Users/example/Library/Application Support/ResearchRadar/workspace/runs/example/artifacts/paper.pdf",
  "page_number": 3,
  "crop_box_points": {"x": 42.0, "y": 75.0, "width": 510.0, "height": 245.0},
  "dpi": 160,
  "output_path": "/Users/example/Library/Application Support/ResearchRadar/workspace/runs/example/figures/figure-2.png"
}
```

All crop boxes use the existing ResearchRadar convention: PDF points with a top-left origin. The helper alone converts to PDFKit's coordinate system and pixels. `extract_page_words` returns page width/height and words in the same top-left point system. The Python figure-quality policy remains responsible for deciding whether a crop is publishable.

`PDFHelperClient` starts one helper process only when one of these operations is requested, waits for its terminal result, and always reaps it on success, failure, timeout, or cancellation. Passing the helper executable path to `run_daily` does not launch it. There is no helper daemon, connection pool, warm process, or idle preflight launch.

---

## 4. Implementation Tasks

### Pre-implementation gate

Before adding product code:

1. commit this reviewed plan separately with `git commit -s -m "[docs] Finalize lightweight macOS app foundation plan"`;
2. install only the offered Command Line Tools for Xcode 26.6 update;
3. verify Swift 6.3 or newer, SDK 26.x, and arm64;
4. build a generated empty executable package;
5. build and run a temporary localized AppKit/SwiftUI package using `swift-tools-version: 6.3` and `.macOS("26.0")`;
6. move temporary probe projects to Trash.

Task 1 is blocked if either SwiftPM probe fails. Preserve the full diagnostics and evaluate the toolchain separately; do not compensate with checked-in workarounds, a second Swift toolchain, or a full Xcode install unless the user makes that decision explicitly.

### Task 1: Add Bundled macOS App Foundation

**Deliverable:** A staged, ad-hoc-signed menu-bar App launches without user-installed Python, `uv`, Homebrew, or the source checkout; left-click reuses one window, right-click opens a native menu, the window runs a bundled local preflight, shows a localized success or failure, and can cancel the engine plus its fixture descendants without leaving a process behind.

This is a vertical product slice, not a packaging-only spike. It deliberately excludes topic onboarding, real providers, daily research, PDF processing, scheduling, and delivery.

**Files:**
- Modify: `.gitignore`
- Create: `src/research_radar/app_bridge/__init__.py`
- Create: `src/research_radar/app_bridge/__main__.py`
- Create: `src/research_radar/app_bridge/protocol.py`
- Create: `src/research_radar/app_bridge/events.py`
- Create: `src/research_radar/app_bridge/runner.py`
- Create: `tests/test_app_bridge_protocol.py`
- Create: `tests/test_app_bridge_events.py`
- Create: `tests/test_app_bridge_runner.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/macos/ResearchRadar/Package.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Protocol/EngineProtocol.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Localization/AppLanguage.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarExecutable/ResearchRadarMain.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/ResearchRadarScene.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/AppDelegate.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/AppContainer.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/WindowCoordinator.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization/LocalizationStore.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization/UserFacingErrorCatalog.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/EngineProcessSupervisor.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/EventTailer.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/FoundationPreflightView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Resources/en.lproj/Localizable.strings`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Resources/zh-Hans.lproj/Localizable.strings`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarProcessFixture/ProcessTreeFixture.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/EngineProtocolTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/AppLanguageTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/EngineProcessSupervisorTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/FoundationWindowTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/LocalizationStoreTests.swift`
- Create: `packaging/macos/research-radar-engine.spec`
- Create: `packaging/macos/Info.plist`
- Create: `script/build_macos_engine.sh`
- Create: `script/assemble_macos_app.sh`
- Create: `script/stage_macos_app.sh`
- Create: `script/verify_macos_bundle.py`
- Create: `tests/test_macos_bundle_verifier.py`

**Interfaces:**
- Produces the common request/event/result/error envelope and only the `preflight` payload. Task 2 adds and freezes bootstrap, daily, and delivery payloads before beta distribution.
- Produces `EngineProcessSupervisor.run(request:)`, `cancel()`, and `reconcileTerminalArtifacts()` with the final process-group semantics used by later tasks.
- Produces one `LocalizationStore` shared by AppKit and SwiftUI, one `WindowCoordinator`, and deterministic bundle verification scripts reused by Tasks 2 and 3.
- Does not consume `AppConfig`, Keychain provider secrets, topic YAML, or any publisher.

```swift
public actor EngineProcessSupervisor {
    public func run(
        request: EngineRequestV1,
        jobDirectory: URL
    ) async throws -> EngineResultV1

    public func cancel(requestID: UUID) async throws

    public func reconcileTerminalArtifacts(
        requestID: UUID,
        jobDirectory: URL
    ) async throws -> ReconciledEngineTerminalState?
}
```

Task 2 maps `JobRecordV1` to this low-level interface; the supervisor never owns the durable queue model.

- [ ] **Step 1: Define the foundation protocol envelope and prove strict decoding**

Write failing Python and Swift tests for exact schema version, the single `preflight` command/payload, unknown keys, secret-value keys, request/job UUID equality, and nullable `config_path` only for local foundation preflight.

```python
@dataclass(frozen=True)
class EngineRequestV1:
    schema_version: int
    request_id: str
    command: EngineCommand
    created_at: str
    app_support_root: str
    config_path: str | None
    payload: PreflightPayloadV1
```

Task 1 does not implement placeholder payloads or decoders for future commands. Task 2 adds the remaining Section 3.2 commands and freezes schema v1 before any local beta leaves development.

Start the Swift package with `defaultLocalization: "en"`, macOS 26, arm64 products, `ResearchRadarCore`, `ResearchRadarAppFeature`, `ResearchRadarExecutable`, and the test-only `ResearchRadarProcessFixture`. The assembler later copies only an explicit allowlist and must never copy the fixture executable.

Run:

```bash
uv run --extra dev pytest tests/test_app_bridge_protocol.py -q
swift test --package-path apps/macos/ResearchRadar --filter EngineProtocolTests
```

Expected before implementation: missing-module/type failures. Expected after implementation: both suites pass and encode identical snake-case fixtures.

- [ ] **Step 2: Implement the localization foundation before user-facing AppKit copy**

Implement `AppLanguagePreference`, `ResolvedAppLanguage`, `AppLanguageResolver`, `AppStringKey`, `LocalizationStore`, and the foundation entries in `UserFacingErrorCatalog`.

`AppLanguageResolver.resolve()` handles `en`, `en-*`, `zh`, and every `zh-*`; unsupported or empty preference lists resolve to English. `LocalizationStore` observes locale changes only while preference is `system`, publishes the resolved locale to SwiftUI, and supplies the same strings to `AppDelegate` menus and tooltip. Task 1 keeps the preference in memory; Task 2 persists it in `AppConfigurationV1`.

Populate both `en` and `zh-Hans` values for the foundation window, Open, Cancel, Quit, Ready, Failed, and Open Diagnostics. Test missing catalog keys, immediate in-memory language switching, unsupported-system fallback, and AppKit/SwiftUI equality.

Run:

```bash
swift test --package-path apps/macos/ResearchRadar --filter AppLanguageTests
swift test --package-path apps/macos/ResearchRadar --filter LocalizationStoreTests
```

Expected: PASS without changing any report language field.

- [ ] **Step 3: Implement local-only preflight and the process-session handshake**

`runner.py` handles only `preflight(live_probe=false)` in Task 1. It verifies the writable owner-only App Support root, engine version, sanitized environment, terminal-artifact paths, and real frozen imports for `cryptography`, `keyring` plus macOS backend discovery, `PIL`, `pypdf`, `yaml`, and the ResearchRadar foundation bridge. The result records each dependency as available without exposing private paths. It does not inspect providers, secrets, Codex, PDFKit, or delivery settings, and it does not import the full CLI or research pipeline.

The executable sequence is fixed:

1. parse and validate request paths and immediately capture the native App parent PID with `os.getppid()`; if it is already reparented or cannot be registered with `kqueue`, treat that as `parent_lost`;
2. install signal handling and arm a macOS `kqueue` `EVFILT_PROC`/`NOTE_EXIT` watcher for that parent;
3. call `os.setsid()`;
4. atomically append and `fsync` the first `started` event;
5. only then permit a handler to create child processes;
6. write exactly one atomic `result.json` or `error.json`.

The parent watcher exists only while an engine job is active and blocks on the kernel event; it is not a timer or polling loop. If the App exits, the engine records `parent_lost` when its terminal path remains writable, sends TERM to its own process group, escalates to KILL after five seconds where needed, and exits without starting or retrying any delivery. Install SIGTERM/SIGINT handling before dispatch. A user-cancelled request emits `cancelled` when the event file remains writable and exits with code 130. The bridge never executes a shell string.

Run: `uv run --extra dev pytest tests/test_app_bridge_events.py tests/test_app_bridge_runner.py -q`

Expected: PASS for successful preflight, crash before `started`, cancellation, redaction, monotonic events, and mutually exclusive terminal files.

- [ ] **Step 4: Write process-tree supervision tests before implementing the supervisor**

The test fixture accepts explicit modes: `normal`, `crash-before-session`, `wait`, `ignore-term-child`, and `parent-exit`. In process-tree modes it launches a child and grandchild, writes their PIDs to a test artifact, and never enters an App bundle allowlist. The parent-exit fixture uses a disposable proxy parent so the test can simulate an App crash without terminating the Swift test process.

Add tests:

```swift
func testFoundationPreflightReadsStartedAndResult() async throws
func testCancelBeforeStartedTerminatesOnlyEnginePID() async throws
func testCancelAfterStartedTerminatesProcessGroup() async throws
func testIgnoringTermEscalatesToKill() async throws
func testExitWaitsUntilChildAndGrandchildAreGone() async throws
func testParentExitStopsEngineChildAndGrandchild() async throws
func testCrashReconcilesResultOrErrorArtifact() async throws
func testCancelledSlotCanRunNextPreflight() async throws
```

Run: `swift test --package-path apps/macos/ResearchRadar --filter EngineProcessSupervisorTests`

Expected: FAIL because the supervisor does not exist.

- [ ] **Step 5: Implement the final PID/process-group cancellation contract**

Launch the engine directly with `Process`, never through a shell. Save the engine PID immediately. `EventTailer` marks session establishment only after reading the fsynced `started` event; then verify `getpgid(pid) == pid`.

Before `started`, cancellation sends TERM to the engine PID. This is safe because the bridge contract forbids child creation before the started event is durable. After `started`, cancellation signals `-pgid`. Wait five seconds, escalate to KILL, reap the engine, then probe the former process group with signal 0 until it is absent. Do not release the supervisor slot while a descendant survives. The Python parent watcher provides the same process-group cleanup when the Swift App cannot send Cancel because it crashed or was killed. Task 2 reconciles a `parent_lost` terminal error as `interrupted`; it never automatically reruns research or creates delivery jobs. Create `EventTailer` when a run starts and release it immediately after terminal reconciliation; no tailer exists between jobs.

Continuously drain stdout and stderr to avoid pipe backpressure. Keep only the newest 1 MiB from each stream, redact before persistence, and never show these bytes in the foundation window.

Run: `swift test --package-path apps/macos/ResearchRadar --filter EngineProcessSupervisorTests`

Expected: PASS, including the ignored-TERM fixture and a second run after cancellation.

- [ ] **Step 6: Build the minimal NSStatusItem App and singleton window**

`AppDelegate` sets activation policy `.accessory`, owns one `NSStatusItem`, and receives `LocalizationStore`, `EngineProcessSupervisor`, and `WindowCoordinator` from `AppContainer`. The status button uses SF Symbol `scope` and a dynamic localized tooltip.

Use `sendAction(on: [.leftMouseUp, .rightMouseUp])`: left click calls `WindowCoordinator.show()`; right click builds a native menu from current localized strings. The foundation menu contains Open and Quit only. Task 2 adds Run Now and Pause All when those actions exist. This precise click split is why v1 uses `NSStatusItem` rather than `MenuBarExtra`.

The singleton window contains one preflight action, progress, Cancel while running, and localized result/error copy. Closing hides the window and leaves the status item running; a second left click reuses the same `NSWindow` object.

Run: `swift test --package-path apps/macos/ResearchRadar --filter FoundationWindowTests`

Expected: PASS for left/right click dispatch, singleton reuse, tooltip refresh, and no raw engine message in an alert.

- [ ] **Step 7: Freeze, copy, inspect, measure, and ad-hoc sign the minimal bundle**

Add `.build/`, `.swiftpm/`, and `*.xcresult` to `.gitignore`. Create a new `app-build` optional dependency containing `pyinstaller>=6.22,<7` and lock the exact version. Fail early unless the toolchain preflight reports arm64, Swift 6.3 or newer, and a macOS 26 SDK. Build scripts set SwiftPM and Clang module-cache paths inside ignored project `.build/` directories; they do not populate an additional App-specific environment under the user's home directory. `build_macos_engine.sh` creates the complete arm64 `onedir` tree under ignored `build/` and `dist/` paths. `assemble_macos_app.sh` uses `/usr/bin/ditto` for the engine tree and copies only the Swift app executable, the deterministic SwiftPM resource bundle `ResearchRadar_ResearchRadarAppFeature.bundle`, and the engine allowlist into `dist/ResearchRadar.app`. Place the resource bundle under `Contents/Resources/` and fail assembly when it is absent; otherwise `Bundle.module` localization would work in `swift run` but fail in the staged App.

`verify_macos_bundle.py` performs these release gates:

1. enumerate every source and staged symlink as `(relative_path, link_target, resolved_relative_target)` and require identical manifests;
2. require every resolved symlink target to remain inside its respective engine root;
3. identify Mach-O executables, `.dylib`, and Python extensions recursively with `/usr/bin/file`;
4. parse `/usr/bin/otool -L` and `LC_RPATH` entries;
5. allow `/System/Library`, `/usr/lib`, or a tokenized dependency that resolves inside the staged bundle;
6. reject `/opt/homebrew`, `/usr/local`, `.venv`, the source checkout, `/private/tmp`, missing targets, and unresolved tokenized dependencies;
7. reject the test fixture executable and secret/private-path fixture strings.

Ad-hoc sign nested Mach-O files deepest-first, then the outer App, without Hardened Runtime for this local foundation build. A test-only resource sampler writes ignored `dist/macos-resource-report.json`; the App itself never samples resources in the background. The report records:

- macOS, architecture, Swift, SDK, Python patch version, and PyInstaller version;
- logical sizes for Swift `.build/`, PyInstaller work output, the frozen engine, and the final `.app`;
- preflight duration and first-window-visible duration;
- timestamped RSS and CPU samples across five idle minutes;
- the idle ResearchRadar descendant process inventory;
- the quiescent App RSS after each of 20 preflight/cancel cycles;
- a bounded `/usr/bin/leaks` summary;
- engine, child, and grandchild liveness after every cancellation.

These are measured baselines, not invented release limits. The report distinguishes development-only disk use from the installed App size and must capture sizes without following symlinks into double counting. Validate with:

```bash
codesign --verify --deep --strict --verbose=2 dist/ResearchRadar.app
PATH=/usr/bin:/bin ./script/verify_macos_bundle.py \
  --source-engine dist/macos-engine/research-radar-engine \
  --app dist/ResearchRadar.app
```

Tests create synthetic safe/escaping symlink trees and mocked `otool` output. Run: `uv run --extra dev pytest tests/test_macos_bundle_verifier.py -q`.

- [ ] **Step 8: Run the staged foundation App on the macOS 26 arm64 development machine**

`stage_macos_app.sh` builds release Swift products, freezes the engine, assembles with `ditto`, verifies, signs, and writes `dist/ResearchRadar.app`. Foundation tests use temporary roots; the manual App launch uses `~/Library/Application Support/ResearchRadar-Dev/`. Launch from Finder semantics with `/usr/bin/open -n`, trigger preflight from the window, cancel one long fixture run, force the proxy App parent to exit once, and confirm no fixture PID survives. The staged preflight must prove every required dependency import resolves from the frozen bundle, not the project environment.

Run:

```bash
./script/stage_macos_app.sh
PATH=/usr/bin:/bin dist/ResearchRadar.app/Contents/Helpers/research-radar-engine/research-radar-engine \
  --request /private/tmp/rr-foundation/request.json \
  --events /private/tmp/rr-foundation/progress.jsonl \
  --result /private/tmp/rr-foundation/result.json \
  --error /private/tmp/rr-foundation/error.json
/usr/bin/open -n dist/ResearchRadar.app
```

Expected: the App starts without the repository on `PATH`, the window displays localized Ready, and bundle inspection reports no private dependency.

- [ ] **Step 9: Run Task 1 gates and create the first signed-off commit**

```bash
.venv/bin/pytest tests/test_app_bridge_protocol.py tests/test_app_bridge_events.py \
  tests/test_app_bridge_runner.py tests/test_macos_bundle_verifier.py
swift test --package-path apps/macos/ResearchRadar
./script/stage_macos_app.sh
.venv/bin/ruff check src tests
.venv/bin/research-radar privacy scan
git diff --check
git add .gitignore pyproject.toml uv.lock src/research_radar/app_bridge \
  tests/test_app_bridge_protocol.py tests/test_app_bridge_events.py \
  tests/test_app_bridge_runner.py tests/test_macos_bundle_verifier.py \
  apps/macos/ResearchRadar packaging/macos script/build_macos_engine.sh \
  script/assemble_macos_app.sh script/stage_macos_app.sh \
  script/verify_macos_bundle.py
git diff --cached --check
git commit -s -m "[feat] Add lightweight macOS app foundation"
```

Stop if the minimal macOS 26 arm64 App cannot pass its local foundation gates, cannot import the required frozen dependencies, leaves any helper process idle, performs fixed polling, or shows sustained unexplained RSS growth across repeated preflight/cancel cycles. Present the measured installed-App, frozen-engine, development-cache, launch-time, five-minute idle samples, 20-cycle quiescent RSS sequence, leak summary, and descendant checks at this checkpoint. If the measured cost is not acceptable to the user, revisit the bundle boundary before Task 2 instead of hiding it behind an invented threshold. Do not begin the durable research workflow on an unproven or unaccepted bundle.

---

### Task 2: Add Durable Research Workflow

#### Phase 2A: Complete Engine Bridge And Native PDF Foundation

**Deliverable:** The proven App bundle gains the full four-command bridge, existing research/publishing services, native PDF helper, typed durable configuration, reviewed-topic onboarding, fake daily execution, report indexing, scheduling, and crash-safe queue integration. A user can create a topic and produce a fake-provider `article_draft.json` plus `wechat.html` without Terminal or YAML, then restart the App and reopen the report.

**Files:**
- Create: `src/research_radar/application/__init__.py`
- Create: `src/research_radar/application/daily.py`
- Create: `src/research_radar/application/wechat.py`
- Modify: `src/research_radar/app_bridge/__main__.py`
- Modify: `src/research_radar/app_bridge/protocol.py`
- Modify: `src/research_radar/app_bridge/events.py`
- Create: `src/research_radar/app_bridge/configuration.py`
- Create: `src/research_radar/app_bridge/pdf_helper.py`
- Modify: `src/research_radar/app_bridge/runner.py`
- Modify: `src/research_radar/cli.py`
- Modify: `src/research_radar/pipeline/progress.py`
- Modify: `src/research_radar/pipeline/daily.py`
- Modify: `src/research_radar/analysis/model_cache.py`
- Modify: `src/research_radar/analysis/figures.py`
- Modify: `packaging/macos/research-radar-engine.spec`
- Modify: `script/build_macos_engine.sh`
- Create: `tests/test_application_daily.py`
- Create: `tests/test_application_wechat.py`
- Modify: `tests/test_app_bridge_protocol.py`
- Modify: `tests/test_app_bridge_events.py`
- Modify: `tests/test_app_bridge_runner.py`
- Create: `tests/test_app_bridge_pdf_helper.py`
- Modify: `tests/test_model_cache.py`
- Modify: `apps/macos/ResearchRadar/Package.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Protocol/EngineProtocol.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarPDFHelper/PDFHelperMain.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarPDFCore/PDFOperations.swift`
- Modify: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/EngineProtocolTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarPDFCoreTests/PDFOperationsTests.swift`

**Interfaces:**
- Consumes: Task 1's frozen engine, protocol envelopes, supervisor, localization foundation, singleton App shell, and bundle verifier; existing `AppConfig`, `run_daily()`, `bootstrap_topic_draft()`, `publish_email_run()`, `WeChatDraftClient`, `render_wechat_publish_html()`, `ProgressWriter`, and figure crop quality policy.
- Produces: `execute_daily(request: DailyExecutionRequest) -> Path`, `publish_wechat_run(request: WeChatPublishRequest) -> WeChatPublishOutcome`, `load_app_configuration(path: Path, *, require_topics: bool) -> LoadedAppConfigurationV1`, all four production command handlers, and `PDFHelperClient.page_bbox()/render_crop()`. This phase completes and freezes schema v1 before beta use.

- [ ] **Step 1: Complete and freeze protocol fixtures for every production command**

Keep the common envelope and preflight types created in Task 1. Add the `bootstrap_topic`, `run_daily`, and `retry_delivery` command/payload types plus one canonical request/result fixture for each and the rejection cases below. Schema v1 becomes frozen at the end of this phase.

```python
def test_request_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    write_json(path, {"schema_version": 2, "request_id": str(uuid4()), "command": "preflight", "payload": {"live_probe": False}})
    with pytest.raises(ConfigError, match="Unsupported app engine schema version: 2"):
        parse_engine_request(path)


def test_request_rejects_secret_values(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    write_json(path, valid_request(payload={"api_key_value": "do-not-store"}))
    with pytest.raises(ConfigError, match="must not contain secret values"):
        parse_engine_request(path)
```

- [ ] **Step 2: Run protocol tests before enabling production handlers**

Run: `uv run --extra dev pytest tests/test_app_bridge_protocol.py -q`

Expected: Task 1 envelope/preflight cases remain PASS. The new command parsing fixtures PASS, while dispatch integration tests remain RED with `command_unavailable` until the production handlers in the following steps are connected.

- [ ] **Step 3: Complete command-specific payload validation and freeze schema v1**

```python
ENGINE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EngineRequestV1:
    schema_version: int
    request_id: str
    command: EngineCommand
    created_at: str
    app_support_root: str
    config_path: str | None
    payload: PreflightPayloadV1 | BootstrapTopicPayloadV1 | RunDailyPayloadV1 | RetryDeliveryPayloadV1


def parse_engine_request(path: Path) -> EngineRequestV1:
    data = read_json(path)
    _reject_unknown_keys(data, REQUEST_KEYS)
    _reject_secret_value_keys(data)
    _require_schema_version(data, ENGINE_SCHEMA_VERSION)
    return _parse_command_payload(data)
```

Retain the explicit Task 1 parsers. Require a non-null, contained `config_path` for bootstrap, daily, delivery retry, and `preflight(live_probe=true)`. Do not use permissive `**mapping` construction and do not silently coerce strings to booleans or integers. `RunDailyPayloadV1.model_cache_limit_bytes` accepts null or a positive integer only.

- [ ] **Step 4: Add PDF targets and complete Swift round-trip fixtures**

Extend the existing Task 1 package with PDF targets:

```swift
// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "ResearchRadar",
    defaultLocalization: "en",
    platforms: [.macOS("26.0")],
    products: [
        .executable(name: "ResearchRadar", targets: ["ResearchRadarExecutable"]),
        .library(name: "ResearchRadarCore", targets: ["ResearchRadarCore"]),
        .library(name: "ResearchRadarAppFeature", targets: ["ResearchRadarAppFeature"]),
        .library(name: "ResearchRadarPDFCore", targets: ["ResearchRadarPDFCore"]),
        .executable(name: "ResearchRadarPDFHelper", targets: ["ResearchRadarPDFHelper"]),
    ],
    targets: [
        .target(name: "ResearchRadarCore"),
        .target(name: "ResearchRadarAppFeature", dependencies: ["ResearchRadarCore"], resources: [.process("Resources")]),
        .executableTarget(name: "ResearchRadarExecutable", dependencies: ["ResearchRadarAppFeature"]),
        .target(name: "ResearchRadarPDFCore"),
        .executableTarget(name: "ResearchRadarPDFHelper", dependencies: ["ResearchRadarPDFCore"]),
        .testTarget(name: "ResearchRadarCoreTests", dependencies: ["ResearchRadarCore"]),
        .testTarget(name: "ResearchRadarPDFCoreTests", dependencies: ["ResearchRadarPDFCore"]),
    ]
)
```

```swift
public struct EngineRequestV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let command: EngineCommand
    public let createdAt: Date
    public let appSupportRoot: String
    public let configPath: String?
    public let payload: EnginePayloadV1
}
```

Store one canonical fixture per command under `apps/macos/ResearchRadar/Tests/Fixtures/Protocol/`. Decode and re-encode it in Swift; parse the same file in pytest. Assert exact enum values and snake-case keys.

Run: `swift test --package-path apps/macos/ResearchRadar --filter EngineProtocolTests`

Expected: PASS for all four final command payloads and snake-case keys.

- [ ] **Step 5: Extend event coverage to the full public stage mapping**

```python
def test_event_writer_redacts_and_sequences(tmp_path: Path) -> None:
    writer = EngineEventWriter(tmp_path / "progress.jsonl", request_id=REQUEST_ID)
    writer.write(type="started", message="token=super-secret")
    writer.write(type="stage_changed", stage="discovery", status="running")
    events = read_jsonl(tmp_path / "progress.jsonl")
    assert [event["sequence"] for event in events] == [1, 2]
    assert "super-secret" not in json.dumps(events)
```

Retain Task 1's append/fsync/redaction implementation. Add fixtures for every mapping in Section 3.4 and verify unknown internal stages remain a `progress` event under the last known public stage rather than changing the wire enum.

Run: `uv run --extra dev pytest tests/test_app_bridge_events.py -q`

Expected: PASS.

- [ ] **Step 6: Extract shared daily orchestration from `cli.py` behind typed options**

```python
@dataclass(frozen=True)
class DailyRouteOverrides:
    global_provider: str | None = None
    global_model: str | None = None
    deepseek_provider: str | None = None
    gist_provider: str | None = None
    gist_model: str | None = None
    reader_provider: str | None = None
    reader_model: str | None = None
    verifier_provider: str | None = None
    verifier_model: str | None = None
    anchor_repair_provider: str | None = None
    anchor_repair_model: str | None = None
    localization_provider: str | None = None
    localization_model: str | None = None


@dataclass(frozen=True)
class DailyExecutionRequest:
    root: Path
    topic_id: str
    limit: int = 5
    deep_limit: int = 2
    language: str = "zh"
    model_cache: bool = True
    model_cache_limit_bytes: int | None = None
    route_overrides: DailyRouteOverrides = field(default_factory=DailyRouteOverrides)
    progress_listener: Callable[[dict[str, Any]], None] | None = None


def execute_daily(
    request: DailyExecutionRequest,
    *,
    config: AppConfig,
    secrets: SecretManager,
) -> Path:
    """Resolve the current routes/connectors and execute the existing pipeline."""
```

Move connector and route construction; do not duplicate it. `handle_run_daily()` constructs `DailyExecutionRequest`, calls `execute_daily()`, writes the optional run-dir output, and prints the same final line as before. Add a parity test that captures CLI fake-run artifacts before and after extraction and compares them byte-for-byte.

When `model_cache_limit_bytes` is null, cache behavior remains byte-for-byte compatible with the CLI. When a positive App value is present, a cache hit uses `os.utime()` to update only the app-owned cache entry's modification timestamp; eviction never relies on filesystem access-time semantics. A cache write or completed daily run prunes the oldest such regular cache files until the model-cache directory is within the user limit. Containment checks must exclude reports, source history, delivery artifacts, configuration, and job state. There is no periodic cache-maintenance process.

Add focused cache-policy tests proving that a null limit preserves the existing bytes and timestamps, a hit under an enabled limit updates only the contained cache entry timestamp, oldest entries are removed first, and reports/source history remain byte-identical.

Run: `uv run --extra dev pytest tests/test_application_daily.py tests/test_model_cache.py tests/test_cli.py tests/test_pipeline_fake.py -q`

Expected: PASS with unchanged CLI artifacts.

- [ ] **Step 7: Extract WeChat orchestration from `cli.py` without changing its public artifacts**

```python
@dataclass(frozen=True)
class WeChatPublishRequest:
    run_dir: Path
    title: str
    digest: str
    author: str
    thumb_media_id: str
    dry_run: bool = False


@dataclass(frozen=True)
class WeChatPublishOutcome:
    status: str
    draft_created: bool
    response: dict[str, object] | None


def publish_wechat_run(
    request: WeChatPublishRequest,
    *,
    secrets: SecretManager,
    client_factory: Callable[..., WeChatDraftClient] = WeChatDraftClient,
) -> WeChatPublishOutcome:
```

The extracted service keeps `wechat_publish.html`, media upload, request/result/error artifacts, and source-history updates identical. `handle_publish_wechat()` becomes argument mapping plus user-facing printing.

Run: `uv run --extra dev pytest tests/test_application_wechat.py tests/test_cli.py tests/test_compose.py tests/test_source_history.py -q`

Expected: PASS and byte-identical WeChat preview/publish HTML fixtures.

- [ ] **Step 8: Add an optional sanitized pipeline event listener**

Modify `ProgressWriter.__init__` to accept `listener: Callable[[dict[str, Any]], None] | None = None`. Invoke it only with the already-redacted event dictionary after the file append. Listener failure records no secret and must not change CLI behavior. Thread this optional listener through `run_daily()` and `DailyExecutionRequest`.

Test that the listener receives `discovery`, `reader`, `verifier`, `localization`, and `artifacts` transitions while `run_progress.jsonl` remains byte-equivalent when no listener is supplied.

Run: `uv run --extra dev pytest tests/test_progress.py tests/test_application_daily.py -q`

Expected: PASS.

- [ ] **Step 9: Implement App configuration conversion and preflight**

`configuration.py` validates `app-config.json`, resolves every path under Application Support, and returns `LoadedAppConfigurationV1`. It may translate `providers[]` and `routes[]` into the keyed mapping expected by existing `parse_config()`, but it must not maintain a second research configuration model in Python.

Preflight returns one row per required capability:

```python
@dataclass(frozen=True)
class PreflightCheckV1:
    id: str
    status: str  # ready, optional, action_required, unavailable
    message: str
    provider: str | None = None
    model: str | None = None
```

Local preflight checks directory writability, secret presence, absolute executable validity, PDF helper executability, configured routes, and enabled delivery requirements. `live_probe=true` additionally performs the existing small structured provider probe. No response body longer than 200 redacted characters enters the result.

Run: `uv run --extra dev pytest tests/test_app_bridge_protocol.py tests/test_app_bridge_runner.py -q`

Expected: PASS and no secret values in serialized results.

- [ ] **Step 10: Implement the four-command bridge dispatcher**

```python
@dataclass(frozen=True)
class EnginePaths:
    request_path: Path
    events_path: Path
    result_path: Path
    error_path: Path
    pdf_helper_path: Path | None


class CommandHandler(Protocol):
    def __call__(
        self,
        request: EngineRequestV1,
        *,
        config: LoadedAppConfigurationV1 | None,
        secrets: SecretManager,
        events: EngineEventWriter,
    ) -> EngineResultV1: ...


@dataclass(frozen=True)
class BridgeDependencies:
    preflight: CommandHandler
    bootstrap_topic: CommandHandler
    run_daily: CommandHandler
    retry_delivery: CommandHandler
    clock: Callable[[], datetime]

    @classmethod
    def production(cls) -> BridgeDependencies: ...


def run_engine_request(
    request: EngineRequestV1,
    paths: EnginePaths,
    *,
    dependencies: BridgeDependencies | None = None,
) -> EngineResultV1:
```

`BridgeDependencies.production()` returns the four local handlers. The runner leaves `config=None` only for `preflight(live_probe=false)`; every other path requires and loads the validated App configuration before dispatch. The handlers call `execute_daily(config=config.research)`, `bootstrap_topic_draft()`, `publish_wechat_run()`, and `publish_email_run()`; tests replace one handler without monkeypatching global functions. Each handler checks that the payload variant matches its command before doing any I/O.

Before dispatching `run_daily`, compare `payload.report_date` with `dependencies.clock().astimezone().date().isoformat()`. v1 does not backfill historical report dates; a mismatch returns `invalid_report_date` before discovery starts. This keeps the queue key aligned with the actual `RunManifest.report_date`.

`__main__.py` accepts only:

```text
research-radar-engine --request <path> --events <path> --result <path> --error <path> [--pdf-helper <path>]
```

`--pdf-helper` is optional for local preflight, provider preflight, topic bootstrap, and delivery retry. It is required for `run_daily`; a missing, non-executable, or escaping path returns `missing_executable` before discovery starts.

Retain Task 1's `setsid()`, fsynced-first-`started` event, SIGTERM/SIGINT, atomic terminal-file, and no-shell contracts unchanged. The newly enabled handlers may start provider children only after the common runner has completed that handshake.

Run: `uv run --extra dev pytest tests/test_app_bridge_runner.py -q`

Expected: all four fake commands PASS; retry delivery invokes exactly one requested channel.

- [ ] **Step 11: Write PDFKit helper tests before implementing the helper**

Generate a two-column test PDF in XCTest using CoreGraphics. Assert:

```swift
func testExtractPageWordsUsesTopLeftPointCoordinates() throws
func testRenderCropPreservesFullWidthFigure() throws
func testRejectsInputOutsideAllowedRoot() throws
func testRejectsOutputOutsideAllowedRoot() throws
```

Run: `swift test --package-path apps/macos/ResearchRadar --filter ResearchRadarPDFCoreTests`

Expected: FAIL because `PDFOperations` is missing.

- [ ] **Step 12: Implement PDFKit bbox extraction and crop rendering**

For each token range in `PDFPage.string`, use `selection(for:)` and `bounds(for:)`. Convert PDFKit bottom-left bounds to the top-left point convention exactly once:

```swift
let top = pageHeight - bounds.maxY
let bottom = pageHeight - bounds.minY
```

For rendering, convert the requested top-left crop back to PDF coordinates, render through `CGContext` at `dpi / 72.0`, and encode PNG with `NSBitmapImageRep`. Reject page indexes outside `1...pageCount`, non-positive crop dimensions, path escapes, symlinks leaving `allowed_root`, and output paths outside `allowed_root`.

Run: `swift test --package-path apps/macos/ResearchRadar --filter ResearchRadarPDFCoreTests`

Expected: PASS.

- [ ] **Step 13: Add the Python PDF helper adapter and preserve CLI fallback**

```python
class PDFHelperClient:
    def page_bbox(self, pdf_path: Path, page_number: int, *, allowed_root: Path) -> PdfPageBbox: ...
    def render_crop(self, pdf_path: Path, page_number: int, crop_box: PdfCropBox, destination: Path, *, dpi: int, allowed_root: Path) -> bool: ...
```

App-engine execution injects this client into figure extraction. Normal CLI execution continues to use the existing Poppler/pypdf/sips path, so the change cannot remove current functionality. Both paths feed the same `_pdf_caption_crop_box_from_bbox()` and `_rendered_crop_is_publishable()` decisions. Tests launch a fixture helper, verify one process per requested operation, and assert that success, malformed result, timeout, and cancellation all leave no helper process.

Run: `uv run --extra dev pytest tests/test_app_bridge_pdf_helper.py tests/test_figures.py -q`

Expected: PASS; helper and CLI fallback produce equivalent point-space crop requests.

- [ ] **Step 14: Re-freeze the expanded engine and preserve the Task 1 bundle contract**

Update the existing PyInstaller spec for the full bridge and PDF adapter, rebuild the complete `onedir`, and run the same symlink, Mach-O, private-path, and sanitized-`PATH` verification introduced in Task 1. Stage `ResearchRadarPDFHelper` under `Contents/Helpers/` and never replace `ditto` with a symlink-flattening copy.

Update `dist/macos-resource-report.json` after staging the expanded engine. Record the change from the Task 1 baseline and name the added engine/PDF functionality responsible for package-size or process changes; do not introduce a guessed hard limit.

Run:

```bash
./script/build_macos_engine.sh
PATH=/usr/bin:/bin dist/macos-engine/research-radar-engine/research-radar-engine \
  --request /private/tmp/rr-app-smoke/request.json \
  --events /private/tmp/rr-app-smoke/progress.jsonl \
  --result /private/tmp/rr-app-smoke/result.json \
  --error /private/tmp/rr-app-smoke/error.json \
  --pdf-helper "$(swift build --package-path apps/macos/ResearchRadar --show-bin-path)/ResearchRadarPDFHelper"
```

Expected: all four fixture commands succeed with no import from the source checkout and no Homebrew/Poppler lookup.

- [ ] **Step 15: Run the Phase 2A gate before adding durable UI state**

```bash
uv run --extra dev pytest tests/test_application_daily.py tests/test_application_wechat.py \
  tests/test_app_bridge_protocol.py tests/test_app_bridge_events.py \
  tests/test_app_bridge_runner.py tests/test_app_bridge_pdf_helper.py tests/test_figures.py
swift test --package-path apps/macos/ResearchRadar
uv run --extra dev ruff check src tests
uv run research-radar privacy scan
git diff --check
```

Expected: PASS. Do not create an intermediate commit; Task 2 is reviewed and committed as one independently usable workflow after Phase 2B.

---

#### Phase 2B: Durable App Runtime, Queue, Scheduling, And Onboarding

**Deliverable:** The Task 1 shell now persists configuration, onboards one or more reviewed topics, starts at login by consent, schedules and coalesces fake daily jobs, indexes reports, and recovers interrupted state while reusing the already-proven process supervisor.

**Files:**
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Models/AppConfiguration.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Localization/AppLanguage.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Models/AppRuntimeState.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Models/JobRecord.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Models/ReportRecord.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Models/ScheduleRecord.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Persistence/JSONCoding.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Persistence/AtomicJSONStore.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Queue/JobQueue.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarCore/Scheduling/ScheduleEvaluator.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarExecutable/ResearchRadarMain.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/ResearchRadarScene.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/AppDelegate.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/AppContainer.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/App/WindowCoordinator.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Stores/AppStore.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization/LocalizationStore.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization/UserFacingErrorCatalog.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/EngineProcessSupervisor.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/EventTailer.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/KeychainStore.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/LoginItemService.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/LegacyStateMigrationService.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/ScheduleCoordinator.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/ReportIndexStore.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/StorageUsageService.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/AppRootView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Onboarding/OnboardingView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Onboarding/ProviderPreflightView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Onboarding/TopicReviewView.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/AtomicJSONStoreTests.swift`
- Modify: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/AppLanguageTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/DurableStateTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/JobQueueTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/ScheduleEvaluatorTests.swift`
- Modify: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/EngineProcessSupervisorTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/KeychainStoreTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/OnboardingTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/LegacyStateMigrationServiceTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/ScheduleCoordinatorTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/StorageUsageServiceTests.swift`
- Modify: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/FoundationWindowTests.swift`
- Modify: `apps/macos/ResearchRadar/Package.swift`

**Interfaces:**
- Consumes: Task 1's `EngineRequestV1`, `EngineEventV1`, `EngineResultV1`, `EngineErrorV1`, bundled engine path, process supervisor, localization store, and singleton status-item/window shell; Phase 2A's full command handlers and native PDF helper.
- Produces: `AppStore`, `JobQueue`, `ScheduleEvaluator`, durable supervisor integration, Keychain/Login Item services, reviewed-topic onboarding, on-demand storage usage/cache cleanup, and the report index used by Task 3 views.

Extend `Package.swift` with these product and target entries before adding app sources:

```swift
.library(name: "ResearchRadarAppFeature", targets: ["ResearchRadarAppFeature"]),
.executable(name: "ResearchRadar", targets: ["ResearchRadarExecutable"]),

.target(name: "ResearchRadarAppFeature", dependencies: ["ResearchRadarCore"]),
.executableTarget(name: "ResearchRadarExecutable", dependencies: ["ResearchRadarAppFeature"]),
.testTarget(name: "ResearchRadarAppFeatureTests", dependencies: ["ResearchRadarAppFeature"]),
```

`ResearchRadarMain.swift` contains only `@main` and returns `ResearchRadarScene` from the feature library. All stateful/tested code stays outside the executable target.

The cross-service interfaces used by this task are fixed before view work begins:

```swift
public actor ReportIndexStore {
    public func allReports() throws -> [ReportRecordV1]
    public func upsert(_ report: ReportRecordV1) throws
    public func updateDelivery(reportID: UUID, delivery: DeliveryRecordV1) throws
}

@MainActor
public final class ScheduleCoordinator {
    public func start()
    public func stop()
    public func evaluateDueSchedules(now: Date) async
    public func runNow(topicID: String) async throws
}

public actor StorageUsageService {
    public func snapshot() throws -> StorageUsageSnapshot
    public func clearModelCache() throws -> StorageUsageSnapshot
}

@MainActor
public final class WindowCoordinator {
    public func attach(_ window: NSWindow)
    public func show(mode: WindowMode)
    public func hide()
}
```

`AppContainer` constructs exactly one localization store, persistent store, queue, report index, process supervisor, schedule coordinator, storage usage service, Keychain store, login-item service, migration service, and window coordinator. Task 3 adds one notification service. Views receive these instances through `AppStore`; they never construct services or perform persistence directly.

- [ ] **Step 1: Define durable Swift value models and legal transitions in tests**

```swift
public struct JobRecordV1: Codable, Equatable, Identifiable, Sendable {
    public let schemaVersion: Int
    public let id: UUID
    public let kind: JobKind
    public let topicID: String
    public let reportDate: String
    public let deliveryChannel: DeliveryChannel?
    public let trigger: JobTrigger
    public var state: JobState
    public var stage: EngineStage?
    public var attemptCount: Int
    public var jobDirectory: String
    public var runDirectory: String?
    public var createdAt: Date
    public var startedAt: Date?
    public var completedAt: Date?
    public var error: RedactedEngineErrorV1?
}
```

Tests must reject delivery jobs without a channel, invalid state transitions such as `succeeded -> running`, non-v1 files with a migration message rather than silent defaults, and any attempt to encode schedules inside `AppConfigurationV1`. Round-trip each of the five top-level durable files through the shared coder and assert its schema version. Also assert that `uiLanguage` round-trips independently from every topic's `reportLanguage`, and that changing one does not rewrite the other.

Run: `swift test --package-path apps/macos/ResearchRadar --filter ResearchRadarCoreTests`

Expected before implementation: FAIL because the models do not exist.

- [ ] **Step 2: Implement owner-only atomic JSON persistence**

```swift
public actor AtomicJSONStore {
    public func read<T: Decodable & Sendable>(_ type: T.Type, from url: URL) throws -> T
    public func write<T: Encodable & Sendable>(_ value: T, to url: URL) throws
}
```

Write to a sibling `.<filename>.<uuid>.tmp`, call `FileHandle.synchronize()`, set POSIX mode `0600`, then `FileManager.replaceItemAt` or `moveItem` on first write. Parent directories are `0700`. A failed decode leaves the original bytes untouched and reports the exact file plus supported schema version without echoing content.

Run: `swift test --package-path apps/macos/ResearchRadar --filter AtomicJSONStoreTests`

Expected: PASS for atomic replacement, permission bits, and corrupted-file preservation.

- [ ] **Step 3: Implement the pure queue reducer and coalescing tests**

```swift
public actor JobQueue {
    public func enqueueResearch(topicID: String, reportDate: String, trigger: JobTrigger) async throws -> EnqueueResult
    public func enqueueDelivery(runDirectory: URL, topicID: String, reportDate: String, channel: DeliveryChannel) async throws -> EnqueueResult
    public func nextPending() async -> JobRecordV1?
    public func transition(jobID: UUID, to state: JobState, stage: EngineStage?, error: RedactedEngineErrorV1?) async throws
    public func recoverInterruptedJobs(results: EngineArtifactResolving) async throws
}
```

Test these decisions explicitly:

- same research topic/report date pending or running -> return existing job;
- same delivery channel/run pending or running -> return existing job;
- failed/cancelled -> Retry creates a new request UUID and increments attempt count;
- successful research -> enqueue only enabled channels;
- research failure -> enqueue no channel;
- unknown delivery -> never retry automatically;
- queue order is FIFO and only one record can be running.

Run: `swift test --package-path apps/macos/ResearchRadar --filter JobQueueTests`

Expected: PASS.

- [ ] **Step 4: Implement deterministic daily schedule evaluation**

```swift
public struct ScheduleEvaluator: Sendable {
    public func dueResearchJobs(
        schedules: [DailyScheduleV1],
        topics: [TopicRecordV1],
        reports: [ReportRecordV1],
        queuedJobs: [JobRecordV1],
        now: Date,
        calendar: Calendar
    ) -> [DueResearchJob]
}
```

Tests cover before/after due time, disabled topic, paused topic, existing success, pending/running coalescing, wake after three missed days, daylight-saving transition, and system time-zone change. The wake case returns only today's latest due job.

Run: `swift test --package-path apps/macos/ResearchRadar --filter ScheduleEvaluatorTests`

Expected: PASS.

- [ ] **Step 5: Write durable supervisor-integration tests using Task 1's fixture**

Reuse the Task 1 fixture and already-proven TERM/KILL behavior. This phase tests durable queue/report integration rather than reimplementing process control:

```swift
func testSupervisorReadsEventsAndTerminalResult() async throws
func testOnlyOneEngineRunsAtATime() async throws
func testRestartReconcilesCompleteResultBeforeMarkingInterrupted() async throws
func testPartialFinalEventLineIsIgnored() async throws
func testSuccessfulDailyUpsertsReportBeforeDeliveryJobs() async throws
func testFailedDailyEnqueuesNoDelivery() async throws
```

Run: `swift test --package-path apps/macos/ResearchRadar --filter EngineProcessSupervisorTests`

Expected before implementation: FAIL because `EngineProcessSupervisor` is missing.

- [ ] **Step 6: Integrate the proven supervisor with durable jobs and report recovery**

```swift
public actor EngineProcessSupervisor {
    public func run(request: EngineRequestV1, jobDirectory: URL) async throws -> EngineResultV1
    public func cancel(requestID: UUID) async throws
    public func reconcileTerminalArtifacts(requestID: UUID, jobDirectory: URL) async throws -> ReconciledEngineTerminalState?
}
```

Launch `Contents/Helpers/research-radar-engine/research-radar-engine` directly with an argument array. Set only required environment keys (`HOME`, `LANG`, and `TMPDIR`). The absolute Codex executable remains a typed configuration field, not an environment variable; do not invoke `/bin/sh`, `zsh`, `env`, or inherit an interactive `PATH` for provider discovery.

Retain Task 1's session handshake, TERM/KILL escalation, descendant check, stream draining, and slot-release rules unchanged. Add event-to-job stage updates, terminal-artifact reconciliation, and report-index upsert. A successful daily result is persisted before channel jobs are enqueued; a missing or invalid `article_draft.json` keeps the research job failed and enqueues no delivery. After successful reconciliation, discard stdout/stderr and retain only small terminal metadata. For failures, retain bounded streams only for the newest failure of the same `(topic, job kind)`.

Run: `swift test --package-path apps/macos/ResearchRadar --filter EngineProcessSupervisorTests`

Expected: PASS with durable state recovered from terminal artifacts and no duplicate delivery job.

- [ ] **Step 7: Implement Keychain storage and cross-runtime compatibility**

```swift
public protocol SecretStoring: Sendable {
    func set(_ value: Data, account: String) throws
    func contains(account: String) throws -> Bool
    func remove(account: String) throws
}

public struct KeychainStore: SecretStoring {
    public static let service = "ResearchRadar"
}
```

Use generic-password items with service `ResearchRadar` and account equal to the existing secret name (`deepseek.api_key`, `web_search.api_key`, `wechat.app_id`, `wechat.app_secret`, `email.smtp_password`). Never provide a reveal action. A macOS integration test uses a unique `ResearchRadar.Tests.<uuid>` service, verifies Python `KeychainSecretBackend` can read the same test value, and removes only that test item.

Run: `swift test --package-path apps/macos/ResearchRadar --filter KeychainStoreTests`

Expected: PASS.

- [ ] **Step 8: Implement explicit Codex detection and fallback policy**

Candidate order is:

1. saved user-selected absolute executable path;
2. the current process's non-shell `PATH` lookup;
3. `/opt/homebrew/bin/codex`, `/usr/local/bin/codex`, and `$HOME/.local/bin/codex`;
4. `NSOpenPanel` selection initiated by the user.

Resolve symlinks, require a regular executable file, and store the absolute path. Do not silently replace a missing Codex verifier. The onboarding screen offers either Fix Codex Path or Use DeepSeek as Verifier. The fallback explicitly changes only the `verifier` route to `deepseek/deepseek-v4-flash` with the configured thinking/high provider settings and displays: `Reader and verifier will use the same provider, so review diversity is reduced.`

Run: `swift test --package-path apps/macos/ResearchRadar --filter OnboardingTests`

Expected: PASS for detection precedence and explicit fallback.

- [ ] **Step 9: Implement onboarding as a state machine, not view-driven side effects**

Use the durable `OnboardingStep` and snapshot types from Section 3.7:

```swift
@MainActor @Observable
final class AppStore {
    private(set) var configuration: AppConfigurationV1
    private(set) var queue: [JobRecordV1]
    private(set) var schedules: [DailyScheduleV1]
    private(set) var reports: [ReportRecordV1]
    var onboardingStep: OnboardingStep
    var windowMode: WindowMode
    var selectedTopicID: String?
    var schedulesPaused: Bool
}
```

The topic review form exposes display name, generated research focus, search queries, paper queries, included concepts, exclusions, and an independent `中文 / English` report-language selector. A new draft starts from `AppLanguageResolver.defaultReportLanguage(for: localizationStore.resolvedLanguage)`, but the user may change it before approval. Approve writes the typed topic into `app-config.json`; Back preserves the generated draft; Cancel discards it. Changing UI language after approval does not mutate the topic. The form never writes or displays YAML.

Provider preflight first checks secret presence locally. `Test Connections` explicitly runs `preflight` with `live_probe=true`. Enabled WeChat requires app id, app secret, and an existing thumb media id. The v1 form explains where that value comes from and accepts it as a setup prerequisite; uploading a new permanent thumbnail is outside the App v1. Enabled Email requires TLS/STARTTLS settings and its named password.

Run: `swift test --package-path apps/macos/ResearchRadar --filter OnboardingTests`

Expected: PASS for forward/back/cancel, UI/report-language independence, no-secret serialization, and preflight blocking rules.

- [ ] **Step 10: Add explicit legacy history import and duplicate-scheduler detection**

```swift
struct ImportSummary: Equatable, Sendable {
    let sourceFileCount: Int
    let rowCount: Int
}

struct LegacyStateMigrationService {
    func legacyScheduleTopics(launchAgentsDirectory: URL) throws -> Set<String>
    func importSourceHistory(from legacyRoot: URL, to workspaceRoot: URL) throws -> ImportSummary
}
```

`legacyScheduleTopics` reads plist files matching the existing exact label prefix and extracts a validated topic slug; it does not call `launchctl` or change files. `importSourceHistory` is offered only before the destination has any source-history row or report. It resolves both roots, accepts only regular non-symlink `*.jsonl` files under `<legacy-root>/data/source_history/`, validates every line as a JSON object, copies through the atomic store with owner-only permissions, and leaves the source unchanged. It does not import config, schedules, runs, cache, logs, or publisher artifacts.

Tests cover a valid import, malformed JSONL, source symlink escape, nonempty destination, no source-history directory, a matching legacy plist, an unrelated plist, and zero source mutations.

Run: `swift test --package-path apps/macos/ResearchRadar --filter LegacyStateMigrationServiceTests`

Expected: PASS.

- [ ] **Step 11: Implement on-demand storage usage and explicit model-cache cleanup**

`StorageUsageService` accepts the resolved App Support root and computes a snapshot only when called. It separately totals regular contained files under model cache, reports/runs, and retained job diagnostics; symlinks, path escapes, and unknown roots fail closed. It never runs a timer or file-system observer.

`clearModelCache()` requires a UI confirmation supplied by Task 3 and operates only on regular files resolved inside `workspace/cache/model_calls/`. It must not traverse or mutate reports, source history, delivery artifacts, configuration, queue, schedules, or report index. An enabled positive `modelCacheLimitBytes` remains an engine-side, post-hit/write policy; the native service does not run background eviction.

Run: `swift test --package-path apps/macos/ResearchRadar --filter StorageUsageServiceTests`

Expected: PASS for on-demand totals, empty/missing cache, contained cleanup, path-escape rejection, and byte-identical durable data.

- [ ] **Step 12: Implement login-item and one-shot schedule coordination**

Wrap `SMAppService.mainApp` behind:

```swift
public protocol LoginItemManaging: Sendable {
    var status: LoginItemStatus { get }
    func setEnabled(_ enabled: Bool) throws
}
```

Registration occurs only after the user turns on Start at Login. On launch and `NSWorkspace.didWakeNotification`, `ScheduleCoordinator` reads `AppRuntimeStateV1.schedulesPaused`; when false it calls the pure evaluator and enqueues due jobs, and when true it enqueues nothing. It then calculates the nearest future enabled schedule and installs one one-shot timer. Topic/schedule edits, pause/resume, significant clock or time-zone changes, sleep, and wake invalidate the existing timer and calculate one replacement. With no enabled schedule, no timer exists. Explicit Quit cancels the timer and does not leave another scheduling process.

Run: `swift test --package-path apps/macos/ResearchRadar --filter ScheduleCoordinatorTests`

Expected: PASS with a fake login service and deterministic clock, including exactly one timer for the nearest due schedule, no timer when disabled, and correct replacement after clock/time-zone/wake changes.

- [ ] **Step 13: Upgrade the foundation shell with operational actions**

Keep the Task 1 `NSStatusItem`, click handling, localization store, and singleton `NSWindow`. Replace the foundation-only view model with `AppStore`; extend the native right-click menu with Run Now and Pause All only after those actions exist. The tooltip receives localized one-line status from the current AppStore presentation.

`WindowCoordinator` stores a weak reference supplied by a tiny `NSViewRepresentable` window accessor. Closing the window hides it but leaves the menu-bar app running. `Cmd-Q` and Quit use the active-run confirmation: Keep App Open or Cancel Run and Quit. There is no second settings or report window.

Run: `swift test --package-path apps/macos/ResearchRadar --filter FoundationWindowTests`

Expected: PASS for singleton reuse and status copy mapping.

- [ ] **Step 14: Run the complete Task 2 gate and create the second signed-off commit**

```bash
swift test --package-path apps/macos/ResearchRadar
./script/build_macos_engine.sh
./script/stage_macos_app.sh
uv run --extra dev pytest tests/test_application_daily.py tests/test_application_wechat.py \
  tests/test_app_bridge_protocol.py tests/test_app_bridge_events.py \
  tests/test_app_bridge_runner.py tests/test_app_bridge_pdf_helper.py \
  tests/test_figures.py tests/test_model_cache.py tests/test_pipeline_fake.py
uv run --extra dev ruff check src tests
uv run research-radar privacy scan
git diff --check
git add src/research_radar/application src/research_radar/app_bridge \
  src/research_radar/cli.py src/research_radar/pipeline/progress.py \
  src/research_radar/pipeline/daily.py src/research_radar/analysis/figures.py \
  src/research_radar/analysis/model_cache.py \
  tests/test_application_daily.py tests/test_application_wechat.py \
  tests/test_app_bridge_protocol.py tests/test_app_bridge_events.py \
  tests/test_app_bridge_runner.py tests/test_app_bridge_pdf_helper.py tests/test_model_cache.py \
  apps/macos/ResearchRadar/Package.swift \
  apps/macos/ResearchRadar/Sources/ResearchRadarCore/Models \
  apps/macos/ResearchRadar/Sources/ResearchRadarCore/Localization \
  apps/macos/ResearchRadar/Sources/ResearchRadarCore/Persistence \
  apps/macos/ResearchRadar/Sources/ResearchRadarCore/Queue \
  apps/macos/ResearchRadar/Sources/ResearchRadarCore/Scheduling \
  apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature \
  apps/macos/ResearchRadar/Sources/ResearchRadarExecutable \
  apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/AtomicJSONStoreTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/DurableStateTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/JobQueueTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarCoreTests/ScheduleEvaluatorTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests \
  packaging/macos/research-radar-engine.spec script/build_macos_engine.sh
git diff --cached --check
git commit -s -m "[feat] Add durable macOS research workflow"
```

Before the commit, compare `dist/macos-resource-report.json` with Task 1. The gate fails on unexplained background processes, fixed polling, missing package-size attribution, or monotonic idle RSS growth; it does not fail against a guessed absolute RSS or bundle-size number.

---

### Task 3: Add Localized Editorial Experience

**Deliverable:** The App presents the approved immediately switchable English/Simplified Chinese compact/full experience, reads real local reports safely, exposes channel-specific recovery and localized diagnostics, ships as a macOS 26 arm64 local beta DMG, and passes final local resource/lifecycle gates without changing any existing report renderer.

**Files:**
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Today/CompactTodayView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Today/OperationalTimelineView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Today/DeliveryStatusView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Full/FullWorkspaceView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Full/TopicSidebarView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Full/ReportReaderView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Full/HistoryView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Full/SettingsView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Full/DiagnosticsView.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Components/StatusBadge.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views/Components/EmptyStateView.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization/LocalizationStore.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization/UserFacingErrorCatalog.swift`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Resources/en.lproj/Localizable.strings`
- Modify: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Resources/zh-Hans.lproj/Localizable.strings`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/ReportReaderPolicy.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/NotificationService.swift`
- Create: `apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Support/VisualTokens.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/AppStorePresentationTests.swift`
- Modify: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/LocalizationStoreTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/LocalizationCatalogTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/ReportReaderPolicyTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/DeliveryRecoveryTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/DiagnosticsRedactionTests.swift`
- Create: `apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/NotificationServiceTests.swift`
- Modify: `packaging/macos/Info.plist`
- Create: `packaging/macos/ResearchRadar.icns`
- Modify: `script/stage_macos_app.sh`
- Modify: `script/assemble_macos_app.sh`
- Create: `script/build_and_run.sh`
- Create: `script/package_macos_beta.sh`
- Create: `.codex/environments/environment.toml`
- Create: `docs/macos-app.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/architecture.md`
- Modify: `docs/security.md`
- Modify: `docs/usage.md`
- Modify: `docs/todo.md`

**Interfaces:**
- Consumes: Task 2's `AppStore`, queue, schedule coordinator, supervisor, report index, typed App/Report language settings, status item, and singleton window.
- Produces: the complete localized reader-facing app, independent WeChat/Email recovery, local beta bundle/scripts, final macOS 26 arm64 resource/lifecycle report, and user documentation.

```swift
enum AppNotificationEvent: Equatable, Sendable {
    case reportReady(topic: String)
    case partialDelivery(topic: String, channel: DeliveryChannel)
    case researchFailed(topic: String, stage: EngineStage)
    case deliveryUnknown(topic: String, channel: DeliveryChannel)
}

protocol NotificationScheduling: Sendable {
    func requestAuthorization() async throws -> Bool
    func send(_ event: AppNotificationEvent) async throws
}
```

`ReportReaderPolicy` is a pure URL decision object used by the `WKNavigationDelegate`; `NotificationService` is the only type that talks to `UNUserNotificationCenter`. Neither type reads raw engine logs or article text.

- [ ] **Step 1: Write full localization and presentation-state tests before building views**

```swift
func testCompletedPresentationUsesPaperHeadlineAndTwoLineSummary() async
func testRunningPresentationMapsInternalStagesToFourPublicSteps() async
func testPartialDeliveryKeepsReportReadyAndShowsOnlyFailedChannelRetry() async
func testCompactAndFullModesUseTheSameSelectedReport() async
func testUserFacingCopyDoesNotExposeInternalStatusFields() async
func testSystemChineseResolvesToSimplifiedChinese() async
func testUnsupportedSystemLanguageFallsBackToEnglish() async
func testManualLanguageChangeRefreshesMenuTooltipAndWindow() async
func testUILanguageDoesNotChangeApprovedTopicReportLanguage() async
func testNewTopicReportLanguageCanBeChangedBeforeApproval() async
```

Forbidden UI strings include `role=`, `status=`, `score=`, `reuse_status`, raw Python exception names, raw provider payloads, and absolute local paths.

`LocalizationCatalogTests` enumerates every `AppStringKey`, requires both `en` and `zh-Hans` values, verifies localized format arguments, and rejects sentence fragments that views would concatenate. `UserFacingErrorCatalog` must cover every stable code from Section 3.5 plus the unknown-code fallback. Existing raw technical messages remain available only to the redacted Diagnostics model.

Run:

```bash
swift test --package-path apps/macos/ResearchRadar --filter Localization
swift test --package-path apps/macos/ResearchRadar --filter AppStorePresentationTests
```

Expected before implementation: FAIL because presentation mapping is missing.

- [ ] **Step 2: Implement compact Today and the expandable operational timeline**

Compact Today contains, in order:

1. topic and next-run line;
2. current state or latest report paper headline;
3. a maximum two-line summary;
4. source/deep-read/verified-claim counts;
5. the four-step timeline;
6. Open Report and Run Now or Cancel actions;
7. channel delivery statuses.

The timeline has stable row heights and does not resize when a step changes state. Expanded rows may show duration, current paper title, and the localized `UserFacingErrorCatalog` explanation; they do not show the raw redacted engine message, prompts, evidence quotes, provider output, or audit metadata.

Every label/action/status comes from `LocalizationStore`; paper titles and report summaries remain in their report language. Use `withAnimation` only when Reduce Motion is off. Use native macOS 26 system materials and Liquid Glass without adding an older-system visual compatibility path.

Run: `swift test --package-path apps/macos/ResearchRadar --filter AppStorePresentationTests`

Expected: PASS.

- [ ] **Step 3: Implement full workspace without a card wall**

Use a `NavigationSplitView` with a light native topic/history sidebar and one open detail surface. The detail toolbar contains compact/full toggle, Run Now, Cancel when running, Open in Browser, and a menu for topic settings and diagnostics.

The report pane is dominant. Settings and diagnostics replace the detail pane; they do not open new persistent windows. Sidebar rows contain one icon, one title, and at most one secondary status line. Settings exposes `Follow System / 简体中文 / English`; selecting an option persists `AppConfigurationV1.uiLanguage` and updates the existing store immediately without recreating the process supervisor, queue, window, selected report, or topic records.

Settings requests `StorageUsageService.snapshot()` only when the storage section becomes visible or the user presses Refresh. It displays model cache, reports, retained job diagnostics, and total App data separately. The model-cache limit is disabled by default; the user may enable it and enter any positive value through a localized size field. Clear Model Cache requires confirmation, runs only through `StorageUsageService`, refreshes the snapshot afterward, and states that reports and source history are unaffected.

Verify at `820 x 620`, `1040 x 760`, and `1440 x 900 pt` with long English paper titles and Chinese topic names. Text must wrap rather than overlap controls.

- [ ] **Step 4: Implement a restricted local report reader**

`ReportReaderView` wraps `WKWebView` through `NSViewRepresentable` and calls:

```swift
webView.loadFileURL(reportURL, allowingReadAccessTo: runDirectoryURL)
```

`ReportReaderPolicy` rules:

- allow the initial `file:` URL only when it resolves under the selected run directory;
- disable content JavaScript through navigation preferences;
- allow same-run image and stylesheet files;
- cancel `http` and `https` navigation and open it with `NSWorkspace.shared.open`;
- reject `javascript:`, `data:`, `ftp:`, paths outside the run, and symlink escapes;
- do not persist website data or grant camera, microphone, location, or download access.

The reader is demand-loaded. Compact mode and any detail surface other than a selected report hold no `WKWebView`. One visible report reuses one WebView while compact/full presentation changes. Switching away from the report, hiding or closing the window, or receiving memory pressure clears the navigation delegate, stops loading, removes the view, and releases the App's strong reference. Use `WKWebsiteDataStore.nonPersistent()` and no shared persistent process pool. WebKit may retire its system content process asynchronously; the App must not keep the WebView alive to force instant reopening.

Add a real fixture report containing a local PNG, table-of-contents anchors, the existing static formula markup, and an external paper link. The WebView smoke must render the image, jump to the anchor, preserve the formula text, and hand the HTTP(S) link to `NSWorkspace` while content JavaScript remains disabled. JavaScript charts, video, and interactive web content are intentionally unsupported; Open in Browser is the future escape hatch for such content.

Run: `swift test --package-path apps/macos/ResearchRadar --filter ReportReaderPolicyTests`

Expected: PASS for every allowed and rejected URL case plus no eager WebView creation, one-instance reuse while visible, and App-reference release on navigation away, window hide, and memory pressure.

- [ ] **Step 5: Implement independent delivery jobs and recovery**

Research success writes `ReportRecordV1` before channel jobs are enqueued. Each enabled channel becomes its own `retry_delivery` engine request. Delivery state is one of `notRequested`, `pending`, `sending`, `created`, `sent`, `failed`, or `unknown`.

WeChat retry calls only the extracted WeChat service and preserves its duplicate/unknown safety. Email retry calls only `publish_email_run()` and respects existing resend protection; the UI requires confirmation before setting `allow_resend` for a previously sent email. No channel can mutate `article_draft.json` or start research.

Run: `swift test --package-path apps/macos/ResearchRadar --filter DeliveryRecoveryTests`

Expected: PASS for WeChat-only failure, Email-only failure, both success, no enabled channels, and unknown-after-crash behavior.

- [ ] **Step 6: Implement notifications and useful diagnostics**

Ask for notification permission only when the user enables schedules. Send notifications for report ready, partial delivery, research failed, and delivery unknown. Notification text contains topic, public stage, and action, never paths or raw errors.

`NotificationService` resolves strings when scheduling each notification, using the current `LocalizationStore` language. A later language change does not attempt to edit notifications already delivered by macOS. Alerts, timeline failures, and retry buttons use `UserFacingErrorCatalog`; only Diagnostics may show the original redacted engine message.

Diagnostics shows:

- app and engine version;
- macOS version and architecture;
- configured provider/model names and secret presence;
- PDF helper availability;
- queue and login-item state;
- on-demand storage totals and the configured optional model-cache limit;
- last attempt, last success, last public stage, report readiness, and per-channel delivery status;
- buttons for Run Preflight, Open Run Folder, Copy Redacted Diagnostics, Retry Research, and Retry Channel.

`Copy Redacted Diagnostics` serializes only an allowlist. Test it against secret-shaped values, private home paths, prompts, evidence quotes, and article bodies.

Run: `swift test --package-path apps/macos/ResearchRadar --filter DiagnosticsRedactionTests`

Run: `swift test --package-path apps/macos/ResearchRadar --filter NotificationServiceTests`

Expected: PASS.

- [ ] **Step 7: Extend the proven staging workflow to the complete App**

Keep Task 1's build/freeze/assemble/verify/sign sequence. Extend it to include the PDF helper, final localized resources, icon, and complete feature target, then call:

```text
script/assemble_macos_app.sh \
  --swift-bin-dir <swift-release-bin> \
  --engine-dir <pyinstaller-onedir> \
  --output dist/ResearchRadar.app
```

The assembler alone performs:

1. validate `ResearchRadar`, `ResearchRadarPDFHelper`, and `research-radar-engine` architectures are `arm64` and target macOS 26;
2. stage `Contents/MacOS/ResearchRadar`;
3. stage `ResearchRadarPDFHelper` and the complete PyInstaller `onedir` directory under `Contents/Helpers/`, using `/usr/bin/ditto` for the engine;
4. copy `Info.plist`, icon, and `ResearchRadar_ResearchRadarAppFeature.bundle` into `Contents/Resources/`, then verify English and Simplified Chinese catalog lookup from the staged App;
5. set executable permissions;
6. compare the source/staged engine symlink manifests and reject any link that escapes the engine root;
7. recursively resolve every Mach-O dependency and fail on Homebrew, `/usr/local`, project-venv, source-checkout, `/private/tmp`, missing, or unresolved dependencies;
8. fail if strings in the bundle contain a project-home path, a secret-like fixture, or the process-tree test executable.

`Info.plist` includes:

```xml
<key>CFBundleIdentifier</key><string>ai.research-radar.app</string>
<key>CFBundleExecutable</key><string>ResearchRadar</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
<key>LSUIElement</key><true/>
<key>NSPrincipalClass</key><string>NSApplication</string>
```

Run: `./script/stage_macos_app.sh`

Expected: one self-contained arm64 `.app` with both nested helpers, intact `onedir` symlinks, and no runtime dependency on Python, `uv`, Homebrew, or Poppler.

- [ ] **Step 8: Add one build/run entrypoint and Codex desktop action**

`script/build_and_run.sh` supports:

```text
./script/build_and_run.sh
./script/build_and_run.sh --verify
./script/build_and_run.sh --logs
./script/build_and_run.sh --demo idle|running|complete|partial|failed
```

It stops only the existing ResearchRadar app process, stages the bundle, launches via `/usr/bin/open -n`, and optionally verifies the process and main window. Demo state is compiled under `#if DEBUG` and uses fixture data only; it cannot invoke models or publishers.

`.codex/environments/environment.toml` defines one Run action invoking `./script/build_and_run.sh --verify`.

- [ ] **Step 9: Perform visual and accessibility QA on deterministic states**

Build and inspect idle, running, complete, partial, and failed states in Light and Dark mode. Use the Product Design audit/design-QA workflow and the macOS SwiftUI, AppKit interop, Liquid Glass, build-run-debug, and telemetry guidance.

Acceptance checklist:

- menu icon is crisp at standard and Retina scales;
- hover status is one line and updates with the job;
- left-click always reuses the same window;
- compact/full transition preserves selection and does not jump content;
- no text truncates controls at the minimum window size;
- no nested-card wall or decorative glass appears;
- timeline state is obvious without relying only on color;
- keyboard reaches every action in logical order;
- VoiceOver names status, topic, next run, progress, and retry actions;
- Reduce Motion removes frame/content animation;
- Increase Contrast and Reduce Transparency remain readable;
- local report images and anchors render; external links open in the default browser.

Save approved screenshots under `docs/assets/macos-app/` only after checking that they contain no account names, email addresses, local paths, API identifiers, or unpublished report content.

- [ ] **Step 10: Add local beta signing and DMG packaging**

`script/package_macos_beta.sh` stages the app, signs nested code deepest-first with ad-hoc identity `-`, signs the outer app last with hardened-runtime option disabled for the local-only beta, then runs:

```bash
codesign --verify --deep --strict --verbose=2 dist/ResearchRadar.app
hdiutil create -volname ResearchRadar -srcfolder dist/ResearchRadar.app \
  -ov -format UDZO dist/ResearchRadar-local-beta.dmg
```

Do not use `codesign --deep` to perform signing. There is currently no Developer ID identity, so the script must label the artifact local beta and must not claim Gatekeeper/notarization readiness.

Public distribution is a separate release gate: obtain a Developer ID Application identity, enable hardened runtime, sign every nested binary and library deepest-first, sign the app, submit with `notarytool`, staple with `stapler`, and verify Gatekeeper. Do not add blanket JIT or unsigned-memory entitlements without a reproduced runtime failure and a security review.

Hardened Runtime and App Sandbox are separate decisions. Before a future Developer ID build is accepted, rerun the complete Task 1 process-tree suite against the hardened signed bundle. App Sandbox remains disabled in v1 and requires a separate capability design for bundled-engine and user-selected Codex execution.

- [ ] **Step 11: Run the final macOS 26 arm64 resource and lifecycle gate**

Retain the Task 1 foundation measurements and regenerate `dist/macos-resource-report.json` from the complete staged App. Record final App and helper sizes, cold launch, fake preflight, five-minute idle RSS/CPU sample, visible-report RSS/child-process sample, and active fake-run process inventory. Compare each value with the Task 1 and Task 2 measurements and name the feature responsible for every meaningful increase; do not convert unmeasured assumptions into hard release numbers.

The functional lightweight gate is strict:

1. before a report is opened, no WebKit content is requested by the App;
2. with the window hidden, the App holds no `WKWebView`, engine, PDF helper, Codex process, event tailer, or fixed-interval timer;
3. one enabled schedule produces one one-shot timer, and no enabled schedule produces none;
4. twenty preflight/cancel cycles and twenty report open/close cycles leave no child process and do not show monotonic RSS growth;
5. successful jobs leave no stdout/stderr payload, failed diagnostics remain bounded, and storage measurement happens only on demand;
6. the staged App and nested helpers are arm64, require macOS 26, and have no dependency on the source checkout, `.venv`, Homebrew, `uv`, or user-installed Python.

This local beta supports only the platform named above. Any compatibility expansion requires a separate approved plan and build/test environment rather than compatibility branches in v1.

- [ ] **Step 12: Document installation and preserve existing product boundaries**

Create `docs/macos-app.md` covering the macOS 26 Apple Silicon requirement, local beta installation, the distinction between App UI language and per-topic report language, Keychain setup, topic onboarding, provider preflight, one-shot schedules, Run Now, cancellation, demand-loaded report reading, WeChat/Email retries, diagnostics, storage categories, optional user cache limit, explicit cache cleanup, Start at Login, Quit semantics, data locations, and uninstall steps that move app-owned durable files to Trash only after explicit confirmation.

README links to the app document without replacing CLI instructions. Architecture and security docs state that Swift owns local app workflow while Python owns research/publishing truth. Usage and roadmap identify the app as beta and retain Archive, Zhihu, evaluation, and CLI workflows.

Run the repo hygiene and privacy tests after documentation changes.

- [ ] **Step 13: Run full regression, real local beta smoke, and the third signed-off commit**

```bash
uv run --extra dev pytest
uv run --extra dev ruff check src tests
swift test --package-path apps/macos/ResearchRadar
./script/stage_macos_app.sh
./script/package_macos_beta.sh
uv run research-radar privacy scan
git diff --check
codesign --verify --deep --strict --verbose=2 dist/ResearchRadar.app
```

Real local beta acceptance uses a dedicated non-production app data root and existing Keychain secret names:

1. launch in system language, switch to Simplified Chinese and English, and confirm the current window, tooltip, menu, new notifications, and user-facing error copy update immediately;
2. complete onboarding without YAML or terminal use;
3. bootstrap a topic, change its report language before approval, then verify later UI-language changes do not alter it;
4. run one fake-provider daily job and verify every public stage;
5. cancel a long-running fixture and verify no child process survives;
6. quit/relaunch and reopen the fake report from the durable index;
7. run one real `agent-memory` report only after the fake workflow passes;
8. confirm local `wechat.html` matches the CLI output for the same `ArticleDraft`;
9. create one WeChat draft and one private email as separate delivery jobs;
10. force one fake channel failure and retry only that channel;
11. sleep/wake once and verify only the latest due job is queued;
12. enable and disable Start at Login, then explicitly Quit and confirm no hidden engine or scheduler remains.
13. open Storage, record on-demand usage, set and disable a custom cache limit, clear model cache with confirmation, and verify reports/source history are byte-identical;
14. open and close a report repeatedly, then verify the App releases its WebView reference and leaves no engine/helper process while hidden;
15. inspect the final resource report and explain changes from the Task 1 and Task 2 baselines.

Then commit:

```bash
git add apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Views \
  apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Localization \
  apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Resources \
  apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/ReportReaderPolicy.swift \
  apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Services/NotificationService.swift \
  apps/macos/ResearchRadar/Sources/ResearchRadarAppFeature/Support/VisualTokens.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/AppStorePresentationTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/LocalizationStoreTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/LocalizationCatalogTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/ReportReaderPolicyTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/DeliveryRecoveryTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/DiagnosticsRedactionTests.swift \
  apps/macos/ResearchRadar/Tests/ResearchRadarAppFeatureTests/NotificationServiceTests.swift \
  packaging/macos/Info.plist packaging/macos/ResearchRadar.icns \
  script/stage_macos_app.sh script/assemble_macos_app.sh script/build_and_run.sh \
  script/package_macos_beta.sh .codex/environments/environment.toml \
  docs/macos-app.md docs/architecture.md docs/security.md \
  docs/usage.md docs/todo.md README.md README.zh-CN.md
git diff --cached --check
git commit -s -m "[feat] Add localized ResearchRadar menu bar experience"
```

Do not push until the user has reviewed the local beta UI and the real delivery smoke results.

---

## 5. Failure And Recovery Matrix

| Failure | Durable state | Automatic action | User action |
| --- | --- | --- | --- |
| Missing DeepSeek key | preflight `action_required` | none | Add key in onboarding |
| Missing Codex executable | preflight `action_required` | none | Select executable or explicitly choose DeepSeek verifier |
| Bundled dependency or symlink verification fails | build gate fails; no beta artifact | none | Repair bundle inputs before feature work/release |
| Provider probe timeout | preflight `unavailable` | none | Retry test or change provider |
| Engine exits before `started` | job `failed` with `engine_crashed` | terminate PID; no group assumption | Retry after viewing localized error/Diagnostics |
| Descendant ignores TERM | job remains cancelling | supervisor escalates group to KILL and waits | none unless cleanup fails |
| Research process exits before result | job `failed` or `interrupted` | no delivery | Retry Research |
| App exits while an engine job is active | engine writes `parent_lost`; Task 2 reconciles job to `interrupted` | terminate engine process group; never auto-rerun or create delivery | Reopen App, inspect status, then explicitly retry |
| App crashes after a valid result is already durable | reconcile to result status | enqueue only deliveries that were already durably requested and not terminal | Review report |
| User cancels during research | job `cancelled` | terminate process group; no delivery | Run again when desired |
| WeChat draft fails | report ready; WeChat `failed` | Email may still run | Retry WeChat only |
| Email fails | report ready; Email `failed` | WeChat remains untouched | Retry Email only |
| Delivery outcome unknown | channel `unknown` | never auto-retry | Check destination, then explicitly retry |
| Corrupt app state JSON | preserve bytes; startup diagnostics | no schedule execution | Restore/rebuild state after confirmation |
| Missing report HTML | report record `needs_attention` | do not render broken view | Open run folder or retry research |
| Native PDF helper rejects crop | no public figure | continue report | none; no broken image shown |
| Report view is hidden or memory pressure occurs | no durable state mutation | release the App-owned WebView reference; recreate on the next explicit open | none |
| Model-cache cleanup encounters an escaped, symlinked, missing, or non-regular entry | reports and source history remain untouched | change no files; stop cleanup and record bounded diagnostics | Review Diagnostics and retry after fixing the cache root |
| Model cache exceeds a user-defined limit | no report/history mutation | after a cache hit/write or completed daily, evict the least-recently-used contained cache entries until within the limit | Raise or disable the optional limit if desired |
| Login-item registration fails | setting remains off with error | app continues while open | Retry registration |
| Unknown engine error code | preserve redacted diagnostics | show generic localized failure | Open Diagnostics or Retry when allowed |
| System language changes in manual mode | no state mutation | keep selected UI language | none |

---

## 6. Security Review Checklist

- Requests permit only four command enums and never arbitrary executable/script text.
- The only external verifier executable is an explicitly validated absolute Codex path.
- Engine, PDF, result, and report paths are resolved and contained under Application Support.
- Symlink escapes are rejected before read/write or WebView access.
- PyInstaller `onedir` symlinks are preserved with `ditto`, compared before/after staging, and required to resolve inside the bundled engine.
- Keychain values never cross the JSON protocol.
- Logs and diagnostics use allowlists plus existing redaction and size bounds.
- Successful jobs retain only terminal metadata; each topic/job kind keeps at most the newest bounded failure diagnostic.
- Raw engine messages and tracebacks never bypass `UserFacingErrorCatalog` into normal UI or notifications.
- WKWebView is created only for a visible report, uses a non-persistent data store, disables JavaScript, grants only run-directory read access, delegates external links to the system browser, and is released when the report is no longer visible or memory pressure occurs.
- The app does not use an embedded HTTP server.
- The local beta is not App Sandbox enabled because it must spawn the bundled engine and optional Codex executable; this tradeoff is documented and command/path allowlists remain mandatory. Hardened Runtime is tracked separately and requires a repeated process-tree gate when enabled.
- Start at Login is opt-in; explicit Quit leaves no hidden helper.
- No publisher runs unless the user enables that channel for the topic or explicitly retries it.
- Existing evidence, source-history, duplicate-send, and unknown-delivery safeguards remain active.
- Bundle inspection rejects private build paths and unapproved dynamic-library locations.
- The process-tree fixture is a test product and is explicitly rejected from the assembled App.
- During an active job the engine watches the native App PID with `kqueue`; parent loss terminates the engine process group and cannot trigger an automatic delivery.
- Cache deletion requires explicit user confirmation, resolves every candidate inside the app-owned model-cache root, and permits only regular cache entries. Reports, figures, source history, configuration, queue state, and delivery artifacts are never deletion candidates.
- The idle App owns no Python engine, PDF helper, Codex process, event tailer, fixed-interval scheduler, or preloaded report view.

---

## 7. Coverage Matrix

| Approved requirement | Implementation location | Verification |
| --- | --- | --- |
| Bundled App foundation before product expansion | Task 1, Steps 1-9 | staged preflight, bundle inspection, macOS 26 arm64 launch/cancel smoke, and resource baseline |
| Swift toolchain is proven before product code | Pre-implementation gate | CLT 26.6, generated package build, and localized AppKit/SwiftUI package run |
| Menu-bar icon with hover status | Task 1, Step 6; Task 2 Phase 2B, Step 13 | foundation window tests plus visual QA |
| App UI follows system or uses explicit Chinese/English | Task 1, Step 2; Task 3, Steps 1-3 and 6 | resolver, catalog, immediate-refresh, menu/notification tests |
| UI language is independent from topic report language | Task 2, Steps 1 and 9; Task 3, Step 1 | persistence and onboarding tests |
| One compact/full singleton window | Task 1, Step 6; Task 3, Steps 2-3 | singleton and presentation tests |
| Editorial Radar plus timeline visual direction | Task 3, Steps 1-3 and 9 | deterministic states and design audit |
| Natural-language topic onboarding with review | Task 2 Phase 2A command handlers; Phase 2B, Step 9 | bridge and onboarding tests |
| Provider preflight and Codex fallback | Task 2 Phase 2A, Step 9; Phase 2B, Steps 7-9 | preflight/Keychain/onboarding tests |
| Multiple topics and per-topic daily schedules | Task 2 Phase 2B, Steps 3-4 and 12 | queue and one-shot schedule tests |
| One global serialized durable queue | Task 2 Phase 2B, Steps 3 and 6 | queue/supervisor tests |
| Run now, cancel, pause, catch-up | Product contract; Task 1, Steps 3-5; Task 2 Phase 2B, Steps 3-6 and 12 | reducer, process-group, one-shot schedule tests |
| App crash cannot orphan model work | Task 1, Steps 3-5; Task 2 Phase 2B, Step 6 | `kqueue` parent-exit fixture, `parent_lost` reconciliation, and descendant liveness checks |
| Legacy history migration and scheduler collision guard | Task 2, Step 10 | migration and plist-detection tests |
| Demand-loaded local report reader | Task 3, Steps 4 and 11 | URL-policy, non-persistent-store, release-on-hide, memory-pressure, and real-report tests |
| WeChat and Email independent recovery | Task 2 Phase 2A application services; Task 3, Step 5 | delivery recovery tests |
| Crash/restart reconciliation | Task 2 Phase 2B, Steps 3 and 6 | terminal-file reconciliation tests |
| Keychain and private atomic state | Task 2 Phase 2B, Steps 2 and 7 | permissions and cross-runtime tests |
| No CLI text/YAML/Homebrew runtime | Task 1, Steps 7-9; Task 3, Step 7 | sanitized-PATH frozen-engine smoke, symlink manifest, Mach-O inspection |
| Native PDFKit helper | Task 2 Phase 2A, Steps 11-14 | Swift fixture, Python adapter, restaged bundle tests |
| Stable user errors and redacted diagnostics | Task 1, Steps 2-3; Task 3, Steps 1 and 6 | error-catalog completeness and diagnostics tests |
| Existing CLI and renderers unchanged | Task 2 parity tests; Task 3 full regression | byte-equivalence and full pytest |
| Local beta staging and nested signing | Task 1, Steps 7-8; Task 3, Steps 7-10 | arm64 codesign, symlink, dependency, and DMG checks |
| Lightweight idle lifecycle | Task 1, Steps 3-8; Task 2 Phase 2B, Steps 3-6 and 12; Task 3, Step 11 | no idle helpers/tailer/fixed polling, no descendants after cancel, and non-monotonic repeated-cycle RSS |
| On-demand storage and optional model-cache limit | Task 2 Phase 2A, Steps 3 and 14; Phase 2B, Step 11; Task 3, Steps 3 and 11 | usage calculated only on request; contained LRU cache cleanup; reports/history byte equivalence |
| macOS 26 arm64 local beta target | Task 1, Steps 7-9; Task 3, Steps 7-11 | minimal and final staged bundle launch, process, signing, and resource evidence on the supported platform |
| No auto-publish, weekly, Archive, Zhihu, eval, TUI | Global constraints | CLI/regression tests and scope review |

---

## 8. Final Acceptance Gate

The v1 beta is complete only when all of these are true:

- Python full tests, Ruff, privacy scan, and diff check pass.
- Swift unit/integration tests pass.
- The PyInstaller engine runs with sanitized PATH and without the source checkout; its preflight imports `cryptography`, the selected macOS `keyring` backend, `PIL`, `pypdf`, `yaml`, and the foundation bridge from the frozen bundle; source and staged symlink manifests match and no link escapes the engine root.
- PDFKit helper tests prove point-space bbox and full-width crop behavior.
- The `.app` contains and launches both helpers; recursive Mach-O inspection finds no private build paths, Homebrew libraries, unresolved tokenized dependency, or fixture executable.
- A process-group cancellation leaves no engine/provider child.
- An App crash during active work produces `parent_lost`, leaves no engine/provider descendant, and never starts an automatic retry or delivery.
- System, Simplified Chinese, and English UI modes pass immediate-refresh tests without mutating any topic report language.
- The five deterministic UI states pass Light/Dark/accessibility review at compact and minimum full sizes.
- A real report is readable in the restricted WebView and byte-equivalent WeChat HTML is preserved.
- WeChat and Email can independently succeed/fail/retry without rerunning research.
- Start at Login is explicit, and Quit leaves no schedule or engine running.
- The staged App and every bundled executable are arm64, declare macOS 26, and run without source checkout, `.venv`, Homebrew, `uv`, or a user-installed Python.
- With no active job, the native App is the only ResearchRadar process. There is no fixed polling, event tailer, Python engine, PDF helper, Codex process, or preloaded WebView.
- When one or more schedules are enabled, the coordinator owns exactly one timer for the nearest next trigger; with no enabled schedule there is no scheduler timer.
- Repeated preflight/cancel and report open/close cycles leave no child process and do not show sustained monotonic RSS growth.
- The Task 1, Task 2, and final resource reports record measured package size, launch/preflight timing, idle/visible-report/active-job resources, and explain meaningful growth without inventing release thresholds.
- Storage usage is calculated only on request. The default cache limit is disabled, and an enabled limit or manual cleanup can affect only the contained model cache; reports, figures, source history, configuration, and delivery artifacts remain byte-identical.
- Successful jobs retain no long-lived stdout/stderr payload, and failure diagnostics obey the documented per-topic/job-kind and 1 MiB bounds.
- The local beta is labeled for the exact supported platform and makes no wider compatibility claim.
- Each of the three implementation commits is signed off and reviewed before any push.

## 9. Assumptions

- v1 Chinese UI means Simplified Chinese only; Traditional Chinese is a separate future addition.
- App UI language and per-topic report language remain independent settings.
- App UI defaults to the system preference, and a manual selection takes effect immediately.
- A new topic uses the resolved UI language only as its editable initial report-language value.
- `NSStatusItem`, a static JavaScript-disabled `WKWebView`, the bundled Python engine, and the versioned JSON file protocol remain the approved architecture.
- v1 is a local beta, not a Mac App Store or notarized public release.
- v1 supports only macOS 26 on Apple Silicon arm64; broader compatibility is separate future work.
- The repository remains compatible with Python `>=3.12`; the first local beta freezes the already-used Python 3.13.x runtime and records its full patch version instead of installing a second Python.
- The model-cache limit defaults to `nil`. Resource limits are added only from measurements or explicit user choice, never guessed in advance.
- Reports, figures, source history, configuration, queue state, and delivery records are durable user data, not cache.
- Background lightness takes priority over instant reopening of a hidden report: the App recreates demand-loaded WebKit and helper resources when the user explicitly needs them.
- TUI, weekly reports, Archive UI, Zhihu UI, and JavaScript report features remain outside v1.

## 10. Execution Handoff

Implement this plan using `superpowers:subagent-driven-development` with a fresh implementation subagent and a separate spec/code-quality review for each task. Use `superpowers:executing-plans` only when the work must stay in one session. Stop at every signed-off commit checkpoint for review; do not combine the three commits and do not push without explicit approval.
