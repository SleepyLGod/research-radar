import AppKit
import SwiftUI

@MainActor
private final class AppContainer {
    let localization = LocalizationStore()
    let model = FoundationViewModel()
    lazy var window = WindowCoordinator {
        AnyView(FoundationView(model: model, localization: localization))
    }
    lazy var statusItem = StatusItemController(
        localization: localization,
        showWindow: { [weak self] in self?.window.show() },
        quit: { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                await self.model.cancel()
                NSApp.terminate(nil)
            }
        }
    )

    func start() {
        _ = statusItem
        localization.onChange = { [weak self] in self?.statusItem.refresh() }
        window.show()
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
