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
    case researchConfiguration(String)
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
    @ObservationIgnored private var secretPresenceLoaded = false
    @ObservationIgnored private var secretLookupFailed = false
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
    @ObservationIgnored private var schedulingBlockedByConfiguration = false
    @ObservationIgnored private let executionGate = EngineExecutionGate()
    public private(set) var requiresReconciliation = false
    public private(set) var scheduleFaulted = false

    public var requiresOnboarding: Bool {
        configuration.topics.isEmpty || runtime.onboardingInProgress == true
    }

    public var onboardingPage: OnboardingStep {
        switch runtime.onboardingStep {
        case .storage, .providers: return runtime.onboardingStep
        case .topicDescription, .topicReview: return .topicDescription
        default: return configuration.topics.isEmpty ? .topicDescription : .preflight
        }
    }

    public func setOnboardingStep(_ step: OnboardingStep) throws {
        guard requiresOnboarding else { return }
        guard [.storage, .providers, .topicDescription, .preflight].contains(step) else {
            throw DurableStateValidationError.invalidValue
        }
        guard step != .preflight || !configuration.topics.isEmpty else { throw AppStoreError.invalidTopic }
        var candidate = runtime
        candidate.onboardingInProgress = true
        candidate.onboardingStep = step
        try persistRuntime(candidate)
    }

    public func completeOnboarding() throws {
        guard !configuration.topics.isEmpty else { throw AppStoreError.invalidTopic }
        var candidate = runtime
        candidate.onboardingInProgress = false
        candidate.onboardingStep = .complete
        try persistRuntime(candidate)
    }

    public func startOnboardingResearch() async {
        guard !behaviorChangesBlocked else { lastErrorCode = "engine_busy"; return }
        guard selectedTopic?.isPaused == false else { lastErrorCode = "topic_invalid"; return }
        do {
            try validateResearchConfiguration()
            try completeOnboarding()
        } catch AppStoreError.researchConfiguration(let code) { lastErrorCode = code; return }
        catch { lastErrorCode = "configuration_write_failed"; return }
        await runSelectedTopicNow()
    }

    public var schedulePresentation: SchedulePresentation {
        SchedulePresentation(topic: selectedTopic, schedule: selectedTopicSchedule,
            paused: runtime.schedulesPaused, faulted: scheduleFaulted || requiresReconciliation,
            configurationError: researchConfigurationErrorCode, now: Date(), calendar: .current)
    }

    public var behaviorChangesBlocked: Bool {
        isShuttingDown || requiresReconciliation || isEngineRunning || admissionCount > 0 || drainTask != nil || jobs.contains {
            [.pending, .running, .cancelling].contains($0.state)
        }
    }

    public var selectedTopic: TopicRecordV1? {
        configuration.topics.first { $0.id == runtime.selectedTopicID } ?? configuration.topics.first
    }

    public var codexExecutableAvailable: Bool {
        configuration.providers.first(where: { $0.id == "codex" })?.commandPath.map(Self.isExecutable) ?? false
    }

    /// Local readiness only. Saved credentials do not imply a verified connection.
    public var researchConfigurationErrorCode: String? {
        do { try configuration.validate() } catch { return "invalid_configuration" }
        let tasks = ["source_gist", "deep_reading", "anchor_repair", "report_localization", "verifier"]
        for task in tasks {
            guard let route = configuration.routes.first(where: { $0.task == task }),
                  let provider = configuration.providers.first(where: { $0.id == route.providerID }) else {
                return "invalid_configuration"
            }
            switch provider.kind {
            case "codex_cli":
                guard let path = provider.commandPath, Self.isExecutable(path) else { return "codex_not_configured" }
            case "openai_compatible":
                guard let endpoint = provider.baseURL, let url = URL(string: endpoint),
                      ["http", "https"].contains(url.scheme), url.host != nil,
                      let name = provider.apiKeySecret, !name.isEmpty else { return "invalid_configuration" }
            case "anthropic_messages":
                guard let name = provider.apiKeySecret, !name.isEmpty else { return "invalid_configuration" }
            case "claude_code_cli":
                guard let path = provider.commandPath, Self.isExecutable(path) else { return "invalid_configuration" }
            case "local": break
            default: return "invalid_configuration"
            }
        }
        if secretLookupFailed { return "keychain_lookup_failed" }
        guard secretPresenceLoaded else { return "credentials_unchecked" }
        if researchSecretNames.contains(where: { secretPresence[$0] != true }) { return "credentials_missing" }
        return nil
    }

    private var researchSecretNames: Set<String> {
        let used = Set(configuration.routes.filter { $0.task != "topic_bootstrap" }.map(\.providerID))
        var names = Set(configuration.providers.filter { used.contains($0.id) }.compactMap(\.apiKeySecret))
        if configuration.discovery.webSearchProvider != nil,
           let name = configuration.discovery.webSearchSecret { names.insert(name) }
        return names
    }

    private static func isExecutable(_ path: String) -> Bool {
        var directory: ObjCBool = false
        return path.hasPrefix("/") && FileManager.default.fileExists(atPath: path, isDirectory: &directory)
            && !directory.boolValue && FileManager.default.isExecutableFile(atPath: path)
    }

    private func validateResearchConfiguration() throws {
        refreshSecretPresence()
        if let code = researchConfigurationErrorCode { throw AppStoreError.researchConfiguration(code) }
    }

    public var todayPresentation: TodayPresentation {
        TodayPresentation(topic: selectedTopic, jobs: jobs, reports: reports, schedules: schedules,
            schedulesPaused: runtime.schedulesPaused, now: Date(), calendar: .current)
    }

    public var engineStatusPresentation: EngineStatusPresentation? {
        jobs.first { [.running, .cancelling].contains($0.state) }.map {
            EngineStatusPresentation(job: $0, topics: configuration.topics)
        }
    }

    public var selectedTopicJobs: [JobRecordV1] {
        jobs.filter { $0.topicID == selectedTopic?.id }.sorted {
            if $0.createdAt != $1.createdAt { return $0.createdAt > $1.createdAt }
            return $0.id.uuidString > $1.id.uuidString
        }
    }

    public var selectedTopicReports: [ReportRecordV1] {
        reports.filter { $0.topicID == selectedTopic?.id }.sorted {
            if $0.reportDate != $1.reportDate { return $0.reportDate > $1.reportDate }
            if $0.createdAt != $1.createdAt { return $0.createdAt > $1.createdAt }
            return $0.id.uuidString > $1.id.uuidString
        }
    }

    public var selectedTopicSchedule: DailyScheduleV1? {
        schedules.first { $0.topicID == selectedTopic?.id }
    }

    public var latestReport: ReportRecordV1? { selectedTopicReports.first }

    public var selectedReport: ReportRecordV1? {
        selectedTopicReports.first { $0.id == selectedReportID }
    }

    /// Return only an existing regular HTML artifact contained in this app's workspace and run.
    public var selectedReportURL: URL? {
        guard let report = selectedReport else { return nil }
        let workspace = URL(fileURLWithPath: configuration.workspaceRoot).resolvingSymlinksInPath().standardizedFileURL
        let run = URL(fileURLWithPath: report.runDirectory).resolvingSymlinksInPath().standardizedFileURL
        let html = URL(fileURLWithPath: report.reportHTMLPath).resolvingSymlinksInPath().standardizedFileURL
        guard run.path.hasPrefix(workspace.path + "/"), html.path.hasPrefix(run.path + "/"),
              ["html", "htm"].contains(html.pathExtension.lowercased()),
              let values = try? html.resourceValues(forKeys: [.isRegularFileKey]),
              values.isRegularFile == true else { return nil }
        return html
    }

    public func setWindowMode(_ mode: WindowMode) throws {
        var candidate = runtime
        candidate.windowMode = mode
        try persistRuntime(candidate)
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
        loadSecretPresenceIfNeeded()
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
        defer { refreshSecretPresence(); finishCommand() }
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
        refreshSecretPresence()
    }

    public func refreshSecretPresence() {
        secretLookupFailed = false
        secretPresenceLoaded = true
        for name in researchSecretNames.union(["deepseek.api_key", "web_search.api_key"]) {
            do { secretPresence[name] = try secretStore.contains(account: name) }
            catch {
                secretPresence[name] = nil
                if researchSecretNames.contains(name) { secretLookupFailed = true }
                lastErrorCode = "keychain_lookup_failed"
            }
        }
        rearmRecoveredSchedules()
    }

    public func loadSecretPresenceIfNeeded() {
        if !secretPresenceLoaded { refreshSecretPresence() }
    }

    /// Detection is a suggestion; only setCodexExecutable persists a user's confirmation.
    public func detectedCodexExecutable(environmentPath: String? = ProcessInfo.processInfo.environment["PATH"],
                                        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser) -> URL? {
        let saved = configuration.providers.first { $0.id == "codex" }?.commandPath
        if let saved, Self.isExecutable(saved) { return nil }
        return CodexExecutableResolver().resolve(savedPath: nil, environmentPath: environmentPath, homeDirectory: homeDirectory)
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
            try configuration.validate()
            admissionCount += 1
            defer { admissionCount -= 1 }
            try await loginItemService.setEnabled(enabled)
            var candidate = configuration
            candidate.startAtLogin = enabled
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

    public func setUIAppearance(_ appearance: AppAppearancePreference) throws {
        var candidate = configuration
        candidate.uiAppearance = appearance
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
        let latestAttempt = reports.filter { $0.topicID == topicID && $0.reportDate == reportDate }.max {
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id.uuidString < $1.id.uuidString
        }
        if !forceNewAttempt, let report = latestAttempt, report.isEffectiveDeepReport {
            selectReport(report.id)
            lastErrorCode = nil
            return
        }
        do { try validateResearchConfiguration() }
        catch AppStoreError.researchConfiguration(let code) { lastErrorCode = code; return }
        catch { lastErrorCode = "invalid_configuration"; return }
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
        guard !isShuttingDown, !requiresReconciliation, !scheduleFaulted else { return }
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

    public func reconcileAfterLaunch(resumePending: Bool = true) async {
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
            if resumePending { await executePendingJobs() }
        } catch {
            requiresReconciliation = true
            commandActive = false; isEngineRunning = false
            lastErrorCode = "state_reconciliation_failed"
        }
    }

    public func stopScheduling() async {
        scheduleFaulted = true
        await scheduleCoordinator.block()
    }

    public func recoverScheduling() async {
        guard !isShuttingDown, !isEngineRunning, admissionCount == 0, drainTask == nil else { return }
        admissionCount += 1
        defer { admissionCount -= 1 }
        do {
            // Do not overwrite corrupt or externally changed state with in-memory snapshots.
            let saved = try persistence.read(AppConfigurationV1.self, from: "config/app-config.json")
            let savedSchedules = try persistence.read(ScheduleSnapshotV1.self, from: "state/schedules.json")
            let savedRuntime = try persistence.read(AppRuntimeStateV1.self, from: "state/app-state.json")
            let savedQueue = try persistence.read(JobQueueSnapshotV1.self, from: "state/queue.json")
            let savedReports = try persistence.read(ReportIndexV1.self, from: "state/report-index.json")
            let currentJobs = await queue.jobs()
            let currentReports = await reportIndex.reports()
            guard saved == configuration, savedSchedules.schedules == schedules,
                  try JSONCoding.encode(savedRuntime) == JSONCoding.encode(runtime),
                  try JSONCoding.encode(savedQueue.jobs) == JSONCoding.encode(currentJobs),
                  try JSONCoding.encode(savedReports.reports) == JSONCoding.encode(currentReports) else {
                throw DurableStateValidationError.invalidValue
            }
            try validateResearchConfiguration()
            if requiresReconciliation { await reconcileAfterLaunch(resumePending: false) }
            guard !requiresReconciliation, !isShuttingDown else { return }
            await refreshScheduleInputs()
            guard !isShuttingDown else { return }
            try await scheduleCoordinator.recover()
            guard !isShuttingDown else { return }
            scheduleFaulted = false
            lastErrorCode = nil
            jobs = await queue.jobs()
            requestDrain()
        } catch {
            await stopScheduling()
            lastErrorCode = "schedule_recovery_failed"
        }
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
        await scheduleCoordinator.stop()
        await cancelActiveJob()
        await drainTask?.value
    }

    public func setSchedulesPaused(_ paused: Bool) throws {
        try requireBehaviorChange()
        if !paused, schedules.contains(where: \.isEnabled) { try validateResearchConfiguration() }
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
        if enabled { try validateResearchConfiguration() }
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
        } catch AppStoreError.researchConfiguration(let code) {
            lastErrorCode = code
        } catch {
            lastErrorCode = "schedule_write_failed"
        }
    }

    private func persistConfiguration(_ candidate: AppConfigurationV1, invalidatePreflight: Bool = true) throws {
        try candidate.validate()
        try persistence.write(candidate, to: "config/app-config.json")
        configuration = candidate
        if invalidatePreflight { preflight = nil }
        rearmRecoveredSchedules()
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
        catch AppStoreError.researchConfiguration(let code) { lastErrorCode = code }
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
        guard let id else { selectedReportID = nil; return }
        guard selectedTopicReports.contains(where: { $0.id == id }) else { return }
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
        try candidate.validate()
        let onboarding = requiresOnboarding
        // Persist the marker first so a crash between writes cannot skip the ready page.
        if onboarding { try setOnboardingStep(.topicDescription) }
        try persistConfiguration(candidate)
        if creating { topicDraft = nil }
        if onboarding { try setOnboardingStep(.preflight) }
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

    public func setCodexReasoningEffort(_ effort: String) throws {
        try requireBehaviorChange()
        guard ["high", "xhigh"].contains(effort),
              let index = configuration.providers.firstIndex(where: { $0.id == "codex" && $0.kind == "codex_cli" }) else {
            throw DurableStateValidationError.invalidValue
        }
        var candidate = configuration
        candidate.providers[index].reasoningEffort = effort
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
            let next = await queue.jobs().first(where: { $0.state == .pending })
            let attemptedID = next?.id
            do {
                if let next, next.kind == .research {
                    refreshSecretPresence()
                    if let code = researchConfigurationErrorCode {
                        try await queue.transition(jobID: next.id, to: .cancelled,
                            error: RedactedEngineErrorV1(code: code, message: "Research configuration needs attention.", retryable: false))
                        lastErrorCode = code
                        jobs = await queue.jobs()
                        continue
                    }
                }
                guard try await coordinator.executeNext(
                    configuration: configuration,
                    onJobsChanged: { [weak self] snapshot in await self?.receiveJobs(snapshot) },
                    onObservationFailure: { [weak self] in await self?.recordObservationFailure() }
                ) != nil else {
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
            jobs = await queue.jobs()
            reports = await reportIndex.reports()
        }
        jobs = await queue.jobs()
        reports = await reportIndex.reports()
        await refreshScheduleInputs()
    }


    private func refreshScheduleInputs() async {
        // This call already refreshes scheduling; metadata refresh must not enqueue another one.
        schedulingBlockedByConfiguration = false
        if !runtime.schedulesPaused, schedules.contains(where: \.isEnabled) {
            refreshSecretPresence()
        }
        let blocked = researchConfigurationErrorCode
        schedulingBlockedByConfiguration = !runtime.schedulesPaused
            && schedules.contains(where: \.isEnabled) && blocked != nil
        if !runtime.schedulesPaused, schedules.contains(where: \.isEnabled), let blocked { lastErrorCode = blocked }
        await scheduleSource.update(ScheduleInputs(
            schedules: schedules, topics: configuration.topics,
            reports: reports, paused: runtime.schedulesPaused || blocked != nil
        ))
    }

    private func rearmRecoveredSchedules() {
        guard schedulingBlockedByConfiguration, !isShuttingDown, !requiresReconciliation,
              !runtime.schedulesPaused, schedules.contains(where: \.isEnabled),
              researchConfigurationErrorCode == nil else { return }
        schedulingBlockedByConfiguration = false
        Task { await startScheduling() }
    }

    private func receiveJobs(_ snapshot: [JobRecordV1]) { jobs = snapshot }

    private func recordObservationFailure() { lastErrorCode = "event_observation_failed" }

    private func recordScheduleFailure() {
        scheduleFaulted = true
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
