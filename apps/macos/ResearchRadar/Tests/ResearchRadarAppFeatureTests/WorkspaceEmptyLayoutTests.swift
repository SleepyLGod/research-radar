import AppKit
import SwiftUI
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@MainActor @Suite struct WorkspaceEmptyLayoutTests {
    @Test func emptyLedgerKeepsFullWorkspaceHeight() async throws {
        _ = NSApplication.shared
        let root = try task3Root(); defer { task3Trash(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [.init(id: "memory", displayName: "Offline topic", researchFocus: "Layout",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese)]
        let store = AppStore(configuration: config, runtime: .init(selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: root, secretStore: EmptyLayoutNoSecrets())
        let model = PaperLedgerModel()
        await model.load(topicID: "memory", reports: []) { _, _ in .init(topicID: "memory", reportIDs: [], papers: []) }
        let presentation = WindowPresentationState(); presentation.isVisible = false
        let measurement = EmptyLayoutMeasurement()
        let content = PaperLedgerView(store: store, localization: LocalizationStore(preference: .english),
            presentation: presentation, model: model, open: { _, _, _ in })
            .onGeometryChange(for: CGSize.self) { $0.size } action: { measurement.size = $0 }
        let host = NSHostingView(rootView: GeometryReader { _ in content })
        host.sizingOptions = []
        let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 700, height: 600),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        try await Task.sleep(for: .milliseconds(150)); host.layoutSubtreeIfNeeded()
        let size = try #require(measurement.size)
        #expect(size.height >= 590)
        #expect(store.jobs.isEmpty && !store.isEngineRunning)
    }
}

@MainActor private final class EmptyLayoutMeasurement { var size: CGSize? }

private struct EmptyLayoutNoSecrets: SecretStoring {
    func contains(account: String) throws -> Bool { throw AppStoreError.invalidTopic }
    func read(account: String) throws -> Data? { throw AppStoreError.invalidTopic }
    func set(_ value: Data, account: String) throws { throw AppStoreError.invalidTopic }
    func remove(account: String) throws { throw AppStoreError.invalidTopic }
}
