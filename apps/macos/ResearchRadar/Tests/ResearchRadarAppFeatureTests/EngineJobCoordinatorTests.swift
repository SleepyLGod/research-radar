import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

private actor FakeEngineRunner: EngineProcessRunning {
    let result: EngineResultV1?
    let exitCode: Int32

    init(result: EngineResultV1?, exitCode: Int32 = 0) {
        self.result = result; self.exitCode = exitCode
    }

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        if let result, let resultIndex = arguments.firstIndex(of: "--result") {
            try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[resultIndex + 1]))
        }
        return EngineProcessOutcome(
            exitCode: exitCode, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data()
        )
    }

    func cancel() async {}
}

@Suite struct EngineJobCoordinatorTests {
    @Test func successfulDailyPersistsReportBeforeIndependentDeliveryJobs() async throws {
        let root = try coordinatorRoot()
        defer { try? trashCoordinatorRoot(root) }
        let run = root.appending(path: "workspace/runs/report", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let draft = run.appending(path: "article_draft.json")
        let html = run.appending(path: "wechat.html")
        try Data("{}".utf8).write(to: draft); try Data("<html></html>".utf8).write(to: html)
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
            appSupportRoot: root, queue: queue, reports: reports
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
            queue: queue, reports: reports
        )

        await #expect(throws: EngineJobCoordinatorError.self) {
            _ = try await coordinator.executeNext(configuration: testConfiguration(root: root))
        }

        #expect(await reports.reports().isEmpty)
        #expect(await queue.jobs().count == 1)
        #expect(await queue.jobs().first?.state == .failed)
    }

    @Test func launchReconciliationCompletesAResultWrittenBeforeTheAppCrashed() async throws {
        let root = try coordinatorRoot()
        defer { try? trashCoordinatorRoot(root) }
        let run = root.appending(path: "workspace/runs/report", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let draft = run.appending(path: "article_draft.json")
        let html = run.appending(path: "wechat.html")
        try Data("{}".utf8).write(to: draft)
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
            appSupportRoot: root, queue: queue, reports: reports
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
            reports: reports
        )

        try await coordinator.reconcileAfterLaunch()

        let deliveryJobs = await queue.jobs().filter { $0.kind == .delivery }
        #expect(deliveryJobs.count == 1)
        #expect(deliveryJobs.first?.deliveryChannel == .email)
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
