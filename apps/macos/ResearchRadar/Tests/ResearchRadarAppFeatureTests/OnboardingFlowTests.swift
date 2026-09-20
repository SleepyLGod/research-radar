import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct OnboardingFlowTests {
    @Test func presentationChangesPreservePreflightAndNeverReadSecretValues() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let store = AppStore(configuration: config, runtime: .init(updatedAt: Date()), appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/fixture/engine"), runner: OnboardingRunner(), secretStore: AdmissionSecrets())
        await store.testConnections()
        let preflight = try #require(store.preflight)
        try store.setUIAppearance(.light)
        try store.setUILanguage(.simplifiedChinese)
        try store.setOnboardingStep(.providers)
        #expect(store.preflight == preflight)
        try store.setCodexReasoningEffort("high")
        #expect(store.preflight == nil)
        await store.shutdown()
    }

    @Test(arguments: ["config", "state"])
    func failedWritesRetainConfigurationProgressAndTopicInput(blocked: String) async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let store = makeStore(root)
        try store.setUIAppearance(.light)
        try store.setOnboardingStep(.topicDescription)
        let original = store.configuration
        let runtime = store.runtime
        let input = TopicEditorInput(topic: topic())
        try FileManager.default.moveItem(at: root.appending(path: blocked), to: root.appending(path: "backup-\(blocked)"))
        try Data("blocked".utf8).write(to: root.appending(path: blocked))
        #expect(!store.performAction { try store.saveTopic(input.candidate(), creating: true) })
        #expect(store.lastErrorCode == "configuration_write_failed")
        #expect(store.configuration == original)
        #expect(store.runtime.onboardingStep == runtime.onboardingStep)
        #expect(store.requiresOnboarding)
        #expect(try input.candidate() == topic())
        if blocked == "config" {
            #expect(throws: (any Error).self) { try store.setUIAppearance(.dark) }
            #expect(store.configuration.uiAppearance == .light)
        }
        await store.shutdown()
    }

    @Test func firstRunFailureUsesExistingRetryFlowAndDoesNotReopenWizard() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        let store = AppStore(configuration: config, runtime: .init(updatedAt: Date()), appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/fixture/engine"), runner: OnboardingRunner(), secretStore: AdmissionSecrets())
        try store.saveTopic(topic(), creating: true)
        #expect(store.requiresOnboarding)
        #expect(store.jobs.isEmpty)
        await store.startOnboardingResearch()
        #expect(!store.requiresOnboarding)
        #expect(store.jobs.count == 1)
        #expect(store.jobs.first?.state == .failed)
        #expect(store.todayPresentation.failureCode == "model_transport_failed")
        let view = TodayContentView(store: store, localization: LocalizationStore(), compact: true, openReport: { _ in })
        #expect(view.showsResearchFailure)
        await view.confirmRunAgain()
        #expect(store.jobs.count == 2)
        #expect(store.jobs.allSatisfy { $0.state == .failed && $0.requestedDeliveryChannels.isEmpty })
        #expect(!store.requiresOnboarding)
        #expect(store.schedules.isEmpty)
        await store.shutdown()
    }

    @Test func firstTopicKeepsReadyPageAcrossRestartUntilExplicitCompletion() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let store = makeStore(root)
        #expect(store.requiresOnboarding)
        try store.setOnboardingStep(.providers)
        try store.setUIAppearance(.dark)
        try store.setUILanguage(.english)
        try store.setOnboardingStep(.topicDescription)
        try store.saveTopic(topic(), creating: true)
        #expect(store.requiresOnboarding)
        #expect(store.onboardingPage == .preflight)
        #expect(store.jobs.isEmpty)
        #expect(store.schedules.isEmpty)
        #expect(!store.configuration.delivery.email.enabled)
        let persistence = AtomicJSONStore(root: root)
        let restored = AppStore(configuration: try persistence.read(AppConfigurationV1.self, from: "config/app-config.json"),
            runtime: try persistence.read(AppRuntimeStateV1.self, from: "state/app-state.json"),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        #expect(restored.requiresOnboarding)
        #expect(restored.onboardingPage == .preflight)
        #expect(restored.configuration.uiAppearance == .dark)
        #expect(restored.configuration.uiLanguage == .english)
        #expect(restored.selectedTopic?.deepReadLimit == 7)
        try restored.completeOnboarding()
        #expect(!restored.requiresOnboarding)
        #expect(restored.jobs.isEmpty)
        #expect(try persistence.read(AppRuntimeStateV1.self, from: "state/app-state.json").onboardingStep == .complete)
        await store.shutdown()
        await restored.shutdown()
    }

    @Test func existingUsersAreNotForcedThroughNewFlow() {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let store = makeStore(root, topics: [topic()])
        #expect(!store.requiresOnboarding)
        #expect(store.runtime.onboardingStep == .storage)
    }

    @Test func cannotSkipTopicAndConfigurationFailureKeepsReadyPage() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let store = makeStore(root)
        #expect(throws: AppStoreError.invalidTopic) { try store.completeOnboarding() }
        try store.saveTopic(topic(), creating: true)
        await store.startOnboardingResearch()
        #expect(store.requiresOnboarding)
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == "codex_not_configured")
        await store.shutdown()
    }

    @Test func independentSavesClearOnlySuccessfullySubmittedSecret() throws {
        var draft = ProviderCredentialDraft(deepSeekKey: "fixture-deepseek", searchKey: "fixture-search")
        var submitted: [String] = []
        try draft.saveDeepSeek { name, _ in submitted.append(name) }
        #expect(submitted == ["deepseek.api_key"])
        #expect(draft.deepSeekKey.isEmpty)
        #expect(draft.searchKey == "fixture-search")
        #expect(throws: KeychainStoreError.invalidAccount) {
            try draft.saveSearch { _, _ in throw KeychainStoreError.invalidAccount }
        }
        #expect(draft.searchKey == "fixture-search")
        try draft.saveSearch { name, _ in submitted.append(name) }
        #expect(submitted == ["deepseek.api_key", "web_search.api_key"])
        #expect(draft.searchKey.isEmpty)
    }

    @Test func checkFailuresNeverEchoRawPayloadAndTavilyHasOwnLabel() throws {
        let privatePath = "/" + "Users/fixture-private"
        let payload: [String: Any] = ["id": "web_search", "provider": "tavily", "model": NSNull(),
            "status": "action_required", "message": "HTTP 401 token=fixture-secret \(privatePath)"]
        let check = try JSONDecoder().decode(PreflightCheckV1.self, from: JSONSerialization.data(withJSONObject: payload))
        #expect(SettingsPresentation.checkLabelKey(id: check.id) == "check.name.web_search")
        #expect(SettingsPresentation.failureDetailKey(for: check) == "check.failure.web_search")
        let text = SettingsPresentation.safeCheckMessage(check.message)
        #expect(text.contains("HTTP 401"))
        #expect(!text.contains("fixture-secret"))
        #expect(!text.contains(privatePath))
        #expect(SettingsPresentation.safeCheckMessage("Search connectivity check failed: HTTP 429 [REDACTED]")
            == "Search connectivity check failed: HTTP 429 [REDACTED]")
    }

    @Test func themeUpdatesRetainedPopoverAndClearsOverridesForSystem() throws {
        _ = NSApplication.shared
        let coordinator = WindowCoordinator { AnyView(Text("Fixture")) }
        let content = coordinator.contentView
        coordinator.setAppearance(.dark)
        #expect(NSApp.appearance?.name == .darkAqua)
        #expect(coordinator.popover.appearance?.name == .darkAqua)
        #expect(content.appearance?.name == .darkAqua)
        #expect(AppAppearancePreference.dark.colorScheme == .dark)
        coordinator.close()
        coordinator.setAppearance(.light)
        #expect(coordinator.popover.appearance?.name == .aqua)
        #expect(content.appearance?.name == .aqua)
        coordinator.setAppearance(.system)
        #expect(NSApp.appearance == nil)
        #expect(coordinator.popover.appearance == nil)
        #expect(content.appearance == nil)
        #expect(AppAppearancePreference.system.colorScheme == nil)
        #expect(coordinator.contentView === content)
    }

    private func makeStore(_ root: URL, topics: [TopicRecordV1] = []) -> AppStore {
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = topics
        return AppStore(configuration: config, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
    }

    private func topic() -> TopicRecordV1 {
        TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall", queries: ["memory"],
            paperQueries: ["memory"], reportLanguage: .english, deepReadLimit: 7)
    }

    private func trash(_ root: URL) {
        guard FileManager.default.fileExists(atPath: root.path) else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
        process.arguments = [root.path]
        do { try process.run(); process.waitUntilExit(); #expect(process.terminationStatus == 0) }
        catch { Issue.record(error) }
    }
}

private actor OnboardingRunner: EngineProcessRunning {
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let input = try #require(arguments.firstIndex(of: "--request"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: URL(fileURLWithPath: arguments[input + 1])))
        if request.command == .preflight {
            let output = try #require(arguments.firstIndex(of: "--result"))
            let summary = try JSONDecoder().decode(PreflightSummaryV1.self, from: Data(#"{"ready":true,"checks":[]}"#.utf8))
            let result = EngineResultV1(requestID: request.requestID, command: .preflight, status: .succeeded,
                completedAt: Date(), preflight: summary)
            try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[output + 1]))
        } else {
            #expect(request.command == .runDaily)
            let output = try #require(arguments.firstIndex(of: "--error"))
            let error: [String: Any] = ["schema_version": 1, "request_id": request.requestID.uuidString.lowercased(),
                "status": "failed", "stage": "source_gist", "code": "model_transport_failed",
                "message": "Offline fixture failure", "retryable": true, "completed_at": "2026-09-20T00:00:00Z"]
            try JSONSerialization.data(withJSONObject: error).write(to: URL(fileURLWithPath: arguments[output + 1]))
        }
        return EngineProcessOutcome(exitCode: request.command == .preflight ? 0 : 1,
            startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
}
