import AppKit
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor struct WorkspacePaneLayoutTests {
    @Test(arguments: [false, true], [AppLanguagePreference.english, .simplifiedChinese])
    func groupedFormsUseTheWholeContentPane(diagnostics: Bool, language: AppLanguagePreference) async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        defer { task3Trash(root) }
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let store = AppStore(configuration: config,
            runtime: .init(onboardingStep: .complete, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let localization = LocalizationStore(preference: language)
        let content = diagnostics
            ? AnyView(WorkspaceDiagnosticsView(store: store, localization: localization))
            : AnyView(WorkspaceSettingsView(store: store, localization: localization))
        let host = NSHostingView(rootView: content)
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 520),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        try await Task.sleep(for: .milliseconds(250))
        host.layoutSubtreeIfNeeded()
        let scroll = try #require(reportViewDescendants(host).compactMap { $0 as? NSScrollView }
            .max(by: { $0.bounds.width < $1.bounds.width }))
        let frame = scroll.convert(scroll.bounds, to: host)
        #expect(abs(frame.minX) <= 1)
        #expect(abs(frame.maxX - host.bounds.maxX) <= 1)
        #expect(abs(frame.minY) <= 1)
        #expect(abs(frame.maxY - host.bounds.maxY) <= 1)
    }
}
