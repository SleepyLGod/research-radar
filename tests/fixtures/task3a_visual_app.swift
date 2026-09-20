// Test-only executable. Link against an already integrated production build.
import AppKit
import SwiftUI
import WebKit
import ResearchRadarCore
#if TASK3A_INTERNAL_SETTINGS
@testable import ResearchRadarAppFeature
#else
import ResearchRadarAppFeature
#endif

struct FakeSecrets: SecretStoring {
    var present = true
    func read(account: String) throws -> Data? { nil }
    func contains(account: String) throws -> Bool { present }
    func set(_ value: Data, account: String) throws { throw HarnessError.secretMutation }
    func remove(account: String) throws { throw HarnessError.secretMutation }
}

enum HarnessError: Error { case secretMutation, invalidCommand, settingsUnavailable, controlNotFound, pressRejected, invalidFixtureConfiguration }

struct Command: Codable {
    let id: String
    let action: String
    var mode: String = "compact"
    var state: String = "idle"
    var language: String = "en"
    var appearance: String = "light"
    var artifact: String = "fixture"
    var target: String = ""
}

@MainActor final class WeakWeb {
    weak var value: WKWebView?
    init(_ value: WKWebView) { self.value = value }
}

@MainActor final class Harness: NSObject, NSApplicationDelegate {
    let root: URL
    var coordinator: WindowCoordinator?
    var statusItem: NSStatusItem?
    weak var productionHost: NSHostingView<AnyView>?
    var store: AppStore?
    var localization: LocalizationStore?
    var presentation = WindowPresentationState()
    var timer: Timer?
    var lastID: String?
    var retired: [WeakWeb] = []
    var lastAction: [String: Any] = [:]
    var statusActionCount = 0
    var outsideWindow: NSWindow?
    var outsideClickCount = 0

