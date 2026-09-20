import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@MainActor @Suite struct Task3APresentationTests {
    @Test func scopedSelectionNavigationAndProtectedHTML() throws {
        let root = try task3Root()
        defer { task3Trash(root) }
        let run = root.appending(path: "workspace/run")
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let html = run.appending(path: "report.html")
        try Data("<html>Report</html>".utf8).write(to: html)
        let old = task3Report(topic: "one", run: run, date: 1)
        let latest = task3Report(topic: "one", run: run, date: 2)
        let other = task3Report(topic: "two", run: run, date: 3)
        let ownJob = try task3Job(topic: "one", state: .running, stage: .anchorRepair)
        let otherJob = try task3Job(topic: "two", state: .failed)
        let schedule = DailyScheduleV1(topicID: "one", hour: 9, minute: 0)
        let store = task3Store(root: root, jobs: [otherJob, ownJob], reports: [latest, other, old], schedules: [schedule])
        #expect(store.latestReport?.id == latest.id)
        #expect(store.selectedTopicJobs.map(\.id) == [ownJob.id])
        #expect(store.selectedTopicReports.map(\.id) == [latest.id, old.id])
        #expect(store.selectedTopicSchedule == schedule)
        #expect(store.todayPresentation.job?.state == .running)
        #expect(store.todayPresentation.job?.stage == .reading)
        #expect(store.todayPresentation.status == .running)
        #expect(store.todayPresentation.jobs.map(\.id) == [ownJob.id])
        #expect(store.todayPresentation.nextRun != nil)
        store.selectReport(latest.id)
        #expect(store.selectedReport?.id == latest.id)
        #expect(store.selectedReportURL == html.resolvingSymlinksInPath())
        try store.setWindowMode(.full)
        try store.setWindowMode(.compact)
        #expect(store.selectedReportID == latest.id)
        #expect(store.selectedTopic?.id == "one")
        try store.selectTopic("two")
        #expect(store.latestReport?.id == other.id)
        #expect(store.selectedReport == nil)
        store.selectReport(other.id)
        #expect(store.selectedReport?.id == other.id)
        store.selectReport(UUID())
        #expect(store.selectedReportID == other.id)
    }

    @Test func reportURLRejectsMissingOutsideAndSymlinkEscapes() throws {
        let root = try task3Root()
        defer { task3Trash(root) }
        let run = root.appending(path: "workspace/run")
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let report = task3Report(topic: "one", run: run, date: 1)
        let store = task3Store(root: root, reports: [report])
        store.selectReport(report.id)
        #expect(store.selectedReportURL == nil)
        let outside = root.appending(path: "outside.html")
        try Data("outside".utf8).write(to: outside)
        try FileManager.default.createSymbolicLink(at: run.appending(path: "report.html"), withDestinationURL: outside)
        #expect(store.selectedReportURL == nil)
        let outsideReport = task3Report(topic: "one", run: root, date: 2)
        try Data("outside".utf8).write(to: root.appending(path: "report.html"))
        let outsideStore = task3Store(root: root, reports: [outsideReport])
        outsideStore.selectReport(outsideReport.id)
        #expect(outsideStore.selectedReportURL == nil)
    }

    @Test func windowModePersistsBeforeMemoryEvenWhenJobsPending() throws {
        let root = try task3Root()
        defer { task3Trash(root) }
        let store = task3Store(root: root, jobs: [try task3Job(topic: "one", state: .pending)])
        try store.setWindowMode(.full)
        #expect(store.runtime.windowMode == .full)
        #expect(try AtomicJSONStore(root: root).read(AppRuntimeStateV1.self, from: "state/app-state.json").windowMode == .full)
        let blocked = try task3Root()
        defer { task3Trash(blocked) }
        try Data("block".utf8).write(to: blocked.appending(path: "state"))
        let failedStore = task3Store(root: blocked)
        let before = failedStore.runtime
        #expect(throws: (any Error).self) { try failedStore.setWindowMode(.full) }
        #expect(failedStore.runtime == before)
    }

    @Test func exactStageMappingAndTerminalStatuses() throws {
        let mapping: [(EngineStage, ResearchStage?)] = [
            (.discovery, .discover), (.sourceGist, .discover), (.acquisition, .reading),
            (.deepReading, .reading), (.anchorRepair, .reading), (.verifier, .verifying),
            (.localization, .composing), (.compose, .composing), (.preflight, nil),
            (.topicBootstrap, nil), (.wechatDraft, nil), (.email, nil), (.complete, nil)
        ]
        for (input, expected) in mapping { #expect(ResearchStage(engineStage: input) == expected) }
        for state: JobState in [.pending, .running, .cancelling, .succeeded, .partialSuccess, .failed, .cancelled, .interrupted, .deliveryUnknown] {
            let job = try task3Job(topic: "one", state: state, stage: .compose)
            let model = JobPresentation(job: job)
            #expect(model.state == state)
            #expect(model.stage == ([.running, .cancelling, .failed, .interrupted, .cancelled].contains(state) ? .composing : nil))
        }
    }

    @Test(arguments: [JobState.failed, .interrupted, .cancelled])
    func stoppedResearchRetainsOnlyItsActualPublicStage(state: JobState) throws {
        let stages: [(EngineStage?, ResearchStage?)] = [
            (.sourceGist, .discovery), (.anchorRepair, .reading),
            (.verifier, .verification), (.localization, .composition),
            (.complete, nil), (.preflight, nil), (nil, nil)
        ]
        for (stage, expected) in stages {
            let research = try task3Job(topic: "one", state: state, stage: stage)
            let model = JobPresentation(job: research)
            #expect(model.state == state)
            #expect(model.stage == expected)
            let delivery = try JobRecordV1(kind: .delivery, topicID: "one", reportDate: "2026-09-19",
                deliveryChannel: .email, trigger: .retry, state: state, stage: stage,
                jobDirectory: "/tmp/unused", createdAt: Date())
            #expect(JobPresentation(job: delivery).stage == nil)
        }
    }

    @Test func deliveryFailureKeepsReportReadyAndPauseSuppressesNextRun() throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let report = task3Report(topic: "one", run: root.appending(path: "workspace/run"), date: 1)
        let job = try JobRecordV1(kind: .delivery, topicID: "one", reportDate: "2026-09-19",
            deliveryChannel: .email, trigger: .retry, state: .failed, jobDirectory: "/secret/path",
            runDirectory: report.runDirectory, createdAt: Date(),
            error: .init(code: "raw", message: "secret raw provider error", retryable: false))
        let store = task3Store(root: root, jobs: [job], reports: [report],
            schedules: [.init(topicID: "one", hour: 9, minute: 0)])
        #expect(store.todayPresentation.status == .partialSuccess)
        #expect(store.todayPresentation.latestReport?.id == report.id)
        #expect(store.todayPresentation.stage == nil)
        #expect(store.todayPresentation.nextRun != nil)
        try store.setSchedulesPaused(true)
        #expect(store.todayPresentation.nextRun == nil)
        #expect(store.todayPresentation.statusKey == "today.partialSuccess")
        #expect(PublicResearchStage.allCases.map(\.localizationKey) == ["stage.discover", "stage.reading", "stage.verifying", "stage.composing"])
    }

    @Test func otherActiveTopicDoesNotLeakIntoSelectedTopicStats() throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let running = try task3Job(topic: "two", state: .running, stage: .verifier)
        let store = task3Store(root: root, jobs: [running],
            reports: [task3Report(topic: "two", run: root.appending(path: "workspace/run"), date: 1)])
        #expect(store.todayPresentation.otherActiveTopicID == "two")
        #expect(store.todayPresentation.jobs.isEmpty)
        #expect(store.todayPresentation.latestReport == nil)
        #expect(store.todayPresentation.stage == nil)
        #expect(store.todayPresentation.status == .idle)
        #expect(store.engineStatusPresentation?.topicID == "two")
        #expect(store.engineStatusPresentation?.topic?.id == "two")
        #expect(store.engineStatusPresentation?.job.stage == .verification)
        try store.selectTopic("two")
        #expect(store.todayPresentation.otherActiveTopicID == nil)
        #expect(store.todayPresentation.stage == .verification)
    }
}

