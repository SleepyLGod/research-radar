import AppKit
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct WindowPresentationTests {
    @Test func presentingSettingsAndChangingLanguageOrModeNeverReadsSecrets() async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        defer { task3Trash(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        // This dependency records a test failure on every value read, not on metadata queries.
        let store = AppStore(configuration: config, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let localization = LocalizationStore(preference: .english)
        let presentation = WindowPresentationState()
        let host = NSHostingView(rootView: ResearchRadarRootView(
            store: store, localization: localization, presentation: presentation))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 660),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        for language: AppLanguagePreference in [.english, .simplifiedChinese] {
            try store.setUILanguage(language)
            localization.preference = language
            for mode: WindowMode in [.full, .compact, .full] {
                try store.setWindowMode(mode)
                presentation.requestedSection = .settings
                presentation.isVisible = true
                try await Task.sleep(for: .milliseconds(150))
                host.layoutSubtreeIfNeeded()
                presentation.isVisible = false
            }
        }
    }

    @Test func productionRootKeepsOneAnchoredPopoverAfterModeTransitions() async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        defer { task3Trash(root) }
        let store = task3Store(root: root)
        try store.setWindowMode(.full)
        let localization = LocalizationStore(preference: .english)
        let presentation = WindowPresentationState()
        let coordinator = WindowCoordinator {
            AnyView(ResearchRadarRootView(store: store, localization: localization, presentation: presentation))
        }
        let originalHost = coordinator.contentView
        let popover = coordinator.popover

        for mode: WindowMode in [.full, .compact, .full] {
            try store.setWindowMode(mode)
            coordinator.present(mode: mode, animated: false)
            let expectedContent = mode == .compact ? NSSize(width: 400, height: 480) : NSSize(width: 900, height: 660)
            for _ in 0..<2 {
                try await Task.sleep(for: .milliseconds(150))
                coordinator.contentView.layoutSubtreeIfNeeded()
                #expect(popover.contentSize.width <= expectedContent.width)
                #expect(popover.contentSize.height <= expectedContent.height)
                #expect(coordinator.contentView === originalHost)
            }
            #expect(coordinator.popover === popover)
        }
    }

    @Test func contentSizeStaysWithinCurrentDisplay() {
        let coordinator = WindowCoordinator { AnyView(Text("ResearchRadar")) }
        let original = coordinator.popover
        coordinator.present(mode: .compact, animated: false)
        #expect(coordinator.popover === original)
        #expect(coordinator.popover.contentSize == NSSize(width: 400, height: 480))
        coordinator.present(mode: .full, animated: false)
        #expect(coordinator.popover === original)
        let size = WindowCoordinator.contentSize(for: .full, available: NSSize(width: 720, height: 540))
        #expect(size.width < 720)
        #expect(size.height < 540)
        #expect(!coordinator.popoverShouldDetach(coordinator.popover))
    }

    @Test func closingPopoverReleasesVisibilityWithoutDestroyingContent() {
        let coordinator = WindowCoordinator { AnyView(Text("ResearchRadar")) }
        var visible = true
        coordinator.onVisibilityChange = { visible = $0 }
        let content = coordinator.contentView
        coordinator.close()
        #expect(!visible)
        #expect(coordinator.contentView === content)
    }
}