    init(root: URL) { self.root = root }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // No production AppDelegate/bootstrap/scheduler or engine is instantiated.
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem = item
        item.button?.image = NSImage(systemSymbolName: "dot.radiowaves.left.and.right", accessibilityDescription: "ResearchRadar test")
        item.button?.target = self
        item.button?.action = #selector(togglePopover)
        do {
            try Data(String(getpid()).utf8).write(to: root.appending(path: "app.pid"), options: .atomic)
        } catch {
            FileHandle.standardError.write(Data("Cannot publish harness PID: \(error)\n".utf8))
            NSApp.terminate(nil)
            return
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.poll() }
        }
        // Let launch finish and the menu-bar host position the item before commands run.
    }

    func webViews(_ view: NSView?) -> [WKWebView] {
        guard let view else { return [] }
        return (view as? WKWebView).map { [$0] } ?? view.subviews.flatMap { webViews($0) }
    }

    func rememberReaders() {
        retired.append(contentsOf: webViews(coordinator?.contentView).map(WeakWeb.init))
    }

    @objc func togglePopover() {
        statusActionCount += 1
        lastAction["popover_shown_when_action_ran"] = coordinator?.popover.isShown ?? false
        lastAction["status_action_count"] = statusActionCount
        coordinator?.toggle()
    }

    func clickStatusItem() throws {
        guard let button = statusItem?.button, let window = button.window, coordinator != nil else {
            throw HarnessError.controlNotFound
        }
        if coordinator?.popover.isShown == true { rememberReaders() }
        let point = button.convert(NSPoint(x: button.bounds.midX, y: button.bounds.midY), to: nil)
        try postClick(in: window, at: point, target: "status-item")
    }

    func postClick(in window: NSWindow, at point: NSPoint, target: String) throws {
        let screenPoint = window.convertPoint(toScreen: point)
        guard window.isVisible, window.frame.contains(screenPoint) else { throw HarnessError.pressRejected }
        lastAction = ["target": target, "accepted": false,
                      "popover_shown_before_input": coordinator?.popover.isShown ?? false]
        if CGPreflightPostEventAccess(), let primary = NSScreen.screens.first {
            let location = CGPoint(x: screenPoint.x, y: primary.frame.maxY - screenPoint.y)
            guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
                                     mouseCursorPosition: location, mouseButton: .left),
                  let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
                                   mouseCursorPosition: location, mouseButton: .left) else {
                throw HarnessError.pressRejected
            }
            lastAction["mechanism"] = "CGEvent left down/up at owned target; existing permission"
            down.setIntegerValueField(.mouseEventClickState, value: 1)
            up.setIntegerValueField(.mouseEventClickState, value: 1)
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
        } else {
            let events = [NSEvent.EventType.leftMouseDown, .leftMouseUp].compactMap { type in
                NSEvent.mouseEvent(with: type, location: point, modifierFlags: [],
                    timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                    context: nil, eventNumber: 0, clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0)
            }
            guard events.count == 2 else { throw HarnessError.pressRejected }
            lastAction["mechanism"] = "local NSEvent left down/up; CG posting unavailable"
            lastAction["fidelity_limit"] = "System-wide event routing and cross-app focus unverified"
            for event in events { NSApp.postEvent(event, atStart: false) }
        }
        lastAction["accepted"] = true
    }

    func pressEscape() throws {
        guard let window = coordinator?.window, coordinator?.popover.isShown == true,
              window.isKeyWindow, NSApp.isActive else { throw HarnessError.pressRejected }
        rememberReaders()
        lastAction = ["target": "escape", "accepted": false]
        if CGPreflightPostEventAccess() {
            guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: false) else {
                throw HarnessError.pressRejected
            }
            lastAction["mechanism"] = "CGEvent Escape down/up to active test popover"
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
        } else {
            let events = [NSEvent.EventType.keyDown, .keyUp].compactMap { type in
                NSEvent.keyEvent(with: type, location: .zero, modifierFlags: [],
                    timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                    context: nil, characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}",
                    isARepeat: false, keyCode: 53)
            }
            guard events.count == 2 else { throw HarnessError.pressRejected }
            lastAction["mechanism"] = "local NSEvent Escape down/up; CG posting unavailable"
            lastAction["fidelity_limit"] = "System keyboard routing unverified"
            for event in events { NSApp.postEvent(event, atStart: false) }
        }
        lastAction["accepted"] = true
    }

    @objc func outsideTargetClicked() { outsideClickCount += 1 }

    func prepareOutsideTarget() throws {
        guard let screen = statusItem?.button?.window?.screen,
              let popoverWindow = coordinator?.window else { throw HarnessError.controlNotFound }
        let area = screen.visibleFrame
        let candidates = [area.minX + 8, area.maxX - 168].map {
            NSRect(x: $0, y: area.minY + 8, width: 160, height: 70)
        }
        guard let frame = candidates.first(where: { !$0.intersects(popoverWindow.frame) }) else {
            throw HarnessError.controlNotFound
        }
        let window = NSWindow(contentRect: frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.title = "Offline click target"
        let button = NSButton(title: "Offline test target", target: self, action: #selector(outsideTargetClicked))
        window.contentView = button
        outsideWindow = window
        window.orderFront(nil)
    }

    func clickOutsideTarget() throws {
        guard let window = outsideWindow, let view = window.contentView else {
            throw HarnessError.controlNotFound
        }
        rememberReaders()
        try postClick(in: window, at: NSPoint(x: view.bounds.midX, y: view.bounds.midY), target: "owned-outside-window")
    }

    func hostingView(in view: NSView?) -> NSHostingView<AnyView>? {
        guard let view else { return nil }
        if let host = view as? NSHostingView<AnyView> { return host }
        for child in view.subviews {
            if let host = hostingView(in: child) { return host }
        }
        return nil
    }

    func accessibilityNodes(_ root: Any?) -> [any NSAccessibilityProtocol] {
        var result: [any NSAccessibilityProtocol] = []
        var visited: Set<ObjectIdentifier> = []
        func walk(_ value: Any, depth: Int) {
            guard depth < 40, result.count < 1000,
                  let node = value as? any NSAccessibilityProtocol,
                  visited.insert(ObjectIdentifier(node as AnyObject)).inserted else { return }
            result.append(node)
            let children = (node.accessibilityChildren() ?? []) + (node.accessibilityRows() ?? [])
                + (node.accessibilityVisibleChildren() ?? [])
            for child in children { walk(child, depth: depth + 1) }
            // NSPopover's AX wrapper can omit the hosting container from its children.
            // Inspect our own view hierarchy as well; never query another application's AX tree.
            if let window = value as? NSWindow, let content = window.contentView {
                walk(content, depth: depth + 1)
            }
            if let view = value as? NSView {
                for child in view.subviews { walk(child, depth: depth + 1) }
            }
        }
        if let root { walk(root, depth: 0) }
        return result
    }

    func labels(_ node: any NSAccessibilityProtocol) -> [String] {
        [node.accessibilityLabel(), node.accessibilityTitle(), node.accessibilityValue() as? String]
            .compactMap { $0 }.filter { !$0.isEmpty }
    }

    func press(_ key: String) throws {
        guard ["action.full_workspace", "nav.settings", "nav.topics", "nav.reports",
               "action.compact", "action.open_report", "action.configure"].contains(key),
              let localization else { throw HarnessError.invalidCommand }
        if ["action.compact", "nav.settings", "nav.topics"].contains(key) { rememberReaders() }
        let label = localization.text(key)
        let nodes = accessibilityNodes(coordinator?.window)
        // Prefer the real button/row, whose label may be provided by a child element.
        let controls = nodes.filter { node in
            guard node.accessibilityRole() == .button || node.accessibilityRole() == .row else { return false }
            return accessibilityNodes(node).flatMap { labels($0) }.contains(label)
        }
        let candidates = controls + nodes.filter { labels($0).contains(label) }
        lastAction = ["key": key, "label": label, "candidates": candidates.count,
                      "mechanism": "in-process NSAccessibility accessibilityPerformPress"]
        guard !candidates.isEmpty else { throw HarnessError.controlNotFound }
        for node in candidates where node.accessibilityPerformPress() {
            lastAction["accepted"] = true
            return
        }
        // SwiftUI may expose AX labels but reject performPress. Queue real local
        // mouse events on this window, never global CG events or selection setters.
        if let window = coordinator?.window, let node = candidates.first {
            let frame = node.accessibilityFrame()
            let screenPoint = NSPoint(x: frame.midX, y: frame.midY)
            if frame.width > 0, frame.height > 0, window.frame.contains(screenPoint) {
                let point = window.convertPoint(fromScreen: screenPoint)
                let events = [NSEvent.EventType.leftMouseDown, .leftMouseUp].compactMap { type in
                    NSEvent.mouseEvent(with: type, location: point, modifierFlags: [],
                        timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                        context: nil, eventNumber: 0, clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0)
                }
                if events.count == 2 {
                    for event in events { NSApp.postEvent(event, atStart: false) }
                    lastAction["mechanism"] = "in-process NSEvent click at AX frame center; AX press rejected"
                    lastAction["accepted"] = true
                    return
                }
            }
        }
        lastAction["accepted"] = false
        throw HarnessError.pressRejected
    }

    func editTopicName() {
        let original = store?.selectedTopic?.displayName ?? ""
        let field = accessibilityNodes(coordinator?.window).first {
            $0.accessibilityRole() == .textField && ($0.accessibilityValue() as? String) == original
        }
        lastAction = ["mechanism": "in-process AX topic-name value setter", "original": original,
                      "accepted": false, "draft": "Task3A unsaved draft"]
        guard let field else { return }
        field.setAccessibilityValue("Task3A unsaved draft")
        lastAction["accepted"] = (field.accessibilityValue() as? String) == "Task3A unsaved draft"
    }

    func configure(_ command: Command) throws {
        let setupPages: [String: OnboardingStep] = ["setupAppearance": .storage,
            "setupServices": .providers, "setupTopic": .topicDescription, "setupReady": .preflight]
        let setupPage = setupPages[command.state]
        let outcomes: [String: ResearchOutcomeV1] = [
            "no_new_content": .init(status: .noNewContent, reasons: [.noEligiblePapers]),
            "incomplete": .init(status: .incomplete, reasons: [.fullTextUnavailable]),
            "partial_ready": .init(status: .ready, reasons: [.readingFailed])
        ]
        let outcome = outcomes[command.state]
        guard ["compact", "full", "reader", "settings"].contains(command.mode),
              (["idle", "running", "complete", "failed", "unknown", "missingConfig", "missingKey"].contains(command.state) || setupPage != nil || outcome != nil),
              ["en", "zh-Hans"].contains(command.language),
              ["light", "dark"].contains(command.appearance) else { throw HarnessError.invalidCommand }
        let support = root.appending(path: "stores/\(command.id)")
        let workspace = root.appending(path: "workspace")
        guard ["fixture", "rendered"].contains(command.artifact) else { throw HarnessError.invalidCommand }
        let run = workspace.appending(path: command.artifact == "rendered" ? "rendered" : "run")
        // This satisfies executable validation only; engineURL stays nil and no job is started.
        let codex = command.state == "missingConfig" ? nil : URL(fileURLWithPath: "/usr/bin/true")
        var config = AppConfigurationDefaults.make(workspaceRoot: workspace, codexExecutable: codex)
        let chinese = command.language == "zh-Hans"
        config.uiLanguage = chinese ? .simplifiedChinese : .english
        config.uiAppearance = command.appearance == "dark" ? .dark : .light
        config.topics = [TopicRecordV1(id: "offline", displayName: chinese ? "智能体记忆与证据评估" : "Agent memory and evidence evaluation",
            researchFocus: "Offline visual acceptance", queries: ["agent memory"],
            paperQueries: ["agent memory"], reportLanguage: .english)]
        if setupPage != nil && setupPage != .preflight { config.topics = [] }
        config.delivery.email.enabled = false
        config.delivery.wechat.enabled = false
        config.startAtLogin = false
        let now = Date()
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let date = formatter.string(from: now)
        let report = ReportRecordV1(topicID: "offline", reportDate: date, runDirectory: run.path,
            articleDraftPath: run.appending(path: "article.json").path,
            reportHTMLPath: run.appending(path: command.artifact == "rendered" ? "wechat.html" : "report.html").path,
            title: chinese ? "记忆评估：答案正确与证据充分" : "Memory evaluation: correct answers and grounded evidence",
            summary: chinese ? "离线固定样本，包含本地图像、段落锚点与静态公式。" : "Offline fixture with a local image, section anchors and a static formula.",
            sourceCount: outcome?.status == .noNewContent ? 0 : 3,
            deepReadCount: outcome == nil ? 2 : (outcome?.status == .ready ? 1 : 0),
            publishableClaimCount: outcome == nil ? 4 : (outcome?.status == .ready ? 2 : 0),
            deliveries: command.state == "unknown" ? [.init(channel: .email, state: .unknown)] : [],
            createdAt: command.state == "failed" ? now.addingTimeInterval(-120) : now,
            researchOutcome: outcome)
        let states: [String: JobState] = ["running": .running, "complete": .succeeded,
                                         "failed": .failed, "unknown": .deliveryUnknown]
        var jobs: [JobRecordV1] = []
        // These research attempts completed as processes; their report outcomes differ.
        if let state = outcome == nil ? states[command.state] : .succeeded {
            jobs = [try JobRecordV1(kind: command.state == "unknown" ? .delivery : .research,
                topicID: "offline", reportDate: date,
                deliveryChannel: command.state == "unknown" ? .email : nil, trigger: .runNow,
                state: state, stage: state == .running ? .deepReading : (state == .failed ? .sourceGist : nil),
                jobDirectory: support.appending(path: "jobs/fixture").path,
                runDirectory: command.state == "unknown" || outcome != nil ? run.path : nil, createdAt: now,
                error: state == .failed ? .init(code: "model_response_retry_exhausted", message: "Offline fixture failure", retryable: true) : nil)]
        }
        let mode: WindowMode = command.mode == "compact" ? .compact : .full
        let missingCredentials = command.state == "missingKey" || setupPage == .providers
        var fixtureReports = ["complete", "unknown", "failed"].contains(command.state)
            || command.mode == "reader" || outcome != nil ? [report] : []
        if command.state == "incomplete" {
            let previous = run.appending(path: "previous")
            fixtureReports.append(ReportRecordV1(topicID: "offline", reportDate: date,
                runDirectory: previous.path,
                articleDraftPath: previous.appending(path: "article.json").path,
                reportHTMLPath: previous.appending(path: "report.html").path,
                title: chinese ? "上次精读：记忆检索与证据" : "Earlier deep read: memory retrieval and evidence",
                summary: chinese ? "这份报告来自较早的成功运行，不是本次未完成任务的结果。"
                    : "This report belongs to an earlier successful run, not the incomplete attempt.",
                sourceCount: 5, deepReadCount: 2, publishableClaimCount: 6, deliveries: [],
                createdAt: now.addingTimeInterval(-120),
                researchOutcome: .init(status: .ready, reasons: [])))
        }
        let next = AppStore(configuration: config, queueSnapshot: .init(jobs: jobs),
            reportSnapshot: .init(reports: fixtureReports),
            runtime: .init(onboardingStep: setupPage ?? .complete, onboardingInProgress: setupPage != nil,
                           windowMode: mode, selectedTopicID: config.topics.first?.id,
                           schedulesPaused: true, updatedAt: now),
            appSupportRoot: support, engineURL: nil, secretStore: FakeSecrets(present: !missingCredentials))
        next.refreshSecretPresence()
        let expectedConfigurationError: String? = command.state == "missingConfig" ? "codex_not_configured"
            : missingCredentials ? "credentials_missing" : nil
        guard next.researchConfigurationErrorCode == expectedConfigurationError else {
            throw HarnessError.invalidFixtureConfiguration
        }
        let localization = LocalizationStore(preference: config.uiLanguage)
        let nextPresentation = WindowPresentationState()
        // Diagnostic lifecycle setup is fixture state, not evidence of an AX control press.
        if command.mode == "reader", command.target == "diagnostic-reader" {
            next.selectReport(report.id)
        }
        let content: AnyView
        if command.mode == "settings" {
            #if TASK3A_INTERNAL_SETTINGS
            content = AnyView(WorkspaceSettingsView(store: next, localization: localization))
            #else
            throw HarnessError.settingsUnavailable
            #endif
        } else {
            content = AnyView(ResearchRadarRootView(store: next, localization: localization, presentation: nextPresentation))
        }
        rememberReaders()
        coordinator?.close()
        store = next
        self.localization = localization
        lastAction = [:]
        presentation = nextPresentation
        let window: WindowCoordinator
        let mounted = AnyView(content.id(command.id))
        if let existing = coordinator {
            window = existing
            guard let host = productionHost else {
                throw HarnessError.invalidCommand
            }
            host.rootView = mounted
        } else {
            window = WindowCoordinator { mounted }
            coordinator = window
            guard let host = hostingView(in: window.contentView) else {
                throw HarnessError.invalidCommand
            }
            productionHost = host
        }
        window.onVisibilityChange = { [weak nextPresentation] visible in nextPresentation?.isVisible = visible }
        guard let button = statusItem?.button else { throw HarnessError.controlNotFound }
        window.attach(to: button)
        window.setAppearance(config.uiAppearance)
        window.present(mode: mode, animated: false)
        try clickStatusItem()
    }

    func poll() {
        // Mirror production mode synchronization, without starting its scheduler.
        if let store { coordinator?.present(mode: store.runtime.windowMode, animated: false) }
        let input = root.appending(path: "command.json")
        guard FileManager.default.fileExists(atPath: input.path) else { return }
        do {
            let command = try JSONDecoder().decode(Command.self, from: Data(contentsOf: input))
            guard command.id != lastID else { return }
            lastID = command.id
            do {
                switch command.action {
                case "configure": try configure(command)
                case "closeReader":
                    guard coordinator?.popover.isShown == true else { throw HarnessError.invalidCommand }
                    try clickStatusItem()
                case "openReader":
                    if coordinator?.popover.isShown == false { try clickStatusItem() }
                    else { try press("action.open_report") }
                case "inspect", "snapshot": break
                case "clickStatusItem": try clickStatusItem()
                case "pressEscape": try pressEscape()
                case "prepareOutsideTarget": try prepareOutsideTarget()
                case "clickOutsideTarget": try clickOutsideTarget()
                case "removeOutsideTarget": outsideWindow?.orderOut(nil); outsideWindow = nil
                case "press": try press(command.target)
                case "editTopicName": editTopicName()
                case "dismissAndIdle":
                    coordinator?.close()
                    timer?.invalidate()
                    timer = nil
                case "idle":
                    timer?.invalidate()
                    timer = nil
                case "quit": NSApp.terminate(nil)
                default: throw HarnessError.invalidCommand
                }
                try respond(command.id, includeAccessibility: ["snapshot", "press", "editTopicName"].contains(command.action))
            } catch { try respond(command.id, error: String(describing: error), includeAccessibility: true) }
        } catch {
            FileHandle.standardError.write(Data("Harness command failed: \(error)\n".utf8))
            NSApp.terminate(nil)
        }
    }

    func respond(_ id: String, error: String? = nil, includeAccessibility: Bool = false) throws {
        let views = webViews(coordinator?.contentView)
        let window = coordinator?.window
        let size = coordinator?.contentView.bounds.size ?? .zero
        let available = statusItem?.button?.window?.screen?.visibleFrame.size ?? .zero
        let mode = store?.runtime.windowMode ?? .compact
        let expected = WindowCoordinator.contentSize(for: mode, available: available)
        let buttonRect: NSRect?
        if let button = statusItem?.button, let statusWindow = button.window {
            buttonRect = statusWindow.convertToScreen(button.convert(button.bounds, to: nil))
        } else { buttonRect = nil }
        let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        let owned = windows.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(getpid()) }
        let allWindows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        var result: [String: Any] = ["id": id, "pid": Int(getpid()),
            "last_action": lastAction,
            "cg_event_posting_available": CGPreflightPostEventAccess(),
            "status_action_count": statusActionCount,
            "outside_click_count": outsideClickCount,
            "window_mode": store?.runtime.windowMode.rawValue ?? "",
            "configuration_error": store?.researchConfigurationErrorCode ?? "",
            "popover_shown": coordinator?.popover.isShown ?? false,
            "status_item_present": statusItem?.button?.window != nil,
            "status_anchor_visible": statusItem?.button?.window?.isVisible ?? false,
            "expected_width": expected.width, "expected_height": expected.height,
            "available_width": available.width, "available_height": available.height,
            "selected_report_id": store?.selectedReportID?.uuidString ?? "",
            "presentation_visible": presentation.isVisible,
            "is_key_window": window?.isKeyWindow ?? false,
            "is_main_window": window?.isMainWindow ?? false,
            "app_active": NSApp.isActive,
            "window_visible": window?.isVisible ?? false,
            "window_miniaturized": window?.isMiniaturized ?? false,
            "app_hidden": NSApp.isHidden,
            "occlusion_visible": window?.occlusionState.contains(.visible) ?? false,
            "window_frame": window.map { NSStringFromRect($0.frame) } ?? "",
            "screens": NSScreen.screens.map { ["frame": NSStringFromRect($0.frame), "visible_frame": NSStringFromRect($0.visibleFrame)] },
            "screen_count": NSScreen.screens.count,
            "cg_owned_all": allWindows.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(getpid()) },
            "window_id": window?.windowNumber ?? 0, "cg_windows": owned,
            "width": size.width, "height": size.height,
            "webview_count": views.count, "retired_observed": retired.count,
            "retired_alive": retired.filter { $0.value != nil }.count,
            "webviews": views.map { ["url": $0.url?.absoluteString ?? "", "loading": $0.isLoading] as [String: Any] }]
        if let buttonRect, let primary = NSScreen.screens.first {
            result["status_capture_rect"] = [buttonRect.minX, primary.frame.maxY - buttonRect.maxY,
                                             buttonRect.width, buttonRect.height]
        }
        if let today = store?.todayPresentation,
           let attempt = today.latestAttemptReport, let outcome = attempt.researchOutcome {
            result["outcome_fixture"] = [
                "status": outcome.status.rawValue,
                "reasons": outcome.reasons.map(\.rawValue),
                "deep_read_count": attempt.deepReadCount,
                "publishable_claim_count": attempt.publishableClaimCount,
                "today_status": today.status.rawValue
            ] as [String: Any]
        }
        if includeAccessibility {
            let nodes = accessibilityNodes(window)
            result["accessibility"] = nodes.map { node -> [String: Any] in
                ["role": node.accessibilityRole()?.rawValue ?? "", "labels": labels(node),
                 "selected": node.isAccessibilitySelected()]
            }
            result["selected_rows"] = nodes.filter {
                $0.accessibilityRole() == .row && $0.isAccessibilitySelected()
            }.map { accessibilityNodes($0).flatMap { labels($0) } }
            result["control_labels"] = ["action.full_workspace", "action.compact"].map {
                localization?.text($0) ?? $0
            }
            result["saved_topic_name"] = store?.selectedTopic?.displayName ?? ""
            result["settings_label"] = localization?.text("nav.settings") ?? ""
        }
        if let error { result["error"] = error }
        try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            .write(to: root.appending(path: "response.json"), options: .atomic)
    }
}

@main enum VisualApp {
    @MainActor static func main() {
        guard let path = ProcessInfo.processInfo.environment["TASK3A_ROOT"] else {
            fatalError("Launch only through check_macos_presentation.py")
        }
        let app = NSApplication.shared
        let harness = Harness(root: URL(fileURLWithPath: path))
        app.setActivationPolicy(.accessory)
        app.delegate = harness
        withExtendedLifetime(harness) { app.run() }
    }
}
