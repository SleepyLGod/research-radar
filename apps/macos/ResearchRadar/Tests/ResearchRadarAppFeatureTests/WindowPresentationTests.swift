import AppKit
import ResearchRadarCore
import SwiftUI
import Testing
import WebKit
@testable import ResearchRadarAppFeature

@MainActor @Suite struct WindowPresentationTests {
    @Test func reportPreviewsDoNotPreloadReaderInsideRetainedWorkspace() async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        let fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        var config = AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot, codexExecutable: nil)
        config.topics = [.init(id: "reader", displayName: "Reader", researchFocus: "Offline",
            queries: ["offline"], paperQueries: ["offline"], reportLanguage: .english)]
        let report = fixture.report
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: [report]),
            runtime: .init(onboardingStep: .complete, windowMode: .full,
                selectedTopicID: "reader", updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        store.selectReport(report.id)
        let host = NSHostingView(rootView: ResearchRadarRootView(store: store,
            localization: LocalizationStore(preference: .english)))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 660),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        func descendants(_ view: NSView) -> [NSView] {
            [view] + view.subviews.flatMap { descendants($0) }
        }
        try await Task.sleep(for: .milliseconds(200))
        #expect(!descendants(host).contains(where: { $0 is WKWebView }))

        try store.setWindowMode(.compact)
        try await Task.sleep(for: .milliseconds(200))
        #expect(!descendants(host).contains(where: { $0 is WKWebView }))
        #expect(store.selectedReportID == report.id)
        #expect(try Data(contentsOf: fixture.root.appending(path: "wechat.html")) == Data(fixture.html.utf8))
    }

    @Test func compactModeRemovesHiddenSidebarFromKeyboardNavigation() async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        defer { task3Trash(root) }
        let store = task3Store(root: root)
        try store.setWindowMode(.full)
        let presentation = WindowPresentationState()
        let host = NSHostingView(rootView: ResearchRadarRootView(store: store,
            localization: LocalizationStore(preference: .english), presentation: presentation))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 660),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        func descendants(_ view: NSView) -> [NSView] {
            [view] + view.subviews.flatMap { descendants($0) }
        }
        try await Task.sleep(for: .milliseconds(250))
        host.layoutSubtreeIfNeeded()
        let sidebar = try #require(descendants(host).compactMap { $0 as? NSOutlineView }.first)
        #expect(sidebar.canBecomeKeyView)

        try store.setWindowMode(.compact)
        try await Task.sleep(for: .milliseconds(250))
        host.layoutSubtreeIfNeeded()
        #expect(!sidebar.canBecomeKeyView)

        try store.setWindowMode(.full)
        try await Task.sleep(for: .milliseconds(250))
        host.layoutSubtreeIfNeeded()
        #expect(descendants(host).contains { $0 === sidebar })
        #expect(sidebar.canBecomeKeyView)
    }

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
