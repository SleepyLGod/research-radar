import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

private actor BootstrapRunner: EngineProcessRunning {
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let requestIndex = try #require(arguments.firstIndex(of: "--request"))
        let resultIndex = try #require(arguments.firstIndex(of: "--result"))
        let request = try EngineProtocolCodec.decodeRequest(
            Data(contentsOf: URL(fileURLWithPath: arguments[requestIndex + 1]))
        )
        let draft = TopicDraftV1(
            id: "robotics", displayName: "Robot Foundation Models",
            researchFocus: "Robot foundation models", queries: ["robot foundation models"],
            paperQueries: ["robot foundation model benchmark"], reportLanguage: .english
        )
        let result = EngineResultV1(
            requestID: request.requestID, command: .bootstrapTopic, status: .succeeded,
            completedAt: Date(), topicDraft: draft
        )
        try EngineProtocolCodec.encode(result).write(
            to: URL(fileURLWithPath: arguments[resultIndex + 1])
        )
        return EngineProcessOutcome(
            exitCode: 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data()
        )
    }
    func cancel() async {}
}

@MainActor @Suite struct AppStoreTests {
    @Test func approvingTopicPersistsTypedProfileWithoutChangingUILanguage() throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        let config = AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil
        )
        let runtime = AppRuntimeStateV1(updatedAt: Date(timeIntervalSince1970: 1))
        let store = AppStore(configuration: config, runtime: runtime, appSupportRoot: root)
        let draft = TopicDraftV1(
            id: "llm-inference", displayName: "LLM Inference",
            researchFocus: "Serving systems", queries: ["LLM inference"],
            paperQueries: ["LLM serving benchmark"], reportLanguage: .chinese
        )

        try store.approveTopic(draft)

        #expect(store.configuration.uiLanguage == .system)
        #expect(store.configuration.topics.first?.reportLanguage == .chinese)
        let persisted = try AtomicJSONStore(root: root).read(
            AppConfigurationV1.self, from: "config/app-config.json"
        )
        #expect(persisted.topics.first?.id == "llm-inference")
    }

    @Test func bootstrapUsesTypedBridgeAndRequiresApprovalBeforePersistingTopic() async throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        let config = AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil
        )
        let store = AppStore(
            configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()),
            appSupportRoot: root, engineURL: URL(fileURLWithPath: "/fake/engine"),
            runner: BootstrapRunner()
        )

        await store.bootstrapTopic(description: "robot foundation models", language: .english)

        #expect(store.topicDraft?.id == "robotics")
        #expect(store.configuration.topics.isEmpty)
        try store.approveTopic(try #require(store.topicDraft))
        #expect(store.configuration.topics.first?.id == "robotics")
    }

    @Test func legacyLaunchdConflictBlocksAppSchedule() throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        var config = AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil
        )
        config.topics = [TopicRecordV1(
            id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["agent memory"], reportLanguage: .chinese
        )]
        let store = AppStore(
            configuration: config,
            runtime: AppRuntimeStateV1(updatedAt: Date()),
            appSupportRoot: root,
            legacyScheduleTopics: ["memory"]
        )

        #expect(throws: AppStoreError.legacyScheduleConflict("memory")) {
            try store.setDailySchedule(
                topicID: "memory", hour: 9, minute: 0,
                enabled: true, deliveryChannels: []
            )
        }
        #expect(store.schedules.isEmpty)
    }
}

private func appStoreRoot() throws -> URL {
    let url = FileManager.default.temporaryDirectory.appending(path: "app-store-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false); return url
}
private func trashAppStoreRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
