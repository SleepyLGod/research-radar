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
    @Test(arguments: ["delivery_failed", "cancelled"])
    func terminalDeliveryFailureDoesNotBlockIndependentEmail(code: String) async throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [testTopic()]
        let run = root.appending(path: "workspace/run")
        let report = ReportRecordV1(topicID: "memory", reportDate: "2026-09-19", runDirectory: run.path,
            articleDraftPath: run.appending(path: "article.json").path, reportHTMLPath: run.appending(path: "report.html").path,
            title: "Report", summary: "", sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1,
            deliveries: [.init(channel: .wechat, state: .pending), .init(channel: .email, state: .pending)], createdAt: Date())
        let jobs = try [DeliveryChannel.wechat, .email].map { channel in
            let id = UUID()
            return try JobRecordV1(id: id, kind: .delivery, topicID: "memory", reportDate: "2026-09-19",
                deliveryChannel: channel, trigger: .retry, jobDirectory: root.appending(path: "jobs/\(id.uuidString.lowercased())").path,
                runDirectory: run.path, createdAt: Date())
        }
        let runner = IndependentDeliveryRunner(firstErrorCode: code)
        let store = AppStore(configuration: config, queueSnapshot: JobQueueSnapshotV1(jobs: jobs),
            reportSnapshot: ReportIndexV1(reports: [report]), runtime: AppRuntimeStateV1(updatedAt: Date()),
            appSupportRoot: root, engineURL: URL(fileURLWithPath: "/fake/engine"), runner: runner)
        await store.runNow(topicID: "memory", reportDate: "2026-09-19")
        #expect(await runner.channels == [.wechat, .email])
        #expect(store.jobs[0].state == .deliveryUnknown)
        #expect(store.jobs[1].state == .succeeded)
        #expect(store.lastErrorCode == code)
        #expect(store.reports[0].deliveries.first(where: { $0.channel == .email })?.state == .sent)
    }

    @Test func keychainFailureIsNotReportedAsMissing() throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root, secretStore: DeniedSecrets())
        store.refreshSecretPresence()
        #expect(store.secretPresence["deepseek.api_key"] == nil)
        #expect(store.lastErrorCode == "keychain_lookup_failed")
    }

    @Test func commandKeepsQueuedJobPendingAndShutdownCancelsOnlyOnce() async throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [testTopic()]
        let runner = SuspendedAppRunner()
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root, engineURL: URL(fileURLWithPath: "/fake/engine"), runner: runner)
        let command = Task { await store.testConnections() }
        await runner.waitForStart()
        await store.runNow(topicID: "memory", reportDate: "2026-09-19")
        #expect(store.jobs.first?.state == .pending)
        #expect(await runner.starts == 1)
        await store.cancelActiveJob()
        await store.cancelActiveJob()
        await store.shutdown()
        #expect(await runner.cancellations == 1)
        await runner.finish()
        await command.value
        #expect(await runner.starts == 1)
        #expect(store.jobs.first?.state == .pending)
    }

    @Test func failedConfigurationAndRuntimeWritesLeaveMemoryUntouched() throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let runtime = AppRuntimeStateV1(updatedAt: Date())
        let store = AppStore(configuration: config, runtime: runtime, appSupportRoot: root)
        try Data("blocked".utf8).write(to: root.appending(path: "config"))
        #expect(throws: (any Error).self) { try store.setUILanguage(.english) }
        #expect(store.configuration == config)
        try Data("blocked".utf8).write(to: root.appending(path: "state"))
        #expect(throws: (any Error).self) { try store.setSchedulesPaused(true) }
        #expect(store.runtime == runtime)
    }

    @Test func approvalDoesNotRequireRuntimeFileWrite() throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        let config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root)
        try Data("blocked".utf8).write(to: root.appending(path: "state"))
        try store.approveTopic(TopicDraftV1(id: "one", displayName: "One", researchFocus: "Focus", queries: ["one"], paperQueries: ["paper"], reportLanguage: .english))
        #expect(store.selectedTopic?.id == "one")
        #expect(try AtomicJSONStore(root: root).read(AppConfigurationV1.self, from: "config/app-config.json").topics.count == 1)
    }

    @Test func failedScheduleWriteLeavesPreviousScheduleInMemory() throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [testTopic()]
        let original = DailyScheduleV1(topicID: "memory", hour: 9, minute: 0)
        let store = AppStore(configuration: config, scheduleSnapshot: ScheduleSnapshotV1(schedules: [original]), runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root)
        try Data("blocked".utf8).write(to: root.appending(path: "state"))
        #expect(throws: (any Error).self) { try store.setDailySchedule(topicID: "memory", hour: 11, minute: 0, enabled: false, deliveryChannels: []) }
        #expect(store.schedules == [original])
    }

    @Test func pendingJobsBlockBehaviorButAllowUILanguage() async throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [testTopic()]
        let store = AppStore(configuration: config, runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root)
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-09-19")
        #expect(store.behaviorChangesBlocked)
        #expect(throws: AppStoreError.busy) { try store.saveSecret(name: "test", value: "fake") }
        #expect(throws: AppStoreError.busy) { try store.setCacheLimit(100) }
        #expect(throws: AppStoreError.busy) { try store.saveTopic(testTopic()) }
        try store.setUILanguage(.english)
        #expect(store.configuration.uiLanguage == .english)
        await store.shutdown()
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-09-20")
        #expect(store.jobs.count == 1)
    }

    @Test func runNowSelectsExistingReportAndRunAgainRequiresConfirmation() async throws {
        let root = try appStoreRoot(); defer { try? trashAppStoreRoot(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [testTopic()]
        let report = ReportRecordV1(topicID: "memory", reportDate: "2026-09-19", runDirectory: "/fake/run", articleDraftPath: "/fake/run/a", reportHTMLPath: "/fake/run/h", title: "Report", summary: "", sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1, deliveries: [], createdAt: Date())
        let store = AppStore(configuration: config, reportSnapshot: ReportIndexV1(reports: [report]), runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root)
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-09-19")
        #expect(store.selectedReportID == report.id)
        #expect(store.jobs.isEmpty)
        await store.runAgain(topicID: "memory", reportDate: "2026-09-19", confirmed: false)
        #expect(store.jobs.isEmpty)
        await store.runAgain(topicID: "memory", reportDate: "2026-09-19", confirmed: true)
        #expect(store.jobs.count == 1)
    }

    @Test func editorValidationPreservesIDAndUneditedTopicFields() throws {
        var topic = testTopic()
        topic.webQueries = ["web"]
        topic.requiredPhrases = ["required"]
        topic.conceptGroups = ["Original Key": ["original phrase"]]
        topic.negativePhrases = ["original exclusion"]
        var input = TopicEditorInput(topic: topic)
        #expect(try input.candidate() == topic)
        let groupID = input.conceptGroups[0].id
        input.queries = " first \n\nsecond "
        input.conceptGroups[0].phrases = "agent\nrecall"
        input.conceptGroups.append(ConceptGroupInput(name: "New group", phrases: ["new phrase"]))
        input.negativePhrases = " not relevant \n\n excluded phrase "
        let candidate = try input.candidate()
        #expect(candidate.id == topic.id)
        #expect(candidate.queries == ["first", "second"])
        #expect(candidate.webQueries == ["web"])
        #expect(candidate.requiredPhrases == ["required"])
        #expect(candidate.conceptGroups == ["Original Key": ["agent", "recall"], "New group": ["new phrase"]])
        #expect(candidate.negativePhrases == ["not relevant", "excluded phrase"])
        #expect(input.conceptGroups[0].id == groupID)
        input.conceptGroups[0].name = "Renamed group"
        #expect(try input.candidate().conceptGroups["Renamed group"] == ["agent", "recall"])
        input.conceptGroups[1].name = "Renamed group"
        #expect(throws: (any Error).self) { try input.candidate() }
        #expect(input.conceptGroups[1].name == "Renamed group")
        input.conceptGroups[1].name = " "
        #expect(throws: AppStoreError.invalidTopic) { try input.candidate() }
        input.conceptGroups[1].name = "New group"
        input.conceptGroups[1].phrases = "\n "
        #expect(throws: AppStoreError.invalidTopic) { try input.candidate() }
        #expect(try CacheLimitInput.parse(enabled: false, bytes: "") == nil)
        #expect(throws: (any Error).self) { try CacheLimitInput.parse(enabled: true, bytes: "0") }
        #expect(throws: (any Error).self) { try CacheLimitInput.parse(enabled: true, bytes: "-1") }
        #expect(try CacheLimitInput.parse(enabled: true, bytes: "1024") == 1024)
        #expect(TopicEditorInput.reportLanguage(for: .english) == .english)
        #expect(TopicEditorInput.reportLanguage(for: .simplifiedChinese) == .chinese)
    }

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

private struct DeniedSecrets: SecretStoring {
    func set(_ value: Data, account: String) throws { throw KeychainStoreError.invalidAccount }
    func read(account: String) throws -> Data? { throw KeychainStoreError.invalidAccount }
    func contains(account: String) throws -> Bool { throw KeychainStoreError.invalidAccount }
    func remove(account: String) throws { throw KeychainStoreError.invalidAccount }
}

private actor IndependentDeliveryRunner: EngineProcessRunning {
    let firstErrorCode: String
    private(set) var channels: [DeliveryChannel] = []
    init(firstErrorCode: String) { self.firstErrorCode = firstErrorCode }
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let requestIndex = try #require(arguments.firstIndex(of: "--request"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: URL(fileURLWithPath: arguments[requestIndex + 1])))
        guard case .retryDelivery(let payload) = request.payload else { throw AppStoreError.invalidTopic }
        channels.append(payload.channel)
        if payload.channel == .wechat {
            let errorIndex = try #require(arguments.firstIndex(of: "--error"))
            let data = try JSONSerialization.data(withJSONObject: [
                "schema_version": 1, "request_id": request.requestID.uuidString.lowercased(), "status": "failed",
                "stage": EngineStage.wechatDraft.rawValue, "code": firstErrorCode, "message": "Fake terminal failure", "retryable": false,
                "completed_at": "2026-09-19T00:00:00Z",
            ])
            try data.write(to: URL(fileURLWithPath: arguments[errorIndex + 1]))
        } else {
            let resultIndex = try #require(arguments.firstIndex(of: "--result"))
            let result = EngineResultV1(requestID: request.requestID, command: .retryDelivery, status: .succeeded,
                completedAt: Date(), delivery: DeliveryResultV1(runDirectory: payload.runDirectory, channel: .email,
                    status: .sent, completedAt: Date()))
            try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[resultIndex + 1]))
        }
        return EngineProcessOutcome(exitCode: payload.channel == .wechat ? 1 : 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
}

private actor SuspendedAppRunner: EngineProcessRunning {
    private(set) var starts = 0
    private(set) var cancellations = 0
    private var completion: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        starts += 1
        await withCheckedContinuation { continuation in
            completion = continuation
            started?.resume(); started = nil
        }
        throw CancellationError()
    }
    func waitForStart() async {
        if completion != nil { return }
        await withCheckedContinuation { started = $0 }
    }
    func finish() { completion?.resume(); completion = nil }
    func cancel() async { cancellations += 1 }
}

private func testTopic() -> TopicRecordV1 {
    TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Memory", queries: ["memory"], paperQueries: ["memory papers"], reportLanguage: .english)
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
