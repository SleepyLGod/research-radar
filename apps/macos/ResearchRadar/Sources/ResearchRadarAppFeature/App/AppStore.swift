import Foundation
import Observation
import ResearchRadarCore

public enum AppStoreError: Error, Equatable, Sendable {
    case invalidScheduleTime
    case legacyScheduleConflict(String)
    case busy
    case invalidTopic
    case invalidExecutable
    case confirmationRequired
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
    public private(set) var topicDraftRevision = 0
    public private(set) var secretPresence: [String: Bool] = [:]
    public private(set) var preflight: PreflightSummaryV1?
    public private(set) var isEngineRunning = false
    public private(set) var storageUsage: StorageUsageSnapshot?
    public private(set) var legacyScheduleTopics: Set<String>
    public private(set) var selectedReportID: UUID?
    public private(set) var isShuttingDown = false
    public private(set) var cancellationRequested = false
    @ObservationIgnored private var commandActive = false
    @ObservationIgnored private var drainTask: Task<Void, Never>?
    @ObservationIgnored private var admissionCount = 0
    @ObservationIgnored private var drainRequested = false
    @ObservationIgnored private let executionGate = EngineExecutionGate()
    public private(set) var requiresReconciliation = false

    public var behaviorChangesBlocked: Bool {
        isShuttingDown || requiresReconciliation || isEngineRunning || admissionCount > 0 || drainTask != nil || jobs.contains {
            [.pending, .running, .cancelling].contains($0.state)
        }
    }

