import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct NotificationServiceTests {
    @Test func preferenceIsOptInAndOnlyExplicitEnableRequestsPermission() async throws {
        let root = URL(fileURLWithPath: NSTemporaryDirectory()).appending(path: UUID().uuidString)
        defer { trash(root) }
        let client = OfflineNotificationClient()
        let store = makeStore(root, client: client)
        #expect(!store.reportNotificationsEnabled)
        #expect(client.checks == 0 && client.requests == 0)
        await store.setReportNotificationsEnabled(true)
        #expect(store.reportNotificationsEnabled && client.requests == 1)
        let saved = try AtomicJSONStore(root: root).read(AppRuntimeStateV1.self, from: "state/app-state.json")
        #expect(saved.reportNotificationsEnabled == true)
        let restarted = makeStore(root, client: client, runtime: saved)
        #expect(restarted.reportNotificationsEnabled && client.requests == 1)
        await restarted.setReportNotificationsEnabled(false)
        #expect(!restarted.reportNotificationsEnabled && client.requests == 1)
    }

    @Test func deniedOrFailedPermissionDoesNotEnableOrChangeResearchState() async throws {
        for denial in [true, false] {
            let client = OfflineNotificationClient()
            client.authorization = denial ? .denied : .notDetermined
            client.failRequest = !denial
            let store = makeStore(temporaryRoot(), client: client)
            await store.setReportNotificationsEnabled(true)
            #expect(!store.reportNotificationsEnabled)
            #expect(store.notifications.issue != nil)
            #expect(store.lastErrorCode == nil && store.jobs.isEmpty && store.reports.isEmpty)
            #expect(client.requests == (denial ? 0 : 1))
        }
    }

    @Test func failedPreferenceSaveKeepsTheOriginalPreference() async throws {
        let root = temporaryRoot()
        defer { trash(root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("blocked".utf8).write(to: root.appending(path: "state"))
        let store = makeStore(root, client: OfflineNotificationClient())
        await store.setReportNotificationsEnabled(true)
        #expect(!store.reportNotificationsEnabled)
        #expect(store.notifications.issue == .preferenceSaveFailed)
    }

    @Test func oldRuntimeDefaultsToDisabled() throws {
        let data = try JSONCoding.encode(AppRuntimeStateV1(updatedAt: Date()))
        let decoded = try JSONCoding.decode(AppRuntimeStateV1.self, from: data)
        #expect(decoded.reportNotificationsEnabled == nil)
    }

    @Test func notificationsAreLocalizedPrivateAndDeduplicated() async throws {
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        let service = NotificationService(client: client)
        let job = try researchJob(.succeeded)
        let report = report(for: job)
        await service.notify(job: job, report: report, language: .english, shouldDeliver: { true })
        await service.notify(job: job, report: report, language: .simplifiedChinese, shouldDeliver: { true })
        #expect(client.messages.count == 1)
        let readyMessage = try #require(client.messages.first)
        #expect(readyMessage.body == "Your report is ready. Click to read it.")
        let failed = try researchJob(.failed)
        await service.notify(job: failed, report: nil, language: .simplifiedChinese, shouldDeliver: { true })
        #expect(client.messages.count == 2)
        let failedMessage = try #require(client.messages.dropFirst().first)
        #expect(failedMessage.body.contains("诊断"))
        #expect(failedMessage.subtitle.contains("摘要"))
        for message in client.messages {
            let text = message.title + message.subtitle + message.body
            for privateValue in ["private_canary", "/Users/", "Bearer", "example.test", "Unpublished"] {
                #expect(!text.contains(privateValue))
            }
        }
        #expect(client.requests == 0)
    }

    @Test func emptyCancelledDeliveryAndDisabledTasksDoNotNotify() async throws {
        let client = OfflineNotificationClient()
        let service = NotificationService(client: client)
        let successful = try researchJob(.succeeded)
        await service.notify(job: successful, report: report(for: successful, effective: false),
            language: .english, shouldDeliver: { true })
        await service.notify(job: try researchJob(.cancelled), report: nil,
            language: .english, shouldDeliver: { true })
        let delivery = try JobRecordV1(kind: .delivery, topicID: "private_canary", reportDate: "2026-10-22",
            deliveryChannel: .email, trigger: .retry, state: .failed,
            jobDirectory: "/private/fixture", runDirectory: "/private/report", createdAt: Date())
        await service.notify(job: delivery, report: nil, language: .english, shouldDeliver: { true })
        await service.notify(job: successful, report: report(for: successful), language: .english, shouldDeliver: { false })
        #expect(client.checks == 0 && client.requests == 0 && client.messages.isEmpty)
    }

    @Test func authorizationRevocationAndSubmissionFailureAreNonfatal() async throws {
        let client = OfflineNotificationClient()
        client.authorization = .denied
        let service = NotificationService(client: client)
        let job = try researchJob(.failed)
        await service.notify(job: job, report: nil, language: .english, shouldDeliver: { true })
        #expect(client.messages.isEmpty && client.requests == 0)
        #expect(service.issue == .permissionDenied)
        client.authorization = .allowed
        client.failAdd = true
        await service.notify(job: try researchJob(.failed), report: nil, language: .english, shouldDeliver: { true })
        #expect(service.issue == .submissionFailed)
    }

    @Test func realQueueCompletionNotifiesOnceAndRestartDoesNotReplayIt() async throws {
        let root = temporaryRoot()
        defer { trash(root) }
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        let store = makeStore(root, client: client, runner: NotificationWorkflowRunner(fails: false))
        await store.setReportNotificationsEnabled(true)
        await store.runNow(topicID: "memory", reportDate: "2026-10-22")
        let report = try #require(store.reports.first)
        #expect(store.jobs.first?.state == .succeeded && client.messages.count == 1)
        #expect(try store.openReportNotification(jobID: report.id) == report.id)
        #expect(store.runtime.selectedTopicID == "memory" && store.runtime.windowMode == .full)
        let restarted = AppStore(configuration: store.configuration, queueSnapshot: .init(jobs: store.jobs),
            reportSnapshot: .init(reports: store.reports), runtime: store.runtime, appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/fixture/engine"), runner: NotificationWorkflowRunner(fails: false),
            secretStore: AdmissionSecrets(), notificationClient: client)
        await restarted.reconcileAfterLaunch()
        #expect(client.messages.count == 1)
        #expect(throws: (any Error).self) { try restarted.openReportNotification(jobID: UUID()) }
    }

    @Test func actualFailureUsesTerminalStageAndDoesNotChangeItsOutcome() async throws {
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        let root = temporaryRoot()
        defer { trash(root) }
        let store = makeStore(root, client: client, runner: NotificationWorkflowRunner(fails: true))
        await store.setReportNotificationsEnabled(true)
        await store.runNow(topicID: "memory", reportDate: "2026-10-22")
        let job = try #require(store.jobs.first)
        #expect(job.state == .failed && job.stage == .sourceGist)
        #expect(store.lastErrorCode == "model_transport_failed")
        #expect(client.messages.count == 1 && store.reports.isEmpty)
        #expect(try store.openReportNotification(jobID: job.id) == nil)
        let presentation = WindowPresentationState()
        presentation.openReportNotification(jobID: job.id, store: store)
        #expect(presentation.requestedSection == .diagnostics)
        #expect(store.lastErrorCode == "model_transport_failed")
    }

    @Test func submissionFailureDoesNotDowngradeASuccessfulReport() async throws {
        let root = temporaryRoot()
        defer { trash(root) }
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        client.failAdd = true
        let store = makeStore(root, client: client, runner: NotificationWorkflowRunner(fails: false))
        await store.setReportNotificationsEnabled(true)
        await store.runNow(topicID: "memory", reportDate: "2026-10-22")
        #expect(store.reports.first?.isEffectiveDeepReport == true)
        #expect(store.jobs.first?.state == .succeeded && store.lastErrorCode == nil)
        #expect(store.notifications.issue == .submissionFailed)
    }

    @Test func disablingWhileCheckingAuthorizationPreventsSubmission() async throws {
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        var enabled = true
        client.onCheck = { enabled = false }
        let service = NotificationService(client: client)
        await service.notify(job: try researchJob(.failed), report: nil, language: .english, shouldDeliver: { enabled })
        #expect(client.messages.isEmpty)
    }

    @Test func forcedCancellationWithoutTerminalArtifactsDoesNotNotifyFailure() async throws {
        let root = temporaryRoot()
        defer { trash(root) }
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        let runner = CancelledNotificationRunner()
        let store = makeStore(root, client: client, runner: runner)
        await store.setReportNotificationsEnabled(true)
        let run = Task { await store.runNow(topicID: "memory", reportDate: "2026-10-22") }
        await runner.waitForStart()
        await store.cancelActiveJob()
        await run.value
        #expect(store.jobs.first?.state == .interrupted)
        #expect(client.messages.isEmpty)
    }

    @Test func compactNotificationFallbackShowsDiagnosticsEvenWhenSavingFails() throws {
        let root = temporaryRoot()
        defer { trash(root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("blocked".utf8).write(to: root.appending(path: "state"))
        let job = try JobRecordV1(kind: .research, topicID: "memory", reportDate: "2026-10-22",
            trigger: .runNow, state: .failed, jobDirectory: "/fixture", createdAt: Date())
        let original = makeStore(root, client: OfflineNotificationClient())
        let store = AppStore(configuration: original.configuration, queueSnapshot: .init(jobs: [job]),
            runtime: .init(onboardingStep: .complete, windowMode: .compact, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets(), notificationClient: OfflineNotificationClient())
        let presentation = WindowPresentationState()
        presentation.openReportNotification(jobID: job.id, store: store)
        #expect(presentation.windowMode(saved: store.runtime.windowMode) == .full)
        #expect(presentation.requestedSection == .diagnostics)
        #expect(store.runtime.windowMode == .compact && store.lastErrorCode == "configuration_write_failed")
    }

    @Test func effectiveOutcomeControlsCompletionNotJustPositiveCounts() async throws {
        let client = OfflineNotificationClient()
        client.authorization = .allowed
        let service = NotificationService(client: client)
        for outcome in ResearchOutcomeV1.Status.allCases {
            let job = try researchJob(.partialSuccess)
            let result = ReportRecordV1(id: job.id, topicID: job.topicID, reportDate: job.reportDate,
                runDirectory: "/fixture", articleDraftPath: "/fixture/draft", reportHTMLPath: "/fixture/html",
                title: "Fixture", summary: "", sourceCount: 2, deepReadCount: 1, publishableClaimCount: 1,
                deliveries: [], createdAt: Date(), researchOutcome: .init(status: outcome, reasons: []))
            await service.notify(job: job, report: result, language: .english, shouldDeliver: { true })
        }
        #expect(client.messages.count == 1)
        await service.notify(job: try researchJob(.interrupted), report: nil,
            language: .english, shouldDeliver: { true })
        #expect(client.messages.count == 2)
    }

    private func makeStore(_ root: URL, client: OfflineNotificationClient,
        runtime: AppRuntimeStateV1 = .init(updatedAt: Date()), runner: (any EngineProcessRunning)? = nil) -> AppStore {
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        config.topics = [.init(id: "memory", displayName: "Unpublished private_canary",
            researchFocus: "Agent memory", queries: ["agent memory"], paperQueries: ["agent memory"], reportLanguage: .english)]
        return AppStore(configuration: config, runtime: runtime, appSupportRoot: root,
            engineURL: runner == nil ? nil : URL(fileURLWithPath: "/fixture/engine"), runner: runner,
            secretStore: AdmissionSecrets(), notificationClient: client)
    }

    private func temporaryRoot() -> URL {
        FileManager.default.temporaryDirectory.appending(path: "report-notification-\(UUID())")
    }

    private func trash(_ root: URL) {
        guard FileManager.default.fileExists(atPath: root.path) else { return }
        do {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
            process.arguments = [root.path]
            try process.run()
            process.waitUntilExit()
            #expect(process.terminationStatus == 0)
        } catch { Issue.record("Could not move notification test data to Trash") }
    }

    private func researchJob(_ state: JobState) throws -> JobRecordV1 {
        try JobRecordV1(kind: .research, topicID: "private_canary", reportDate: "2026-10-22", trigger: .runNow,
            state: state, stage: .sourceGist, jobDirectory: "/private/fixture", createdAt: Date(),
            error: .init(code: "model_transport_failed", message: "Bearer private_canary", retryable: false))
    }

    private func report(for job: JobRecordV1, effective: Bool = true) -> ReportRecordV1 {
        .init(id: job.id, topicID: job.topicID, reportDate: job.reportDate, runDirectory: "/private/report",
            articleDraftPath: "/private/report/draft.json", reportHTMLPath: "/private/report/report.html",
            title: "Unpublished private_canary", summary: "reader@example.test", sourceCount: 2,
            deepReadCount: effective ? 1 : 0, publishableClaimCount: effective ? 1 : 0, deliveries: [], createdAt: Date())
    }
}

@MainActor final class OfflineNotificationClient: ReportNotificationClient {
    var authorization: ReportNotificationAuthorization = .notDetermined
    var checks = 0
    var requests = 0
    var messages: [ReportNotificationMessage] = []
    var failRequest = false
    var failAdd = false
    var onCheck: (() -> Void)?
    func authorizationStatus() async -> ReportNotificationAuthorization {
        checks += 1
        onCheck?()
        return authorization
    }
    func requestAuthorization() async throws -> Bool {
        requests += 1
        if failRequest { throw CocoaError(.coderInvalidValue) }
        authorization = .allowed
        return true
    }
    func add(_ message: ReportNotificationMessage) async throws {
        if failAdd { throw CocoaError(.coderInvalidValue) }
        messages.append(message)
    }
    func activate(onOpen: @escaping @MainActor @Sendable (UUID) -> Void) {}
}

private actor NotificationWorkflowRunner: EngineProcessRunning {
    let fails: Bool
    init(fails: Bool) { self.fails = fails }
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        func path(_ flag: String) throws -> URL {
            let index = try #require(arguments.firstIndex(of: flag))
            return URL(fileURLWithPath: arguments[index + 1])
        }
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: path("--request")))
        #expect(request.command == .runDaily)
        if fails {
            try JSONSerialization.data(withJSONObject: ["schema_version": 1,
                "request_id": request.requestID.uuidString.lowercased(), "status": "failed", "stage": "source_gist",
                "code": "model_transport_failed", "message": "private_canary", "retryable": true,
                "completed_at": "2026-10-22T00:00:00Z"]).write(to: path("--error"))
        } else {
            let run = URL(fileURLWithPath: request.appSupportRoot).appending(path: "workspace/runs/\(request.requestID)")
            try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
            let draft = run.appending(path: "article_draft.json"), html = run.appending(path: "wechat.html")
            try Data(#"{"topic_id":"memory"}"#.utf8).write(to: draft)
            try Data("<html lang=\"zh\">报告</html>".utf8).write(to: html)
            try EngineProtocolCodec.encode(EngineResultV1(requestID: request.requestID, command: .runDaily,
                status: .succeeded, completedAt: Date(), report: .init(runDirectory: run.path, reportDate: "2026-10-22",
                    articleDraftPath: draft.path, reportHTMLPath: html.path, title: "Fixture", summary: "Fixture",
                    sourceCount: 2, deepReadCount: 1, publishableClaimCount: 2))).write(to: path("--result"))
        }
        return EngineProcessOutcome(exitCode: fails ? 1 : 0, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
}

private actor CancelledNotificationRunner: EngineProcessRunning {
    private var completion: CheckedContinuation<EngineProcessOutcome, Never>?
    private var started: CheckedContinuation<Void, Never>?
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        await withCheckedContinuation { continuation in
            completion = continuation
            started?.resume(); started = nil
        }
    }
    func waitForStart() async {
        if completion != nil { return }
        await withCheckedContinuation { started = $0 }
    }
    func cancel() async {
        completion?.resume(returning: .init(exitCode: 137, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data()))
        completion = nil
    }
}
