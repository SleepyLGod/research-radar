import AppKit
import SwiftUI
import Observation
import ResearchRadarCore

@MainActor
private final class AppContainer {
    let localization: LocalizationStore
    let store: AppStore?
    let launchError: String?
    let presentation = WindowPresentationState()
    private var scheduleEventObserver: ScheduleEventObserver?

    init() {
        let root = try? AppDataLocation.root()
        if let root {
            do {
                let loaded = try AppBootstrapService(appSupportRoot: root).load(
                    engineURL: EngineLocation.bundledFoundationEngine(),
                    pdfHelperURL: EngineLocation.bundledPDFHelper()
                )
                store = loaded; launchError = nil
                localization = LocalizationStore(preference: loaded.configuration.uiLanguage)
                return
            } catch {
                store = nil; launchError = "durable_state_invalid"
            }
        } else {
            store = nil; launchError = "app_support_unavailable"
        }
        localization = LocalizationStore()
    }

    lazy var window = WindowCoordinator {
        if let store {
            return AnyView(ResearchRadarRootView(store: store, localization: localization, presentation: presentation))
        }
        return AnyView(LaunchFailureView(localization: localization, code: launchError ?? "engine_crashed"))
    }
    lazy var statusItem = StatusItemController(
        localization: localization,
        showWindow: { [weak self] in self?.window.toggle() },
        runNow: { [weak self] in
            guard let store = self?.store else { return }
            Task { await store.runSelectedTopicNow() }
        },
        pauseSchedules: { [weak self] in
            guard let store = self?.store else { return }
            store.performAction { try store.setSchedulesPaused(!store.runtime.schedulesPaused) }
        },
        schedulesPaused: { [weak self] in self?.store?.runtime.schedulesPaused ?? false },
        quit: { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                self.scheduleEventObserver?.stop()
                await self.store?.shutdown()
                NSApp.terminate(nil)
            }
        }
    )

    func start() {
        _ = statusItem
        if let button = statusItem.button { window.attach(to: button) }
        window.onVisibilityChange = { [weak self] visible in self?.presentation.isVisible = visible }
        observePresentation()
        window.show()
        if let store {
            scheduleEventObserver = ScheduleEventObserver { [weak store] in
                Task { await store?.startScheduling() }
            }
            scheduleEventObserver?.start()
            Task {
                await store.reconcileAfterLaunch()
                await store.startScheduling()
            }
        }
    }

    private func observePresentation() {
        withObservationTracking {
            guard let store else { return }
            let mode = store.requiresOnboarding ? WindowMode.full : store.runtime.windowMode
            window.setAppearance(store.configuration.uiAppearance)
            window.present(mode: mode, animated: window.popover.isShown)
            let today = store.todayPresentation
            let active = store.engineStatusPresentation
            let state: String
            if let active {
                state = active.job.state == .cancelling ? "today.cancelling"
                    : active.job.stage.map { "stage.\($0.rawValue)" }
                    ?? (active.job.kind == .delivery ? "today.delivering" : "today.running")
            } else {
                state = store.isEngineRunning ? "today.checking" : today.statusKey
            }
            statusItem.refresh(status: localization.text(state), topic: active?.topic?.displayName ?? store.selectedTopic?.displayName)
        } onChange: { [weak self] in
            Task { @MainActor [weak self] in self?.observePresentation() }
        }
    }
}

private struct LaunchFailureView: View {
    let localization: LocalizationStore
    let code: String
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(localization.text("error.state_unavailable"), systemImage: "exclamationmark.triangle.fill")
                .font(.title3.weight(.semibold)).foregroundStyle(.orange)
            Text(localization.text("error.state_unavailable_detail")).foregroundStyle(.secondary)
            Text(code).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
        }.padding(20).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

@MainActor
private final class ResearchRadarAppDelegate: NSObject, NSApplicationDelegate {
    private var container: AppContainer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let container = AppContainer()
        self.container = container
        container.start()
    }
}

@MainActor
public func runResearchRadarApplication() {
    let application = NSApplication.shared
    application.setActivationPolicy(.accessory)
    let delegate = ResearchRadarAppDelegate()
    application.delegate = delegate
    application.run()
    withExtendedLifetime(delegate) {}
}
