import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@Suite @MainActor struct ReaderBudgetSettingsTests {
    @Test func missingChineseWriterBudgetDoesNotStopEnglishSchedule() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        var config = ReaderBudgetTestConfiguration.declaringBudgets(AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"), codexExecutable: URL(fileURLWithPath: "/usr/bin/true")))
        let writerIndex = try #require(config.routes.firstIndex { $0.task == "report_localization" })
        config.routes[writerIndex] = RouteRecordV1(task: "report_localization",
            providerID: "deepseek", model: "independent-writer")
        config.topics = [
            TopicRecordV1(id: "chinese", displayName: "Chinese", researchFocus: "Memory",
                queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese),
            TopicRecordV1(id: "english", displayName: "English", researchFocus: "Memory",
                queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english),
        ]
        let store = AppStore(configuration: config, scheduleSnapshot: .init(schedules: [
            DailyScheduleV1(topicID: "chinese", hour: 0, minute: 0),
            DailyScheduleV1(topicID: "english", hour: 0, minute: 0),
        ]), runtime: .init(selectedTopicID: "chinese", updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        await store.startScheduling()
        #expect(store.jobs.map(\.topicID) == ["english"])
        #expect(store.researchConfigurationErrorCode == "reader_context_unknown")
        await store.shutdown()
    }

    @Test func independentWriterBudgetIsEditableAndOnlyBlocksChineseTopic() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        var config = ReaderBudgetTestConfiguration.declaringBudgets(AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"), codexExecutable: URL(fileURLWithPath: "/usr/bin/true")))
        let writerIndex = try #require(config.routes.firstIndex { $0.task == "report_localization" })
        config.routes[writerIndex] = RouteRecordV1(task: "report_localization",
            providerID: "deepseek", model: "independent-writer")
        config.topics = [
            TopicRecordV1(id: "chinese", displayName: "中文", researchFocus: "Memory",
                queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese),
            TopicRecordV1(id: "english", displayName: "English", researchFocus: "Memory",
                queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english),
        ]
        let store = AppStore(configuration: config,
            runtime: .init(selectedTopicID: "english", schedulesPaused: true, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        #expect(store.researchConfigurationErrorCode == nil)
        #expect(store.readerBudgetRoutes.contains { $0.task == "report_localization" && $0.model == "independent-writer" })
        await store.enqueueRunNow(topicID: "chinese", reportDate: "2026-11-06")
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == "reader_context_unknown")
        try store.selectTopic("chinese")
        #expect(store.researchConfigurationErrorCode == "reader_context_unknown")
        store.saveDailySchedule(topicID: "english", hour: 9, minute: 0,
            enabled: true, deliveryChannels: [])
        #expect(store.schedules.count == 1)
        let budget = ReaderContextBudgetV1(contextWindowTokens: 200_000,
            outputReserveTokens: 10_000, overheadReserveTokens: 5_000)
        try store.setReaderContextBudget(providerID: "deepseek", model: "independent-writer", budget: budget)
        #expect(store.researchConfigurationErrorCode == nil)
        let saved = try JSONCoding.decode(AppConfigurationV1.self,
            from: Data(contentsOf: root.appending(path: "config/app-config.json")))
        #expect(saved.providers.first { $0.id == "deepseek" }?.readerContexts?["independent-writer"] == budget)
        await store.enqueueRunNow(topicID: "chinese", reportDate: "2026-11-06")
        #expect(store.jobs.contains { $0.topicID == "chinese" })
        await store.shutdown()
    }

    @Test func saveUsesAtomicConfigurationAndSurvivesReload() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let budget = ReaderContextBudgetV1(contextWindowTokens: 200_000, outputReserveTokens: 10_000, overheadReserveTokens: 5_000)
        try store.setReaderContextBudget(providerID: "deepseek", model: "deepseek-flash", budget: budget)
        let data = try Data(contentsOf: root.appending(path: "config/app-config.json"))
        let saved = try JSONCoding.decode(AppConfigurationV1.self, from: data)
        #expect(saved.providers[0].readerContexts?["deepseek-flash"] == budget)
        #expect(saved.routes == config.routes)
        #expect(saved.delivery == config.delivery)
        #expect(saved.providers[1].readerContexts == nil)
    }

    @Test func failedSaveDoesNotChangeInMemoryConfiguration() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("not a directory".utf8).write(to: root.appending(path: "config"))
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let budget = ReaderContextBudgetV1(contextWindowTokens: 100_000, outputReserveTokens: 10_000, overheadReserveTokens: 5_000)
        #expect(throws: (any Error).self) {
            try store.setReaderContextBudget(providerID: "deepseek", model: "deepseek-flash", budget: budget)
        }
        #expect(store.configuration == config)
    }

    @Test(arguments: ["deep_reading", "verifier"], [false, true])
    func missingExactModelBudgetPreventsAdmission(task: String, wrongModel: Bool) async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        var config = ReaderBudgetTestConfiguration.declaringBudgets(AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"), codexExecutable: URL(fileURLWithPath: "/usr/bin/true")))
        config.topics = [TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let route = try #require(config.routes.first { $0.task == task })
        let index = try #require(config.providers.firstIndex { $0.id == route.providerID })
        let budget = config.providers[index].readerContexts?[route.model]
        config.providers[index].readerContexts = wrongModel ? ["another-model": try #require(budget)] : nil
        let store = AppStore(configuration: config, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())

        #expect(store.researchConfigurationErrorCode == "reader_context_unknown")
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-11-06")
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == "reader_context_unknown")
        store.saveDailySchedule(topicID: "memory", hour: 9, minute: 0, enabled: true, deliveryChannels: [])
        #expect(store.schedules.isEmpty)
        #expect(store.lastErrorCode == "reader_context_unknown")
        await store.shutdown()
    }

    @Test func localReaderAndVerifierDoNotRequireBudgets() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.providers = [ProviderRecordV1(id: "local", kind: "local", timeoutSeconds: 120)]
        config.routes = config.routes.map { RouteRecordV1(task: $0.task, providerID: "local", model: "local") }
        config.topics = [TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let store = AppStore(configuration: config, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())

        #expect(store.researchConfigurationErrorCode == nil)
        #expect(store.configuration.providers.allSatisfy { $0.readerContexts == nil })
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-11-06")
        #expect(store.jobs.count == 1)
        #expect(store.lastErrorCode == nil)
        await store.shutdown()
    }
}
