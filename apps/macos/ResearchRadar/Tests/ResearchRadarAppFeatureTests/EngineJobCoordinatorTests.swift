import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

private actor FakeEngineRunner: EngineProcessRunning {
    private(set) var lastArguments: [String] = []
    let result: EngineResultV1?
    let exitCode: Int32
    let afterResult: @Sendable () throws -> Void

    init(result: EngineResultV1?, exitCode: Int32 = 0, afterResult: @escaping @Sendable () throws -> Void = {}) {
        self.result = result; self.exitCode = exitCode
        self.afterResult = afterResult
    }

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        lastArguments = arguments
        if let result, let resultIndex = arguments.firstIndex(of: "--result") {
            try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[resultIndex + 1]))
        }
        try afterResult()
        return EngineProcessOutcome(
            exitCode: exitCode, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data()
        )
    }

    func cancel() async {}
}

@Suite struct EngineJobCoordinatorTests {
    @Test func dailyExecutionPassesConfiguredPDFHelperAsAnArgument() async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        let id = try enqueuedID(try await fixture.queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .runNow
        ))
        let helper = URL(fileURLWithPath: "/Applications/Research Radar.app/Contents/Helpers/ResearchRadarPDFHelper")
        let runner = FakeEngineRunner(result: fixture.result(id: id))
        let coordinator = EngineJobCoordinator(
            runner: runner, engineURL: URL(fileURLWithPath: "/fake"), appSupportRoot: fixture.root,
            queue: fixture.queue, reports: fixture.reports, pdfHelperURL: helper, gate: fixture.gate
        )
        _ = try await coordinator.executeNext(configuration: testConfiguration(root: fixture.root))
        let arguments = await runner.lastArguments
        let index = try #require(arguments.firstIndex(of: "--pdf-helper"))
        #expect(arguments[index + 1] == helper.path)
        #expect(arguments.filter { $0 == "--pdf-helper" }.count == 1)
        #expect(await fixture.queue.jobs().first?.state == .succeeded)
    }

    @Test func successfulDailyPersistsReportBeforeIndependentDeliveryJobs() async throws {
        let root = try coordinatorRoot()
        defer { try? trashCoordinatorRoot(root) }
        let run = root.appending(path: "workspace/runs/report", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let draft = run.appending(path: "article_draft.json")
        let html = run.appending(path: "wechat.html")
        try Data(#"{"topic_id":"memory"}"#.utf8).write(to: draft); try Data("<html></html>".utf8).write(to: html)
        let store = AtomicJSONStore(root: root)
        let queue = JobQueue(store: store, jobsRoot: root.appending(path: "jobs"))
        let reports = ReportIndexStore(store: store)
        let enqueued = try await queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .runNow,
            deliveryChannels: [.wechat, .email]
        )
        let requestID = try enqueuedID(enqueued)
        let result = EngineResultV1(
            requestID: requestID, command: .runDaily, status: .succeeded,
            completedAt: Date(timeIntervalSince1970: 20),
            report: EngineReportSummaryV1(
                runDirectory: run.path, reportDate: "2026-08-30",
                articleDraftPath: draft.path, reportHTMLPath: html.path,
                title: "Daily", summary: "Summary", sourceCount: 3,
                deepReadCount: 1, publishableClaimCount: 4
            )
        )
        let coordinator = EngineJobCoordinator(
            runner: FakeEngineRunner(result: result), engineURL: URL(fileURLWithPath: "/fake/engine"),
            appSupportRoot: root, queue: queue, reports: reports, gate: EngineExecutionGate()
        )

        _ = try await coordinator.executeNext(configuration: testConfiguration(root: root))

        let indexed = await reports.reports()
        let jobs = await queue.jobs()
        #expect(indexed.count == 1)
        #expect(jobs.first?.state == .succeeded)
        #expect(jobs.filter { $0.kind == .delivery }.map(\.deliveryChannel) == [.wechat, .email])
    }

    @Test func failedDailyDoesNotCreateAReportOrDelivery() async throws {
        let root = try coordinatorRoot()
        defer { try? trashCoordinatorRoot(root) }
        let store = AtomicJSONStore(root: root)
        let queue = JobQueue(store: store, jobsRoot: root.appending(path: "jobs"))
        let reports = ReportIndexStore(store: store)
        _ = try await queue.enqueueResearch(topicID: "memory", reportDate: "2026-08-30", trigger: .runNow)
        let coordinator = EngineJobCoordinator(
            runner: FakeEngineRunner(result: nil, exitCode: 1),
            engineURL: URL(fileURLWithPath: "/fake/engine"), appSupportRoot: root,
            queue: queue, reports: reports, gate: EngineExecutionGate()
        )

        await #expect(throws: EngineCommandFailure.self) {
            _ = try await coordinator.executeNext(configuration: testConfiguration(root: root))
        }

        #expect(await reports.reports().isEmpty)
        #expect(await queue.jobs().count == 1)
        #expect(await queue.jobs().first?.state == .interrupted)
    }

    @Test func launchReconciliationCompletesAResultWrittenBeforeTheAppCrashed() async throws {
        let root = try coordinatorRoot()
        defer { try? trashCoordinatorRoot(root) }
        let run = root.appending(path: "workspace/runs/report", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let draft = run.appending(path: "article_draft.json")
        let html = run.appending(path: "wechat.html")
        try Data(#"{"topic_id":"memory"}"#.utf8).write(to: draft)
        try Data("<html></html>".utf8).write(to: html)
        let store = AtomicJSONStore(root: root)
        let queue = JobQueue(store: store, jobsRoot: root.appending(path: "jobs"))
        let reports = ReportIndexStore(store: store)
        let enqueued = try await queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .runNow,
            deliveryChannels: [.wechat, .email]
        )
        let requestID = try enqueuedID(enqueued)
        _ = try await queue.nextPending()
        let jobDirectory = root.appending(path: "jobs/\(requestID.uuidString.lowercased())")
        try FileManager.default.createDirectory(at: jobDirectory, withIntermediateDirectories: true)
        _ = try FoundationJobBuilder.create(
            request: researchRequest(id: requestID, root: root), jobDirectory: jobDirectory
        )
        let result = EngineResultV1(
            requestID: requestID, command: .runDaily, status: .succeeded,
            completedAt: Date(timeIntervalSince1970: 20),
            report: EngineReportSummaryV1(
                runDirectory: run.path, reportDate: "2026-08-30",
                articleDraftPath: draft.path, reportHTMLPath: html.path,
                title: "Daily", summary: "Summary", sourceCount: 3,
                deepReadCount: 1, publishableClaimCount: 4
            )
        )
        try EngineProtocolCodec.encode(result).write(
            to: jobDirectory.appending(path: "result.json")
        )
        let coordinator = EngineJobCoordinator(
            runner: FakeEngineRunner(result: nil), engineURL: URL(fileURLWithPath: "/fake/engine"),
            appSupportRoot: root, queue: queue, reports: reports, gate: EngineExecutionGate()
        )

        try await coordinator.reconcileAfterLaunch()

        #expect(await reports.reports().count == 1)
        let jobs = await queue.jobs()
        #expect(jobs.first?.state == .succeeded)
        #expect(jobs.filter { $0.kind == .delivery }.map(\.deliveryChannel) == [.wechat, .email])
    }

    @Test func launchReconciliationRestoresDeliveryJobsMissingAfterReportPersistence() async throws {
        let root = try coordinatorRoot()
        defer { try? trashCoordinatorRoot(root) }
        let run = root.appending(path: "workspace/runs/report", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let store = AtomicJSONStore(root: root)
        let queue = JobQueue(store: store, jobsRoot: root.appending(path: "jobs"))
        let reports = ReportIndexStore(store: store)
        try await reports.upsert(ReportRecordV1(
            topicID: "memory",
            reportDate: "2026-08-30",
            runDirectory: run.path,
            articleDraftPath: run.appending(path: "article_draft.json").path,
            reportHTMLPath: run.appending(path: "wechat.html").path,
            title: "Daily",
            summary: "Summary",
            sourceCount: 3,
            deepReadCount: 1,
            publishableClaimCount: 4,
            deliveries: [DeliveryRecordV1(channel: .email, state: .pending)],
            createdAt: Date(timeIntervalSince1970: 20)
        ))
        let coordinator = EngineJobCoordinator(
            runner: FakeEngineRunner(result: nil),
            engineURL: URL(fileURLWithPath: "/fake/engine"),
            appSupportRoot: root,
            queue: queue,
            reports: reports, gate: EngineExecutionGate()
        )

        try await coordinator.reconcileAfterLaunch()

        let deliveryJobs = await queue.jobs().filter { $0.kind == .delivery }
        #expect(deliveryJobs.count == 1)
        #expect(deliveryJobs.first?.deliveryChannel == .email)
    }

    @Test(arguments: ["report-index.json", "queue.json"])
    func validSuccessSurvivesPersistenceFailureAndReconciles(file: String) async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        let id = try enqueuedID(try await fixture.queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .schedule,
            deliveryChannels: [.email]
        ))
        let result = fixture.result(id: id)
        let blocker = fixture.root.appending(path: "state/\(file)")
        let runner = FakeEngineRunner(result: result, exitCode: 17) {
            if FileManager.default.fileExists(atPath: blocker.path) { try trashCoordinatorRoot(blocker) }
            try FileManager.default.createDirectory(at: blocker, withIntermediateDirectories: true)
        }
        let coordinator = fixture.coordinator(runner: runner)
        await #expect(throws: EnginePersistenceError.reconciliationRequired(jobID: id)) {
            _ = try await coordinator.executeNext(configuration: testConfiguration(root: fixture.root))
        }
        #expect(await fixture.queue.jobs().first?.state == .running)
        #expect(throws: EngineExecutionGateError.reconciliationRequired) { try fixture.gate.acquire() }
        let artifact = fixture.root.appending(path: "jobs/\(id.uuidString.lowercased())/result.json")
        #expect(try EngineProtocolCodec.decodeResult(Data(contentsOf: artifact)) == result)

        try trashCoordinatorRoot(blocker)
        try await coordinator.reconcileAfterLaunch()
        #expect(await fixture.queue.jobs().first?.state == .succeeded)
        try await fixture.reports.updateDelivery(
            runDirectory: fixture.run.path, channel: .email, state: .sent,
            error: nil, at: Date(timeIntervalSince1970: 30)
        )
        try await coordinator.reconcileAfterLaunch()
        #expect(await fixture.reports.reports().count == 1)
        #expect(await fixture.reports.reports().first?.deliveries.first?.state == .sent)
        #expect(await fixture.queue.jobs().filter { $0.kind == .delivery }.count == 1)
    }

    @Test func busyCommandDoesNotClaimScheduledResearch() async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        _ = try await fixture.queue.enqueueResearch(topicID: "memory", reportDate: "2026-08-30", trigger: .schedule)
        let runner = BlockingEngineRunner()
        let client = EngineCommandClient(
            runner: runner, engineURL: URL(fileURLWithPath: "/fake"),
            appSupportRoot: fixture.root, gate: fixture.gate
        )
        let task = Task { try await client.preflight(liveProbe: false) }
        await runner.waitUntilStarted()
        await #expect(throws: EngineExecutionGateError.busy) {
            _ = try await fixture.coordinator(runner: runner).executeNext(configuration: testConfiguration(root: fixture.root))
        }
        #expect(await fixture.queue.jobs().first?.state == .pending)
        await client.cancel()
        await client.cancel()
        await fixture.coordinator(runner: runner).cancel()
        _ = try? await task.value
        #expect(await runner.cancellations == 1)
    }

    @Test(arguments: ["cancelled", "parent_lost", "engine_crashed"])
    func researchErrorPreservesCodeAndStage(code: String) async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        let id = try enqueuedID(try await fixture.queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .runNow
        ))
        let errorURL = fixture.root.appending(path: "jobs/\(id.uuidString.lowercased())/error.json")
        let runner = FakeEngineRunner(result: nil, exitCode: 1) {
            try terminalError(id: id, code: code, stage: "compose").write(to: errorURL)
        }
        await #expect(throws: EngineCommandFailure.self) {
            _ = try await fixture.coordinator(runner: runner).executeNext(configuration: testConfiguration(root: fixture.root))
        }
        let job = try #require(await fixture.queue.jobs().first)
        #expect(job.state == (code == "cancelled" ? .cancelled : code == "parent_lost" ? .interrupted : .failed))
        #expect(job.error?.code == code)
        #expect(job.stage == .compose)
    }

    @Test func deliveryCancellationIsUnknownAndCannotRetrySilently() async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        try await fixture.indexReport()
        let id = try enqueuedID(try await fixture.queue.enqueueDelivery(
            runDirectory: fixture.run, topicID: "memory", reportDate: "2026-08-30", channel: .email
        ))
        let errorURL = fixture.root.appending(path: "jobs/\(id.uuidString.lowercased())/error.json")
        let runner = FakeEngineRunner(result: nil, exitCode: 130) {
            try terminalError(id: id, code: "cancelled", stage: "email").write(to: errorURL)
        }
        await #expect(throws: EngineCommandFailure.self) {
            _ = try await fixture.coordinator(runner: runner).executeNext(configuration: testConfiguration(root: fixture.root))
        }
        #expect(await fixture.queue.jobs().first?.state == .deliveryUnknown)
        #expect(await fixture.reports.reports().first?.deliveries.first?.state == .unknown)
        await #expect(throws: JobRecordError.unknownDeliveryRequiresAcknowledgement) {
            _ = try await fixture.queue.enqueueDelivery(
                runDirectory: fixture.run, topicID: "different", reportDate: "2026-08-31", channel: .email
            )
        }
    }

    @Test(arguments: ["command", "request", "topic", "savedTopic"])
    func rejectsMismatchedResearchArtifacts(field: String) async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        let id = try enqueuedID(try await fixture.queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .runNow
        ))
        if field == "topic" {
            try Data(#"{"topic_id":"other"}"#.utf8).write(to: fixture.run.appending(path: "article_draft.json"))
        }
        let result = field == "command" ? EngineResultV1(
            requestID: id, command: .bootstrapTopic, status: .succeeded, completedAt: Date(),
            topicDraft: TopicDraftV1(
                id: "memory", displayName: "Memory", researchFocus: "Memory",
                queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese
            )
        ) : fixture.result(id: field == "request" ? UUID() : id)
        let runner = FakeEngineRunner(result: result) {
            if field == "savedTopic" {
                let request = try researchRequest(id: id, root: fixture.root, topicID: "other")
                try EngineProtocolCodec.encode(request).write(
                    to: fixture.root.appending(path: "jobs/\(id.uuidString.lowercased())/request.json")
                )
            }
        }
        await #expect(throws: EngineJobCoordinatorError.requestMismatch) {
            _ = try await fixture.coordinator(runner: runner)
                .executeNext(configuration: testConfiguration(root: fixture.root))
        }
        #expect(await fixture.reports.reports().isEmpty)
        #expect(await fixture.queue.jobs().first?.state != .succeeded)
    }

    @Test(arguments: ["run", "channel"])
    func rejectsMismatchedDeliveryArtifacts(field: String) async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        try await fixture.indexReport()
        let id = try enqueuedID(try await fixture.queue.enqueueDelivery(
            runDirectory: fixture.run, topicID: "memory", reportDate: "2026-08-30", channel: .email
        ))
        let result = EngineResultV1(
            requestID: id, command: .retryDelivery, status: .succeeded, completedAt: Date(),
            delivery: DeliveryResultV1(
                runDirectory: field == "run" ? fixture.root.path : fixture.run.path,
                channel: field == "channel" ? .wechat : .email,
                status: field == "channel" ? .created : .sent, completedAt: Date()
            )
        )
        await #expect(throws: EngineJobCoordinatorError.requestMismatch) {
            _ = try await fixture.coordinator(runner: FakeEngineRunner(result: result))
                .executeNext(configuration: testConfiguration(root: fixture.root))
        }
        #expect(await fixture.queue.jobs().first?.state == .deliveryUnknown)
        #expect(await fixture.reports.reports().first?.deliveries.first?.state == .unknown)
    }
    @Test(arguments: [JobKind.research, .delivery], [false, true])
    func invalidRecoveryArtifactIsRetainedWithoutBlockingOtherJobs(kind: JobKind, malformed: Bool) async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        if kind == .delivery { try await fixture.indexReport() }
        let enqueued: EnqueueResult
        if kind == .research {
            enqueued = try await fixture.queue.enqueueResearch(topicID: "memory", reportDate: "2026-08-30", trigger: .runNow)
        } else {
            enqueued = try await fixture.queue.enqueueDelivery(
                runDirectory: fixture.run, topicID: "memory", reportDate: "2026-08-30", channel: .email
            )
        }
        let id = try enqueuedID(enqueued)
        let job = try #require(try await fixture.queue.nextPending())
        let request = kind == .research ? try researchRequest(id: id, root: fixture.root)
            : try deliveryRequest(id: id, root: fixture.root, run: fixture.run)
        let paths = try FoundationJobBuilder.create(request: request, jobDirectory: URL(fileURLWithPath: job.jobDirectory))
        let wrongResult = kind == .research ? fixture.result(id: UUID()) : deliveryResult(id: UUID(), run: fixture.run)
        let artifact = malformed ? Data("{invalid".utf8) : try EngineProtocolCodec.encode(wrongResult)
        try artifact.write(to: paths.result)
        let pendingID = try enqueuedID(try await fixture.queue.enqueueResearch(
            topicID: "other", reportDate: "2026-08-30", trigger: .schedule
        ))

        try await fixture.coordinator(runner: FakeEngineRunner(result: nil)).reconcileAfterLaunch()
        let rejected = try #require(await fixture.queue.jobs().first { $0.id == id })
        #expect(rejected.state == (kind == .research ? .interrupted : .deliveryUnknown))
        #expect(rejected.error?.code == "terminal_invalid")
        #expect(try Data(contentsOf: paths.result) == artifact)

        let persistence = AtomicJSONStore(root: fixture.root)
        let restartedQueue = JobQueue(
            snapshot: try persistence.read(JobQueueSnapshotV1.self, from: "state/queue.json"),
            store: persistence, jobsRoot: fixture.root.appending(path: "jobs")
        )
        let restartedGate = EngineExecutionGate()
        let restarted = EngineJobCoordinator(
            runner: FakeEngineRunner(result: nil), engineURL: URL(fileURLWithPath: "/fake"),
            appSupportRoot: fixture.root, queue: restartedQueue, reports: fixture.reports, gate: restartedGate
        )
        try await restarted.reconcileAfterLaunch()
        let lease = try restartedGate.acquire()
        defer { restartedGate.release(lease) }
        #expect(try await restartedQueue.nextPending()?.id == pendingID)
        #expect(try Data(contentsOf: paths.result) == artifact)
    }

    @Test func quarantineWriteFailureStillStopsAdmission() async throws {
        let fixture = try ReliabilityFixture()
        defer { try? trashCoordinatorRoot(fixture.root) }
        let id = try enqueuedID(try await fixture.queue.enqueueResearch(
            topicID: "memory", reportDate: "2026-08-30", trigger: .runNow
        ))
        let job = try #require(try await fixture.queue.nextPending())
        let paths = try FoundationJobBuilder.create(
            request: researchRequest(id: id, root: fixture.root), jobDirectory: URL(fileURLWithPath: job.jobDirectory)
        )
        try Data("{invalid".utf8).write(to: paths.result)
        let queueFile = fixture.root.appending(path: "state/queue.json")
        try trashCoordinatorRoot(queueFile)
        try FileManager.default.createDirectory(at: queueFile, withIntermediateDirectories: false)
        await #expect(throws: EnginePersistenceError.reconciliationRequired(jobID: id)) {
            try await fixture.coordinator(runner: FakeEngineRunner(result: nil)).reconcileAfterLaunch()
        }
        #expect(throws: EngineExecutionGateError.reconciliationRequired) { try fixture.gate.acquire() }
        #expect(await fixture.queue.jobs().first?.state == .running)
    }

    @Test(arguments: [100.0, 50.0])
    func newerUnknownResendSurvivesOldSuccessReplay(secondCreationTime: TimeInterval) async throws {
        let clock = DeliveryAttemptClock(Date(timeIntervalSince1970: 100))
        let fixture = try ReliabilityFixture(clock: { clock.read() })
        defer { try? trashCoordinatorRoot(fixture.root) }
        try await fixture.indexReport()
        let firstID = try enqueuedID(try await fixture.queue.enqueueDelivery(
            runDirectory: fixture.run, topicID: "memory", reportDate: "2026-08-30", channel: .email
        ))
        let successful = fixture.coordinator(runner: FakeEngineRunner(result: deliveryResult(id: firstID, run: fixture.run)))
        _ = try await successful.executeNext(configuration: testConfiguration(root: fixture.root))
        try await successful.reconcileAfterLaunch()
        #expect(await fixture.reports.reports().first?.deliveries.first?.state == .sent)

        clock.set(Date(timeIntervalSince1970: secondCreationTime))
        let secondID = try enqueuedID(try await fixture.queue.enqueueDelivery(
            runDirectory: fixture.run, topicID: "memory", reportDate: "2026-08-30", channel: .email, allowResend: true
        ))
        await #expect(throws: EngineCommandFailure.self) {
            _ = try await fixture.coordinator(runner: FakeEngineRunner(result: nil, exitCode: 130))
                .executeNext(configuration: testConfiguration(root: fixture.root))
        }
        #expect(await fixture.reports.reports().first?.deliveries.first?.state == .unknown)
        let jobs = await fixture.queue.jobs()
        #expect(jobs.first?.state == .succeeded)
        #expect(jobs.last?.state == .deliveryUnknown)
        #expect(jobs.first?.createdAt == Date(timeIntervalSince1970: 100))
        #expect(jobs.last?.createdAt == Date(timeIntervalSince1970: secondCreationTime))
        #expect(jobs.first?.attemptCount == 1)
        #expect(jobs.last?.attemptCount == 2)
        let queue = JobQueue(
            snapshot: JobQueueSnapshotV1(jobs: Array(jobs.reversed())), store: AtomicJSONStore(root: fixture.root),
            jobsRoot: fixture.root.appending(path: "jobs")
        )
        let restarted = EngineJobCoordinator(
            runner: FakeEngineRunner(result: nil), engineURL: URL(fileURLWithPath: "/fake"),
            appSupportRoot: fixture.root, queue: queue, reports: fixture.reports, gate: EngineExecutionGate()
        )
        try await restarted.reconcileAfterLaunch()
        try await restarted.reconcileAfterLaunch()
        #expect(await fixture.reports.reports().first?.deliveries.first?.state == .unknown)
        #expect(await queue.jobs().first { $0.id == firstID }?.state == .succeeded)
        #expect(await queue.jobs().first { $0.id == secondID }?.state == .deliveryUnknown)
        await #expect(throws: JobRecordError.unknownDeliveryRequiresAcknowledgement) {
            _ = try await queue.enqueueDelivery(
                runDirectory: fixture.run, topicID: "memory", reportDate: "2026-08-30", channel: .email, allowResend: true
            )
        }
    }
}

