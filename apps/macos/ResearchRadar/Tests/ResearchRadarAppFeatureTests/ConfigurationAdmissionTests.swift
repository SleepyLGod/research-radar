import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

struct AdmissionSecrets: SecretStoring {
    var present = true
    var denied = false
    func contains(account: String) throws -> Bool {
        if denied { throw KeychainStoreError.invalidAccount }
        return present
    }
    func read(account: String) throws -> Data? {
        Issue.record("Configuration validation must not read secret values")
        return nil
    }
    func set(_ value: Data, account: String) throws {}
    func remove(account: String) throws {}
}

@MainActor @Suite struct ConfigurationAdmissionTests {
    @Test(arguments: ["credentials", "codex", "verifier"], [false, true])
    func configurationRecoveryRearmsOnlyUnpausedSchedules(recovery: String, paused: Bool) async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let base = makeStore(root: root, codex: recovery == "credentials")
        let secrets: any SecretStoring = recovery == "credentials" ? RecoveringSecrets() : AdmissionSecrets()
        let store = AppStore(configuration: base.configuration,
            scheduleSnapshot: .init(schedules: [DailyScheduleV1(topicID: "memory", hour: 0, minute: 0)]),
            runtime: .init(schedulesPaused: paused, updatedAt: Date()), appSupportRoot: root, secretStore: secrets)
        await store.startScheduling()
        #expect(store.jobs.isEmpty)
        switch recovery {
        case "credentials": try store.saveSecret(name: "deepseek.api_key", value: "fixture-only")
        case "codex": try store.setCodexExecutable("/usr/bin/true")
        default: try store.useDeepSeekVerifier()
        }
        #expect(store.researchConfigurationErrorCode == nil)
        // No engine is installed: only durable schedule admission can happen.
        for _ in 0..<100 {
            if !store.jobs.isEmpty { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(store.jobs.count == (paused ? 0 : 1))
        if !paused { #expect(store.jobs.first?.trigger == .schedule) }
        await store.shutdown()
    }

    @Test func explicitConnectionCheckCanRecoverUnknownMetadata() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let base = makeStore(root: root, codex: true)
        let secrets = RecoveringSecrets()
        let store = AppStore(configuration: base.configuration, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, engineURL: URL(fileURLWithPath: "/fake/engine"),
            runner: AuthorizationCheckRunner(secrets: secrets), secretStore: secrets)
        #expect(store.researchConfigurationErrorCode == "keychain_lookup_failed")
        await store.testConnections()
        #expect(store.preflight?.ready == true)
        #expect(store.researchConfigurationErrorCode == nil)
        #expect(store.lastErrorCode == nil)
    }

    @Test func successfulReplacementRefreshesPreviouslyUnavailablePresence() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let base = makeStore(root: root, codex: true)
        let store = AppStore(configuration: base.configuration, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: RecoveringSecrets())
        #expect(store.researchConfigurationErrorCode == "keychain_lookup_failed")
        try store.saveSecret(name: "deepseek.api_key", value: "fixture-only")
        #expect(store.researchConfigurationErrorCode == nil)
    }

