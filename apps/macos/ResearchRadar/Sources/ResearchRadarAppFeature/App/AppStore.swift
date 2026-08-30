import Foundation
import Observation
import ResearchRadarCore

public enum AppStoreError: Error, Equatable, Sendable {
    case invalidScheduleTime
    case legacyScheduleConflict(String)
}

@MainActor
@Observable
public final class AppStore {
    public private(set) var configuration: AppConfigurationV1
    public private(set) var jobs: [JobRecordV1]
    public private(set) var schedules: [DailyScheduleV1]
    public private(set) var reports: [ReportRecordV1]
    public private(set) var runtime: AppRuntimeStateV1
    public private(set) var lastErrorCode: String?
    public private(set) var topicDraft: TopicDraftV1?
    public private(set) var preflight: PreflightSummaryV1?
    public private(set) var isEngineRunning = false
    public private(set) var storageUsage: StorageUsageSnapshot?
    public private(set) var legacyScheduleTopics: Set<String>

    @ObservationIgnored private let persistence: AtomicJSONStore
    @ObservationIgnored private let queue: JobQueue
    @ObservationIgnored private let reportIndex: ReportIndexStore
    @ObservationIgnored private let jobsRoot: URL
    @ObservationIgnored private let coordinator: EngineJobCoordinator?
    @ObservationIgnored private let commandClient: EngineCommandClient?
    @ObservationIgnored private let secretStore: any SecretStoring
    @ObservationIgnored private let scheduleSource: ScheduleStateSource
    @ObservationIgnored private lazy var scheduleCoordinator = ScheduleCoordinator(
        queue: queue,
        timer: OneShotTimerDriver(),
        inputs: { [scheduleSource] in await scheduleSource.current() },
        onJobsEnqueued: { [weak self] in await self?.executePendingJobs() },
        onFailure: { [weak self] in await self?.recordScheduleFailure() }
    )
    @ObservationIgnored private let loginItemService: LoginItemService
    @ObservationIgnored private let storageService: StorageUsageService

    public init(
        configuration: AppConfigurationV1,
        queueSnapshot: JobQueueSnapshotV1 = JobQueueSnapshotV1(),
        scheduleSnapshot: ScheduleSnapshotV1 = ScheduleSnapshotV1(),
        reportSnapshot: ReportIndexV1 = ReportIndexV1(),
        runtime: AppRuntimeStateV1,
        appSupportRoot: URL,
        engineURL: URL? = nil,
        runner: (any EngineProcessRunning)? = nil,
        secretStore: any SecretStoring = KeychainStore(),
        loginItemService: LoginItemService = LoginItemService(),
        legacyScheduleTopics: Set<String> = []
    ) {
        self.configuration = configuration; jobs = queueSnapshot.jobs
        schedules = scheduleSnapshot.schedules; reports = reportSnapshot.reports
        self.runtime = runtime
        self.legacyScheduleTopics = legacyScheduleTopics
        self.secretStore = secretStore
        self.loginItemService = loginItemService
        storageService = StorageUsageService(appSupportRoot: appSupportRoot)
        persistence = AtomicJSONStore(root: appSupportRoot)
        jobsRoot = appSupportRoot.appending(path: "jobs", directoryHint: .isDirectory)
        let durableQueue = JobQueue(snapshot: queueSnapshot, store: persistence, jobsRoot: jobsRoot)
        let durableReports = ReportIndexStore(index: reportSnapshot, store: persistence)
        let source = ScheduleStateSource(ScheduleInputs(
            schedules: scheduleSnapshot.schedules, topics: configuration.topics,
            reports: reportSnapshot.reports, paused: runtime.schedulesPaused
        ))
        queue = durableQueue; reportIndex = durableReports
        scheduleSource = source
        if let engineURL {
            let sharedRunner = runner ?? EngineProcessSupervisor()
            coordinator = EngineJobCoordinator(
                runner: sharedRunner, engineURL: engineURL,
                appSupportRoot: appSupportRoot, queue: durableQueue, reports: durableReports
            )
            commandClient = EngineCommandClient(
                runner: sharedRunner, engineURL: engineURL, appSupportRoot: appSupportRoot
            )
        } else {
            coordinator = nil
            commandClient = nil
        }
    }

    public func approveTopic(_ draft: TopicDraftV1) throws {
        let topic = TopicRecordV1(
            id: draft.id, displayName: draft.displayName,
            researchFocus: draft.researchFocus, queries: draft.queries,
            paperQueries: draft.paperQueries, webQueries: draft.webQueries,
            exclusionTerms: draft.exclusionTerms, requiredPhrases: draft.requiredPhrases,
            conceptGroups: draft.conceptGroups, negativePhrases: draft.negativePhrases,
            prioritySources: draft.prioritySources, sourceIntent: draft.sourceIntent,
            reportLanguage: draft.reportLanguage
        )
        if let index = configuration.topics.firstIndex(where: { $0.id == topic.id }) {
            configuration.topics[index] = topic
        } else {
            configuration.topics.append(topic)
        }
        runtime.selectedTopicID = topic.id; runtime.onboardingStep = .delivery
        try persistConfigurationAndRuntime()
        topicDraft = nil
    }

