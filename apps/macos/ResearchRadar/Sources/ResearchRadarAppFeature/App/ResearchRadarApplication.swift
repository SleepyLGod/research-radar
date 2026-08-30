import AppKit
import SwiftUI

@MainActor
private final class AppContainer {
    let localization: LocalizationStore
    let store: AppStore?
    let launchError: String?
    private var scheduleEventObserver: ScheduleEventObserver?

    init() {
        let root = (try? FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true
        ))?.appending(path: "ResearchRadar", directoryHint: .isDirectory)
        if let root {
            do {
                let loaded = try AppBootstrapService(appSupportRoot: root).load(
                    engineURL: EngineLocation.bundledFoundationEngine()
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
            return AnyView(ResearchRadarRootView(store: store, localization: localization))
        }
        return AnyView(LaunchFailureView(localization: localization, code: launchError ?? "engine_crashed"))
    }
    lazy var statusItem = StatusItemController(
        localization: localization,
        showWindow: { [weak self] in self?.window.show() },
        runNow: { [weak self] in
            guard let store = self?.store else { return }
            Task { await store.runSelectedTopicNow() }
        },
        pauseSchedules: { [weak self] in
            guard let store = self?.store else { return }
            try? store.setSchedulesPaused(!store.runtime.schedulesPaused)
        },
        schedulesPaused: { [weak self] in self?.store?.runtime.schedulesPaused ?? false },
        quit: { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                await self.store?.cancelActiveJob()
                await self.store?.stopScheduling()
                self.scheduleEventObserver?.stop()
                NSApp.terminate(nil)
            }
        }
    )

    func start() {
        _ = statusItem
        localization.onChange = { [weak self] in
            guard let self else { return }
            try? self.store?.setUILanguage(self.localization.preference)
            self.statusItem.refresh()
        }
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
}

private struct LaunchFailureView: View {
    let localization: LocalizationStore
    let code: String
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(localization.text("error.state_unavailable"), systemImage: "exclamationmark.triangle.fill")
                .font(.title3.weight(.semibold)).foregroundStyle(.orange)
            Text(localization.text("error.state_unavailable_detail")).foregroundStyle(.secondary)
            Text(code).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
        }.padding(28).frame(minWidth: 520, minHeight: 260)
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