private final class DeliveryAttemptClock: @unchecked Sendable {
    private let lock = NSLock()
    private var date: Date

    init(_ date: Date) { self.date = date }
    func read() -> Date { lock.withLock { date } }
    func set(_ date: Date) { lock.withLock { self.date = date } }
}

private func deliveryRequest(id: UUID, root: URL, run: URL) throws -> EngineRequestV1 {
    try EngineRequestV1(
        requestID: id, command: .retryDelivery, createdAt: Date(), appSupportRoot: root.path, configPath: nil,
        payload: .retryDelivery(RetryDeliveryPayloadV1(
            runDirectory: run.path, channel: .email, allowResend: false, acknowledgeUnknownOutcome: false
        ))
    )
}

private func deliveryResult(id: UUID, run: URL) -> EngineResultV1 {
    EngineResultV1(
        requestID: id, command: .retryDelivery, status: .succeeded, completedAt: Date(timeIntervalSince1970: 110),
        delivery: DeliveryResultV1(runDirectory: run.path, channel: .email, status: .sent, completedAt: Date(timeIntervalSince1970: 110))
    )
}

private func researchRequest(id: UUID, root: URL, topicID: String = "memory") throws -> EngineRequestV1 {
    try EngineRequestV1(
        requestID: id, command: .runDaily, createdAt: Date(), appSupportRoot: root.path, configPath: nil,
        payload: .runDaily(RunDailyPayloadV1(
            topicID: topicID, reportDate: "2026-08-30", limit: 1, deepLimit: 1,
            language: .chinese, modelCache: false, modelCacheLimitBytes: nil
        ))
    )
}