    public func bootstrapTopic(description: String, language: ReportLanguageV1) async {
        guard let commandClient, !description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            lastErrorCode = "topic_description_required"; return
        }
        isEngineRunning = true; defer { isEngineRunning = false }
        do {
            topicDraft = try await commandClient.bootstrapTopic(
                description: description, language: language
            )
            runtime.onboardingStep = .topicReview; lastErrorCode = nil
        } catch {
            lastErrorCode = "topic_bootstrap_failed"
        }
    }

    public func testConnections() async {
        guard let commandClient else { lastErrorCode = "engine_missing"; return }
        isEngineRunning = true; defer { isEngineRunning = false }
        do { preflight = try await commandClient.preflight(liveProbe: true); lastErrorCode = nil }
        catch { lastErrorCode = "preflight_not_ready" }
    }

    public func saveSecret(name: String, value: String) throws {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw KeychainStoreError.invalidAccount }
        try secretStore.set(Data(trimmed.utf8), account: name)
    }

    public func secretIsPresent(name: String) -> Bool {
        (try? secretStore.contains(account: name)) == true
    }

    public func configureWeChat(
        enabled: Bool, author: String, thumbMediaID: String,
        appID: String, appSecret: String
    ) throws {
        if !appID.isEmpty { try saveSecret(name: "wechat.app_id", value: appID) }
        if !appSecret.isEmpty { try saveSecret(name: "wechat.app_secret", value: appSecret) }
        configuration.delivery.wechat.enabled = enabled
        configuration.delivery.wechat.author = author
        configuration.delivery.wechat.thumbMediaID = thumbMediaID
        try persistence.write(configuration, to: "config/app-config.json")
    }

    public func configureEmail(
        enabled: Bool, host: String, port: Int, security: EmailSecurityV1,
        username: String, password: String, from: String, to: String
    ) throws {
        if !password.isEmpty { try saveSecret(name: "email.smtp_password", value: password) }
        configuration.delivery.email.enabled = enabled
        configuration.delivery.email.smtpHost = host
        configuration.delivery.email.smtpPort = port
        configuration.delivery.email.security = security
        configuration.delivery.email.username = username
        configuration.delivery.email.fromAddress = from
        configuration.delivery.email.toAddress = to
        try persistence.write(configuration, to: "config/app-config.json")
    }

    public func setStartAtLogin(_ enabled: Bool) async {
        do {
            try await loginItemService.setEnabled(enabled)
            configuration.startAtLogin = enabled
            try persistence.write(configuration, to: "config/app-config.json")
            lastErrorCode = nil
        } catch { lastErrorCode = "login_item_failed" }
    }

    public var loginItemStatus: LoginItemStatus { loginItemService.status }

    public func refreshStorageUsage() {
        do { storageUsage = try storageService.snapshot(); lastErrorCode = nil }
        catch { lastErrorCode = "storage_scan_failed" }
    }

    public func clearModelCache() {
        do { storageUsage = try storageService.clearModelCache(); lastErrorCode = nil }
        catch { lastErrorCode = "cache_cleanup_failed" }
    }

    public func importLegacySourceHistory(from legacyRoot: URL) {
        do {
            _ = try LegacyStateMigrationService().importSourceHistory(
                from: legacyRoot,
                to: URL(fileURLWithPath: configuration.workspaceRoot)
            )
            runtime.legacyHistoryImportedAt = Date()
            try persistence.write(runtime, to: "state/app-state.json")
            lastErrorCode = nil
        } catch {
            lastErrorCode = "legacy_history_import_failed"
        }
    }

    public func setUILanguage(_ language: AppLanguagePreference) throws {
        configuration.uiLanguage = language; try persistence.write(configuration, to: "config/app-config.json")
    }

    public func useDeepSeekVerifier() throws {
        configuration = AppConfigurationDefaults.useDeepSeekVerifier(configuration)
        try persistence.write(configuration, to: "config/app-config.json")
    }

    public func selectDeepSeekVerifierFallback() async {
        do {
            try useDeepSeekVerifier()
            lastErrorCode = nil
            await testConnections()
        } catch {
            lastErrorCode = "configuration_write_failed"
        }
    }

    public func enqueueRunNow(topicID: String, reportDate: String) async {
        do {
            _ = try await queue.enqueueResearch(
                topicID: topicID,
                reportDate: reportDate,
                trigger: .runNow,
                deliveryChannels: enabledDeliveryChannels
            )
            jobs = await queue.jobs(); lastErrorCode = nil
        } catch {
            lastErrorCode = "queue_write_failed"
        }
    }

    public func runNow(topicID: String, reportDate: String) async {
        await enqueueRunNow(topicID: topicID, reportDate: reportDate)
        await executePendingJobs()
    }

    public func runSelectedTopicNow() async {
        guard let topicID = runtime.selectedTopicID ?? configuration.topics.first?.id else { return }
        let formatter = DateFormatter(); formatter.calendar = .current; formatter.dateFormat = "yyyy-MM-dd"
        await runNow(topicID: topicID, reportDate: formatter.string(from: Date()))
    }

    public func startScheduling() async {
        await refreshScheduleInputs()
        do {
            try await scheduleCoordinator.refresh()
        } catch {
            lastErrorCode = "schedule_refresh_failed"
        }
        jobs = await queue.jobs()
    }

    public func reconcileAfterLaunch() async {
        do {
            guard let coordinator else {
                lastErrorCode = "engine_missing"
                return
            }
            try await coordinator.reconcileAfterLaunch()
            jobs = await queue.jobs()
            reports = await reportIndex.reports()
            lastErrorCode = nil
            await executePendingJobs()
        } catch { lastErrorCode = "state_reconciliation_failed" }
    }

    public func stopScheduling() async {
        await scheduleCoordinator.stop()
    }

    public func retryDelivery(
        report: ReportRecordV1,
        channel: DeliveryChannel,
        allowResend: Bool,
        acknowledgeUnknownOutcome: Bool
    ) async {
        do {
            _ = try await queue.enqueueDelivery(
                runDirectory: URL(fileURLWithPath: report.runDirectory),
                topicID: report.topicID, reportDate: report.reportDate,
                channel: channel, trigger: .retry, allowResend: allowResend,
                acknowledgeUnknownOutcome: acknowledgeUnknownOutcome
            )
            await executePendingJobs()
        } catch {
            lastErrorCode = "delivery_retry_blocked"
        }
    }

    public func cancelActiveJob() async {
        await commandClient?.cancel(); await coordinator?.cancel()
    }

    public func setSchedulesPaused(_ paused: Bool) throws {
        runtime.schedulesPaused = paused; runtime.updatedAt = Date()
        try persistence.write(runtime, to: "state/app-state.json")
        Task { await startScheduling() }
    }

    public func setDailySchedule(
        topicID: String, hour: Int, minute: Int, enabled: Bool,
        deliveryChannels: [DeliveryChannel]
    ) throws {
        if enabled, legacyScheduleTopics.contains(topicID) {
            throw AppStoreError.legacyScheduleConflict(topicID)
        }
        guard (0...23).contains(hour), (0...59).contains(minute) else {
            throw AppStoreError.invalidScheduleTime
        }
        let normalizedChannels = Array(Set(deliveryChannels)).sorted {
            $0.rawValue < $1.rawValue
        }
        if let index = schedules.firstIndex(where: { $0.topicID == topicID }) {
            schedules[index].hour = hour; schedules[index].minute = minute
            schedules[index].isEnabled = enabled
            schedules[index].deliveryChannels = normalizedChannels
        } else {
            schedules.append(DailyScheduleV1(
                topicID: topicID, hour: hour, minute: minute,
                isEnabled: enabled, deliveryChannels: normalizedChannels
            ))
        }
        try persistence.write(ScheduleSnapshotV1(schedules: schedules), to: "state/schedules.json")
        Task { await startScheduling() }
    }

    public func saveDailySchedule(
        topicID: String, hour: Int, minute: Int, enabled: Bool,
        deliveryChannels: [DeliveryChannel]
    ) {
        do {
            try setDailySchedule(
                topicID: topicID,
                hour: hour,
                minute: minute,
                enabled: enabled,
                deliveryChannels: deliveryChannels
            )
            lastErrorCode = nil
        } catch AppStoreError.legacyScheduleConflict {
            lastErrorCode = "legacy_schedule_conflict"
        } catch {
            lastErrorCode = "schedule_write_failed"
        }
    }

    private func persistConfigurationAndRuntime() throws {
        runtime.updatedAt = Date()
        try persistence.write(configuration, to: "config/app-config.json")
        try persistence.write(runtime, to: "state/app-state.json")
    }

    private func executePendingJobs() async {
        guard let coordinator else { lastErrorCode = "engine_missing"; return }
        isEngineRunning = true; defer { isEngineRunning = false }
        var encounteredFailure = false
        var consecutiveFailures = 0
        while true {
            do {
                guard try await coordinator.executeNext(configuration: configuration) != nil else {
                    break
                }
                consecutiveFailures = 0
            } catch {
                encounteredFailure = true
                consecutiveFailures += 1
                if consecutiveFailures >= 3 { break }
                continue
            }
        }
        jobs = await queue.jobs()
        reports = await reportIndex.reports()
        lastErrorCode = encounteredFailure ? "engine_failed" : nil
        await refreshScheduleInputs()
    }


    private func refreshScheduleInputs() async {
        await scheduleSource.update(ScheduleInputs(
            schedules: schedules, topics: configuration.topics,
            reports: reports, paused: runtime.schedulesPaused
        ))
    }

    private func recordScheduleFailure() {
        lastErrorCode = "schedule_refresh_failed"
    }

    private var enabledDeliveryChannels: [DeliveryChannel] {
        var channels: [DeliveryChannel] = []
        if configuration.delivery.wechat.enabled { channels.append(.wechat) }
        if configuration.delivery.email.enabled { channels.append(.email) }
        return channels
    }
}
