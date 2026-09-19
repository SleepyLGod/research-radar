import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct NativeViewTests {
    @Test func captureBilingualNativeLayoutsWhenRequested() async throws {
        guard let path = ProcessInfo.processInfo.environment["RESEARCH_RADAR_UI_EVIDENCE_ROOT"],
              !path.isEmpty else { return }
        #expect(path.hasPrefix("/"))
        guard path.hasPrefix("/") else { throw CocoaError(.fileWriteInvalidFileName) }
        let output = URL(fileURLWithPath: path, isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for language in [AppLanguagePreference.english, .simplifiedChinese] {
            let chinese = language == .simplifiedChinese
            let root = FileManager.default.temporaryDirectory.appending(path: "native-layout-\(UUID().uuidString)")
            var config = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
            config.uiLanguage = language
            let topic = TopicRecordV1(
                id: "agent-memory", displayName: chinese ? "智能体记忆" : "Agent memory",
                researchFocus: chinese ? "检索、记忆维护与评估" : "Retrieval, memory maintenance and evaluation",
                queries: ["agent memory", "memory maintenance"], paperQueries: ["agent memory evaluation"],
                exclusionTerms: ["advertisement"], conceptGroups: ["Memory": ["agent memory", "long-term recall"]],
                negativePhrases: ["sponsored content"], reportLanguage: chinese ? .chinese : .english
            )
            config.topics = [topic]
            let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()),
                appSupportRoot: root, secretStore: ViewTestSecrets())
            let localization = LocalizationStore(preference: language)
            try await capture(
                TopicEditorView(store: store, localization: localization, topic: topic),
                size: NSSize(width: 760, height: 1100),
                to: output.appending(path: "topic-\(language.rawValue).png")
            )
            try await capture(
                Form {
                    AppLanguagePicker(store: store, localization: localization)
                    ProviderSettingsView(store: store, localization: localization)
                    Section(localization.text("setting.storage")) {
                        CacheLimitView(store: store, localization: localization)
                    }
                }.formStyle(.grouped),
                size: NSSize(width: 760, height: 720),
                to: output.appending(path: "settings-\(language.rawValue).png")
            )
            store.performAction { throw AppStoreError.invalidTopic }
            try await capture(
                AppActionErrorView(store: store, localization: localization).padding(24),
                size: NSSize(width: 760, height: 220),
                to: output.appending(path: "error-\(language.rawValue).png")
            )
            #expect(store.configuration == config)
            #expect(store.jobs.isEmpty)
        }
    }

    // These are rendered view snapshots, not input-event or end-to-end tests.
    private func capture<Content: View>(_ content: Content, size: NSSize, to url: URL) async throws {
        _ = NSApplication.shared
        let bounds = NSRect(origin: .zero, size: size)
        let hosting = NSHostingView(rootView: content.environment(\.colorScheme, .light))
        let window = NSWindow(contentRect: bounds, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .aqua)
        window.contentView = hosting
        window.setContentSize(size)
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        await Task.yield()
        try await Task.sleep(for: .milliseconds(100))
        hosting.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        let bitmap = try #require(hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds))
        hosting.cacheDisplay(in: hosting.bounds, to: bitmap)
        #expect(bitmap.pixelsWide > 0 && bitmap.pixelsHigh > 0)
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        #expect(!png.isEmpty)
        try png.write(to: url, options: .atomic)
    }

    @Test func topicEditorAndSettingsLayOutWithFakeServices() {
        let root = FileManager.default.temporaryDirectory.appending(path: "view-test-unused")
        var config = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
        let topic = TopicRecordV1(id: "memory", displayName: "Agent memory", researchFocus: "Retrieval and maintenance", queries: ["agent memory"], paperQueries: ["agent memory evaluation"], reportLanguage: .english)
        config.topics = [topic]
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root, secretStore: ViewTestSecrets())
        let localization = LocalizationStore(preference: .english)
        let editor = NSHostingView(rootView: TopicEditorView(store: store, localization: localization, topic: topic))
        editor.frame = NSRect(x: 0, y: 0, width: 620, height: 700)
        editor.layoutSubtreeIfNeeded()
        #expect(editor.fittingSize.width > 0)
        let providers = NSHostingView(rootView: ProviderSettingsView(store: store, localization: localization))
        providers.frame = NSRect(x: 0, y: 0, width: 680, height: 500)
        providers.layoutSubtreeIfNeeded()
        #expect(providers.fittingSize.height > 0)
        #expect(store.configuration == config)
    }
}

private struct ViewTestSecrets: SecretStoring {
    func set(_ value: Data, account: String) throws {}
    func read(account: String) throws -> Data? { nil }
    func contains(account: String) throws -> Bool { false }
    func remove(account: String) throws {}
}