private func terminalError(id: UUID, code: String, stage: String) throws -> Data {
    try JSONSerialization.data(withJSONObject: [
        "schema_version": 1, "request_id": id.uuidString.lowercased(), "status": "failed",
        "stage": stage, "code": code, "message": "Stopped.", "retryable": false,
        "completed_at": "2026-08-30T00:00:00Z",
    ])
}

private struct ReliabilityFixture: Sendable {
    let root: URL
    let run: URL
    let queue: JobQueue
    let reports: ReportIndexStore
    let gate = EngineExecutionGate()

    init(clock: @escaping @Sendable () -> Date = Date.init) throws {
        root = try coordinatorRoot()
        run = root.appending(path: "workspace/runs/report")
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        try Data(#"{"topic_id":"memory"}"#.utf8).write(to: run.appending(path: "article_draft.json"))
        try Data("<html></html>".utf8).write(to: run.appending(path: "wechat.html"))
        let store = AtomicJSONStore(root: root)
        queue = JobQueue(store: store, jobsRoot: root.appending(path: "jobs"), clock: clock)
        reports = ReportIndexStore(store: store)
    }

    func result(id: UUID, command: EngineCommand = .runDaily) -> EngineResultV1 {
        EngineResultV1(
            requestID: id, command: command, status: .succeeded, completedAt: Date(timeIntervalSince1970: 20),
            report: EngineReportSummaryV1(
                runDirectory: run.path, reportDate: "2026-08-30",
                articleDraftPath: run.appending(path: "article_draft.json").path,
                reportHTMLPath: run.appending(path: "wechat.html").path,
                title: "Daily", summary: "Summary", sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1
            )
        )
    }

    func coordinator(runner: any EngineProcessRunning) -> EngineJobCoordinator {
        EngineJobCoordinator(
            runner: runner, engineURL: URL(fileURLWithPath: "/fake"), appSupportRoot: root,
            queue: queue, reports: reports, gate: gate
        )
    }

    func indexReport() async throws {
        let summary = result(id: UUID()).report!
        try await reports.upsert(ReportRecordV1(
            topicID: "memory", reportDate: summary.reportDate, runDirectory: run.path,
            articleDraftPath: summary.articleDraftPath, reportHTMLPath: summary.reportHTMLPath,
            title: summary.title, summary: summary.summary, sourceCount: 1, deepReadCount: 1,
            publishableClaimCount: 1, deliveries: [DeliveryRecordV1(channel: .email, state: .pending)], createdAt: Date()
        ))
    }
}

private actor BlockingEngineRunner: EngineProcessRunning {
    private var continuation: CheckedContinuation<EngineProcessOutcome, Never>?
    private(set) var cancellations = 0

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        await withCheckedContinuation { continuation = $0 }
    }

    func waitUntilStarted() async {
        while continuation == nil { await Task.yield() }
    }

    func cancel() async {
        cancellations += 1
        continuation?.resume(returning: EngineProcessOutcome(
            exitCode: 130, startedProcessGroup: nil, standardOutput: Data(), standardError: Data()
        ))
        continuation = nil
    }
}

private func testConfiguration(root: URL) -> AppConfigurationV1 {
    var config = AppConfigurationDefaults.make(
        workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil
    )
    config.topics = [TopicRecordV1(
        id: "memory", displayName: "Memory", researchFocus: "Memory",
        queries: ["memory"], paperQueries: ["agent memory"], reportLanguage: .chinese
    )]
    config.delivery.wechat.enabled = true
    config.delivery.email.enabled = true
    return config
}

private func enqueuedID(_ result: EnqueueResult) throws -> UUID {
    switch result { case .enqueued(let id): id; case .coalesced: throw CocoaError(.validationMissingMandatoryProperty) }
}

private func coordinatorRoot() throws -> URL {
    let url = FileManager.default.temporaryDirectory.appending(path: "engine-coordinator-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
    return url
}

private func trashCoordinatorRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