func task3Root() throws -> URL {
    let root = FileManager.default.temporaryDirectory.appending(path: "task3a-\(UUID())")
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return root
}

func task3Trash(_ root: URL) {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [root.path]
    do { try process.run(); process.waitUntilExit(); #expect(process.terminationStatus == 0) }
    catch { Issue.record(error) }
}

func task3Job(topic: String, state: JobState, stage: EngineStage? = nil) throws -> JobRecordV1 {
    try JobRecordV1(kind: .research, topicID: topic, reportDate: "2026-09-19", trigger: .runNow,
        state: state, stage: stage, jobDirectory: "/tmp/unused", createdAt: Date())
}

func task3Report(topic: String, run: URL, date: Double) -> ReportRecordV1 {
    ReportRecordV1(topicID: topic, reportDate: "2026-09-19", runDirectory: run.path,
        articleDraftPath: run.appending(path: "article.json").path, reportHTMLPath: run.appending(path: "report.html").path,
        title: "Report", summary: "Summary", sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1,
        deliveries: [], createdAt: Date(timeIntervalSince1970: date))
}

@MainActor func task3Store(root: URL, jobs: [JobRecordV1] = [], reports: [ReportRecordV1] = [], schedules: [DailyScheduleV1] = []) -> AppStore {
    var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
    config.topics = ["one", "two"].map { TopicRecordV1(id: $0, displayName: $0, researchFocus: $0, queries: [$0], paperQueries: [$0], reportLanguage: .english) }
    return AppStore(configuration: config, queueSnapshot: .init(jobs: jobs), scheduleSnapshot: .init(schedules: schedules),
        reportSnapshot: .init(reports: reports), runtime: .init(selectedTopicID: "one", updatedAt: Date()), appSupportRoot: root)
}