    public var selectedTopic: TopicRecordV1? {
        configuration.topics.first { $0.id == runtime.selectedTopicID } ?? configuration.topics.first
    }

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
        onFailure: { [weak self] in await self?.recordScheduleFailure() },
        onAdmissionChange: { [weak self] active in await self?.scheduleAdmissionChanged(active) }
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
        pdfHelperURL: URL? = nil,
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
                appSupportRoot: appSupportRoot, queue: durableQueue, reports: durableReports,
                pdfHelperURL: pdfHelperURL,
                gate: executionGate
            )
            commandClient = EngineCommandClient(
                runner: sharedRunner, engineURL: engineURL, appSupportRoot: appSupportRoot,
                gate: executionGate
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
        guard !configuration.topics.contains(where: { $0.id == topic.id }) else {
            throw AppStoreError.invalidTopic
        }
        try saveTopic(topic, creating: true)
        topicDraft = nil
    }

    public func bootstrapTopic(description: String, language: ReportLanguageV1) async {
        guard !behaviorChangesBlocked else { lastErrorCode = "engine_busy"; return }
        guard let commandClient, !description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            lastErrorCode = "topic_description_required"; return
        }
        commandActive = true; isEngineRunning = true; cancellationRequested = false
        defer { finishCommand() }
        do {
            topicDraft = try await commandClient.bootstrapTopic(
                description: description, language: language
            )
            topicDraftRevision += 1
            lastErrorCode = nil
        } catch {
            lastErrorCode = "topic_bootstrap_failed"
        }
    }

    public func testConnections() async {
        guard !behaviorChangesBlocked else { lastErrorCode = "engine_busy"; return }
        guard let commandClient else { lastErrorCode = "engine_missing"; return }
        commandActive = true; isEngineRunning = true; cancellationRequested = false
        preflight = nil
        defer { finishCommand() }
        do { preflight = try await commandClient.preflight(liveProbe: true); lastErrorCode = nil }
        catch { lastErrorCode = "preflight_not_ready" }
    }

    public func saveSecret(name: String, value: String) throws {
        try requireBehaviorChange()
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw KeychainStoreError.invalidAccount }
        try secretStore.set(Data(trimmed.utf8), account: name)
        secretPresence[name] = true
        preflight = nil
    }

    public func refreshSecretPresence() {
        for name in ["deepseek.api_key", "web_search.api_key"] {
            do { secretPresence[name] = try secretStore.contains(account: name) }
            catch {
                secretPresence[name] = nil
                lastErrorCode = "keychain_lookup_failed"
            }
        }
    }

    public func configureWeChat(
        enabled: Bool, author: String, thumbMediaID: String,
        appID: String, appSecret: String
    ) throws {
        try requireBehaviorChange()
        var candidate = configuration
        candidate.delivery.wechat.enabled = enabled
        candidate.delivery.wechat.author = author
        candidate.delivery.wechat.thumbMediaID = thumbMediaID
        try candidate.validate()
        if !appID.isEmpty { try saveSecret(name: "wechat.app_id", value: appID) }
        if !appSecret.isEmpty { try saveSecret(name: "wechat.app_secret", value: appSecret) }
        try persistConfiguration(candidate)
    }

    public func configureEmail(
        enabled: Bool, host: String, port: Int, security: EmailSecurityV1,
        username: String, password: String, from: String, to: String
    ) throws {
        try requireBehaviorChange()
        var candidate = configuration
        candidate.delivery.email.enabled = enabled
        candidate.delivery.email.smtpHost = host
        candidate.delivery.email.smtpPort = port
        candidate.delivery.email.security = security
        candidate.delivery.email.username = username
        candidate.delivery.email.fromAddress = from
        candidate.delivery.email.toAddress = to
        try candidate.validate()
        if !password.isEmpty { try saveSecret(name: "email.smtp_password", value: password) }
        try persistConfiguration(candidate)
    }

    public func setStartAtLogin(_ enabled: Bool) async {
        do {
            try requireBehaviorChange()
            var candidate = configuration
            candidate.startAtLogin = enabled
            try candidate.validate()
            admissionCount += 1
            defer { admissionCount -= 1 }
            try await loginItemService.setEnabled(enabled)
            candidate.uiLanguage = configuration.uiLanguage
            try persistConfiguration(candidate)
            lastErrorCode = nil
        } catch { lastErrorCode = "login_item_failed" }
    }

    public var loginItemStatus: LoginItemStatus { loginItemService.status }

    public func refreshStorageUsage() {
        do { storageUsage = try storageService.snapshot(); lastErrorCode = nil }
        catch { lastErrorCode = "storage_scan_failed" }
    }

    public func clearModelCache() {
        do { try requireBehaviorChange(); storageUsage = try storageService.clearModelCache(); lastErrorCode = nil }
        catch { lastErrorCode = "cache_cleanup_failed" }
    }

    public func importLegacySourceHistory(from legacyRoot: URL) {
        do {
            try requireBehaviorChange()
            _ = try LegacyStateMigrationService().importSourceHistory(
                from: legacyRoot,
                to: URL(fileURLWithPath: configuration.workspaceRoot)
            )
            var candidate = runtime
            candidate.legacyHistoryImportedAt = Date()
            try persistRuntime(candidate)
            lastErrorCode = nil
        } catch {
            lastErrorCode = "legacy_history_import_failed"
        }
    }

    public func setUILanguage(_ language: AppLanguagePreference) throws {
        var candidate = configuration
        candidate.uiLanguage = language
        try persistConfiguration(candidate, invalidatePreflight: false)
    }

    public func useDeepSeekVerifier() throws {
        try requireBehaviorChange()
        try persistConfiguration(AppConfigurationDefaults.useDeepSeekVerifier(configuration))
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

    public func enqueueRunNow(topicID: String, reportDate: String, forceNewAttempt: Bool = false) async {
        guard !isShuttingDown, !requiresReconciliation else { lastErrorCode = "app_stopping"; return }
        guard configuration.topics.contains(where: { $0.id == topicID && !$0.isPaused }) else {
            lastErrorCode = "topic_invalid"; return
        }
        if !forceNewAttempt, let report = reports.last(where: { $0.topicID == topicID && $0.reportDate == reportDate }) {
            selectedReportID = report.id
            lastErrorCode = nil
            return
        }
        admissionCount += 1
        defer { admissionCount -= 1 }
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
        if jobs.contains(where: { $0.state == .pending }) { await executePendingJobs() }
    }

    public func runAgain(topicID: String, reportDate: String, confirmed: Bool) async {
        guard confirmed else { lastErrorCode = "confirmation_required"; return }
        await enqueueRunNow(topicID: topicID, reportDate: reportDate, forceNewAttempt: true)
        await executePendingJobs()
    }

    public func runSelectedTopicNow() async {
        guard let topicID = runtime.selectedTopicID ?? configuration.topics.first?.id else { return }
        let formatter = DateFormatter(); formatter.calendar = .current; formatter.dateFormat = "yyyy-MM-dd"
        await runNow(topicID: topicID, reportDate: formatter.string(from: Date()))
    }

    public func startScheduling() async {
        guard !isShuttingDown, !requiresReconciliation else { return }
        admissionCount += 1
        defer { admissionCount -= 1 }
        await refreshScheduleInputs()
        do {
            try await scheduleCoordinator.refresh()
        } catch {
            await stopScheduling()
            lastErrorCode = "schedule_refresh_failed"
        }
        jobs = await queue.jobs()
    }

    public func reconcileAfterLaunch() async {
        guard !isShuttingDown, !isEngineRunning else { return }
        commandActive = true; isEngineRunning = true
        do {
            guard let coordinator else {
                lastErrorCode = "engine_missing"
                commandActive = false; isEngineRunning = false
                return
            }
            try await coordinator.reconcileAfterLaunch()
            jobs = await queue.jobs()
            reports = await reportIndex.reports()
            lastErrorCode = nil
            requiresReconciliation = false
            commandActive = false; isEngineRunning = false
            await executePendingJobs()
        } catch {
            requiresReconciliation = true
            commandActive = false; isEngineRunning = false
            lastErrorCode = "state_reconciliation_failed"
        }
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
        guard !isShuttingDown else { lastErrorCode = "app_stopping"; return }
        admissionCount += 1
        defer { admissionCount -= 1 }
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
        guard isEngineRunning, !cancellationRequested else { return }
        cancellationRequested = true
        if commandActive { await commandClient?.cancel() }
        else { await coordinator?.cancel() }
    }

    public func shutdown() async {
        isShuttingDown = true
        executionGate.stopAdmission()
        await stopScheduling()
        await cancelActiveJob()
        await drainTask?.value
    }

    public func setSchedulesPaused(_ paused: Bool) throws {
        try requireBehaviorChange()
        var candidate = runtime
        candidate.schedulesPaused = paused
        try persistRuntime(candidate)
        Task { await startScheduling() }
    }

    public func setDailySchedule(
        topicID: String, hour: Int, minute: Int, enabled: Bool,
        deliveryChannels: [DeliveryChannel]
    ) throws {
        try requireBehaviorChange()
        guard configuration.topics.contains(where: { $0.id == topicID }) else { throw AppStoreError.invalidTopic }
        if enabled, legacyScheduleTopics.contains(topicID) {
            throw AppStoreError.legacyScheduleConflict(topicID)
        }
        guard (0...23).contains(hour), (0...59).contains(minute) else {
            throw AppStoreError.invalidScheduleTime
        }
        let normalizedChannels = Array(Set(deliveryChannels)).sorted {
            $0.rawValue < $1.rawValue
        }
        var candidate = schedules
        if let index = candidate.firstIndex(where: { $0.topicID == topicID }) {
            candidate[index].hour = hour; candidate[index].minute = minute
            candidate[index].isEnabled = enabled
            candidate[index].deliveryChannels = normalizedChannels
        } else {
            candidate.append(DailyScheduleV1(
                topicID: topicID, hour: hour, minute: minute,
                isEnabled: enabled, deliveryChannels: normalizedChannels
            ))
        }
        let snapshot = ScheduleSnapshotV1(schedules: candidate)
        try snapshot.validate()
        try persistence.write(snapshot, to: "state/schedules.json")
        schedules = candidate
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

    private func persistConfiguration(_ candidate: AppConfigurationV1, invalidatePreflight: Bool = true) throws {
        try candidate.validate()
        try persistence.write(candidate, to: "config/app-config.json")
        configuration = candidate
        if invalidatePreflight { preflight = nil }
    }

    private func persistRuntime(_ value: AppRuntimeStateV1) throws {
        var candidate = value
        candidate.updatedAt = Date()
        try persistence.write(candidate, to: "state/app-state.json")
        runtime = candidate
    }

    private func requireBehaviorChange() throws {
        guard !behaviorChangesBlocked else { throw AppStoreError.busy }
    }

    @discardableResult
    public func performAction(_ action: () throws -> Void) -> Bool {
        do { try action(); lastErrorCode = nil; return true }
        catch AppStoreError.busy { lastErrorCode = "engine_busy" }
        catch AppStoreError.invalidExecutable { lastErrorCode = "codex_path_invalid" }
        catch AppStoreError.invalidTopic { lastErrorCode = "topic_invalid" }
        catch { lastErrorCode = "configuration_write_failed" }
        return false
    }

    public func selectTopic(_ id: String) throws {
        guard configuration.topics.contains(where: { $0.id == id }) else { throw AppStoreError.invalidTopic }
        var candidate = runtime
        candidate.selectedTopicID = id
        try persistRuntime(candidate)
    }

    public func selectReport(_ id: UUID?) {
        selectedReportID = id
    }

    public func saveTopic(_ topic: TopicRecordV1, creating: Bool = false) throws {
        try requireBehaviorChange()
        var candidate = configuration
        if creating {
            guard !candidate.topics.contains(where: { $0.id == topic.id }) else { throw AppStoreError.invalidTopic }
            candidate.topics.append(topic)
        } else {
            guard let index = candidate.topics.firstIndex(where: { $0.id == topic.id }) else { throw AppStoreError.invalidTopic }
            candidate.topics[index] = topic
        }
        try persistConfiguration(candidate)
        if creating { topicDraft = nil }
        Task { await startScheduling() }
    }

    public func setCacheLimit(_ bytes: UInt64?) throws {
        try requireBehaviorChange()
        var candidate = configuration
        candidate.storage.modelCacheLimitBytes = bytes
        try persistConfiguration(candidate)
    }

    public func setCodexExecutable(_ path: String) throws {
        try requireBehaviorChange()
        var directory: ObjCBool = false
        guard path.hasPrefix("/"), FileManager.default.fileExists(atPath: path, isDirectory: &directory),
              !directory.boolValue, FileManager.default.isExecutableFile(atPath: path),
              let index = configuration.providers.firstIndex(where: { $0.id == "codex" }) else {
            throw AppStoreError.invalidExecutable
        }
        var candidate = configuration
        candidate.providers[index].commandPath = path
        try persistConfiguration(candidate)
    }

    public func useCodexVerifier() throws {
        try requireBehaviorChange()
        var candidate = configuration
        guard let index = candidate.routes.firstIndex(where: { $0.task == "verifier" }),
              let route = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: candidate.workspaceRoot), codexExecutable: nil).routes.first(where: { $0.task == "verifier" }) else {
            throw DurableStateValidationError.invalidValue
        }
        candidate.routes[index] = route
        try persistConfiguration(candidate)
    }

    private func finishCommand() {
        commandActive = false; isEngineRunning = false; cancellationRequested = false
        requestDrain()
    }

    private func executePendingJobs() async {
        jobs = await queue.jobs()
        requestDrain()
        await drainTask?.value
    }

    private func requestDrain() {
        guard !isShuttingDown, !requiresReconciliation, jobs.contains(where: { $0.state == .pending }) else { return }
        drainRequested = true
        guard !commandActive, drainTask == nil else { return }
        drainTask = Task { await drainQueue() }
    }

    private func drainQueue() async {
        var failed = false
        defer {
            drainTask = nil; isEngineRunning = false; cancellationRequested = false
            if drainRequested && !failed { requestDrain() }
        }
        drainRequested = false
        guard !isShuttingDown else { return }
        guard executionGate.beginDrain() else { return }
        defer { executionGate.endDrain() }
        guard let coordinator else { lastErrorCode = "engine_missing"; return }
        isEngineRunning = true
        while !isShuttingDown {
            let attemptedID = await queue.jobs().first(where: { $0.state == .pending })?.id
            do {
                guard try await coordinator.executeNext(configuration: configuration) != nil else {
                    break
                }
                cancellationRequested = false
            } catch let failure as EngineCommandFailure {
                lastErrorCode = failure.error.code
                cancellationRequested = false
                jobs = await queue.jobs()
            } catch is EnginePersistenceError {
                failed = true
                requiresReconciliation = true
                lastErrorCode = "state_reconciliation_failed"
                await stopScheduling()
                break
            } catch EngineExecutionGateError.busy {
                failed = true
                lastErrorCode = "engine_busy"
                break
            } catch EngineExecutionGateError.admissionStopped {
                failed = true
                break
            } catch {
                jobs = await queue.jobs()
                guard let attemptedID,
                      let terminal = jobs.first(where: { $0.id == attemptedID }),
                      ![.pending, .running, .cancelling].contains(terminal.state) else {
                    failed = true
                    requiresReconciliation = true
                    lastErrorCode = "state_reconciliation_failed"
                    await stopScheduling()
                    break
                }
                lastErrorCode = terminal.error?.code ?? "engine_failed"
                cancellationRequested = false
            }
        }
        jobs = await queue.jobs()
        reports = await reportIndex.reports()
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

    private func scheduleAdmissionChanged(_ active: Bool) {
        admissionCount += active ? 1 : -1
    }

    private var enabledDeliveryChannels: [DeliveryChannel] {
        var channels: [DeliveryChannel] = []
        if configuration.delivery.wechat.enabled { channels.append(.wechat) }
        if configuration.delivery.email.enabled { channels.append(.email) }
        return channels
    }
}