    @Test func failedCredentialSaveRetainsBothDraftsAndDoesNotClaimVerification() {
        var draft = ProviderCredentialDraft()
        draft.deepSeekKey = "replacement"
        draft.searchKey = "search replacement"
        var saves = 0
        #expect(throws: KeychainStoreError.invalidAccount) {
            try draft.save { _, _ in
                saves += 1
                if saves == 2 { throw KeychainStoreError.invalidAccount }
            }
        }
        #expect(draft.deepSeekKey == "replacement")
        #expect(draft.searchKey == "search replacement")
        #expect(throws: Never.self) { try draft.save { _, _ in } }
        #expect(draft.deepSeekKey.isEmpty && draft.searchKey.isEmpty)
    }

    @Test func validCustomCodexIsNeverReplacedByDetection() {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let store = makeStore(root: root, codex: true)
        #expect(store.researchConfigurationErrorCode == nil)
        #expect(store.detectedCodexExecutable(environmentPath: "/missing", homeDirectory: root) == nil)
        #expect(store.configuration.providers.first { $0.id == "codex" }?.commandPath == "/usr/bin/true")
    }

    @Test(arguments: ["codex_not_configured", "/private/untrusted-error", "research_failed"])
    func todayExposesOnlyStableFailureCodes(code: String) throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let topic = TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)
        let job = try JobRecordV1(kind: .research, topicID: "memory", reportDate: "2026-09-20",
            trigger: .runNow, state: .failed, jobDirectory: root.path, createdAt: Date(),
            error: RedactedEngineErrorV1(code: code, message: "Never display this payload", retryable: false))
        let today = TodayPresentation(topic: topic, jobs: [job], reports: [], schedules: [],
            schedulesPaused: false, now: Date(), calendar: .current)
        #expect(today.failureCode == (code.hasPrefix("/") ? "engine_failed" : code))
        #expect(today.latestResearchJob?.error == nil)
    }

    @Test func invalidPendingResearchReleasesConfigurationEditingWithoutLaunching() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let base = makeStore(root: root, codex: false)
        let job = try JobRecordV1(kind: .research, topicID: "memory", reportDate: "2026-09-20",
            trigger: .schedule, jobDirectory: root.appending(path: "jobs/pending").path, createdAt: Date())
        let store = AppStore(configuration: base.configuration, queueSnapshot: .init(jobs: [job]),
            runtime: .init(updatedAt: Date()), appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/must-not-launch"), runner: ForbiddenResearchRunner(),
            secretStore: AdmissionSecrets())
        await store.runNow(topicID: "memory", reportDate: "2026-09-20")
        #expect(store.jobs.first?.state == .cancelled)
        #expect(store.jobs.first?.error?.code == "codex_not_configured")
        #expect(!store.behaviorChangesBlocked)
        await store.shutdown()
    }

    @Test(arguments: ["codex_not_configured", "credentials_missing", "keychain_lookup_failed"])
    func invalidConfigurationNeverQueuesResearch(code: String) async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let store = makeStore(root: root, codex: code != "codex_not_configured",
            secrets: AdmissionSecrets(present: code != "credentials_missing", denied: code == "keychain_lookup_failed"))
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-09-20")
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == code)
    }

    @Test func scheduleCannotBeEnabledWithMissingCodex() {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let store = makeStore(root: root, codex: false)
        store.saveDailySchedule(topicID: "memory", hour: 9, minute: 0, enabled: true, deliveryChannels: [])
        #expect(store.schedules.isEmpty)
        #expect(store.lastErrorCode == "codex_not_configured")
    }

    @Test func restoredScheduleDoesNotQueueResearchWithMissingCodex() async {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        let store = makeStore(root: root, codex: false,
            schedules: [DailyScheduleV1(topicID: "memory", hour: 0, minute: 0)])
        await store.startScheduling()
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == "codex_not_configured")
        await store.shutdown()
    }

    @Test func validConfigurationQueuesWithoutReadingSecretValues() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { trash(root) }
        let store = makeStore(root: root, codex: true)
        await store.enqueueRunNow(topicID: "memory", reportDate: "2026-09-20")
        #expect(store.jobs.count == 1)
        #expect(store.lastErrorCode == nil)
        await store.shutdown()
    }

    private func makeStore(root: URL, codex: Bool, secrets: AdmissionSecrets = AdmissionSecrets(),
                           schedules: [DailyScheduleV1] = []) -> AppStore {
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: codex ? URL(fileURLWithPath: "/usr/bin/true") : nil)
        config.topics = [TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        return AppStore(configuration: config, scheduleSnapshot: ScheduleSnapshotV1(schedules: schedules),
            runtime: AppRuntimeStateV1(updatedAt: Date()), appSupportRoot: root, secretStore: secrets)
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

private actor ForbiddenResearchRunner: EngineProcessRunning {
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        Issue.record("Invalid configuration launched research")
        throw CocoaError(.featureUnsupported)
    }
    func cancel() async {}
}

private final class RecoveringSecrets: SecretStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var available = false
    func contains(account: String) throws -> Bool {
        try lock.withLock {
            guard available else { throw KeychainStoreError.invalidAccount }
            return true
        }
    }
    func set(_ value: Data, account: String) throws { lock.withLock { available = true } }
    func read(account: String) throws -> Data? {
        Issue.record("Presence recovery must not read secret values")
        return nil
    }
    func remove(account: String) throws {}
}

private actor AuthorizationCheckRunner: EngineProcessRunning {
    let secrets: RecoveringSecrets
    init(secrets: RecoveringSecrets) { self.secrets = secrets }
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let requestIndex = try #require(arguments.firstIndex(of: "--request"))
        let resultIndex = try #require(arguments.firstIndex(of: "--result"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: URL(fileURLWithPath: arguments[requestIndex + 1])))
        #expect(request.command == .preflight)
        try secrets.set(Data("fixture-authorization".utf8), account: "deepseek.api_key")
        let summary = try JSONDecoder().decode(PreflightSummaryV1.self,
            from: Data(#"{"checks":[],"ready":true}"#.utf8))
        let result = EngineResultV1(requestID: request.requestID, command: .preflight, status: .succeeded,
            completedAt: Date(), preflight: summary)
        try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[resultIndex + 1]))
        return EngineProcessOutcome(exitCode: 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
}
