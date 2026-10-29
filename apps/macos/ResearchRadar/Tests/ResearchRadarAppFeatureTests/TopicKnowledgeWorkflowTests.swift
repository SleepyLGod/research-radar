import AppKit
import Foundation
import SwiftUI
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

private actor KnowledgeOfflineRunner: EngineProcessRunning {
    enum Mode: Sendable { case success, failure, hold, holdLedger }
    let mode: Mode
    var current: TopicKnowledgeV1?
    private var continuation: CheckedContinuation<Void, Never>?
    private var startWaiter: CheckedContinuation<Void, Never>?
    private(set) var commands: [EngineCommand] = []
    private(set) var cancelCount = 0
    private(set) var readTopics: [String] = []

    init(mode: Mode = .success, current: TopicKnowledgeV1? = nil) { self.mode = mode; self.current = current }
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let input = URL(fileURLWithPath: arguments[try #require(arguments.firstIndex(of: "--request")) + 1])
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: input))
        commands.append(request.command)
        if case .readPaperLedger(let payload) = request.payload {
            if mode == .holdLedger {
                await withCheckedContinuation { continuation in
                    self.continuation = continuation; startWaiter?.resume(); startWaiter = nil
                }
            }
            let result = EngineResultV1(requestID: request.requestID, command: request.command,
                status: .succeeded, completedAt: Date(), paperLedger: .init(topicID: payload.topicID,
                    reportIDs: payload.reports.map(\.reportID), papers: []))
            let output = URL(fileURLWithPath: arguments[try #require(arguments.firstIndex(of: "--result")) + 1])
            try EngineProtocolCodec.encode(result).write(to: output)
            return .init(exitCode: 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
        }
        let value: TopicKnowledgeV1
        if case .readTopicKnowledge(let payload) = request.payload {
            readTopics.append(payload.topicID)
            value = current ?? .init(topicID: payload.topicID, current: nil)
        } else if case .organizeTopic(let payload) = request.payload {
            if mode == .hold {
                await withCheckedContinuation { continuation in
                    self.continuation = continuation; startWaiter?.resume(); startWaiter = nil
                }
            }
            if mode == .failure || mode == .hold {
                let code = mode == .hold ? "cancelled" : "knowledge_failed"
                let errorURL = URL(fileURLWithPath: arguments[try #require(arguments.firstIndex(of: "--error")) + 1])
                try JSONSerialization.data(withJSONObject: [
                    "schema_version": 1, "request_id": request.requestID.uuidString.lowercased(),
                    "status": "failed", "stage": "knowledge", "code": code,
                    "message": "Offline organization stopped", "retryable": false,
                    "completed_at": "2026-10-28T09:00:00Z",
                ]).write(to: errorURL)
                return .init(exitCode: 1, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
            }
            value = .init(topicID: payload.topicID, current: .init(
                snapshotID: String(repeating: "a", count: 32), createdAt: "2026-10-28T09:00:00.123456+00:00",
                inputFingerprint: String(repeating: "b", count: 64), reportIDs: payload.reports.map(\.reportID),
                provider: "offline", model: "offline-model", paperCount: 2, featureCount: 4, groupCount: 1, relationCount: 1))
            current = value
        } else { throw EngineProtocolError.commandPayloadMismatch }
        let result = EngineResultV1(requestID: request.requestID, command: request.command,
            status: .succeeded, completedAt: Date(), knowledge: value)
        let output = URL(fileURLWithPath: arguments[try #require(arguments.firstIndex(of: "--result")) + 1])
        try EngineProtocolCodec.encode(result).write(to: output)
        return .init(exitCode: 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
    }
    func cancel() async { cancelCount += 1; continuation?.resume(); continuation = nil }
    func finishRead() { continuation?.resume(); continuation = nil }
    func waitForStart() async {
        if continuation != nil { return }
        await withCheckedContinuation { startWaiter = $0 }
    }
}

private struct KnowledgeNoSecrets: SecretStoring {
    func contains(account: String) throws -> Bool { false }
    func read(account: String) throws -> Data? { throw AppStoreError.invalidTopic }
    func set(_ value: Data, account: String) throws { throw AppStoreError.invalidTopic }
    func remove(account: String) throws { throw AppStoreError.invalidTopic }
}

@MainActor @Suite struct TopicKnowledgeWorkflowTests {
    @Test(arguments: [false, true])
    func organizationUsesQueueButNeverCreatesReportsDeliveriesOrNotifications(recoverRunning: Bool) async throws {
        let fixture = try KnowledgeFixture(); defer { try? fixture.trash() }
        let runner = KnowledgeOfflineRunner()
        let store = fixture.store(runner: runner)
        let prior = store.reports
        await store.organizeSelectedTopic()
        #expect(store.jobs.count == 1)
        #expect(store.jobs.first?.kind == .organization && store.jobs.first?.state == .succeeded)
        #expect(store.jobs.first?.requestedDeliveryChannels.isEmpty == true)
        #expect(store.reports == prior)
        #expect(store.topicKnowledge.current(for: "memory")?.paperCount == 2)
        #expect(await runner.commands == [.organizeTopic])
        let snapshot = try await store.readTopicKnowledge(topicID: "memory")
        #expect(snapshot.current?.paperCount == 2)
        var saved = try AtomicJSONStore(root: fixture.root).read(JobQueueSnapshotV1.self, from: "state/queue.json")
        if recoverRunning { saved.jobs[0].state = .running; saved.jobs[0].completedAt = nil }
        let reopened = fixture.store(runner: runner, jobs: saved)
        await reopened.reconcileAfterLaunch()
        #expect(reopened.jobs.first?.state == .succeeded)
        #expect(try await reopened.readTopicKnowledge(topicID: "memory") == snapshot)
        #expect(await runner.commands.filter { $0 == .organizeTopic }.count == 1)
    }

    @Test func cancellationStopsOnlyOrganizationAndKeepsPreviousKnowledge() async throws {
        let fixture = try KnowledgeFixture(); defer { try? fixture.trash() }
        let old = TopicKnowledgeV1(topicID: "memory", current: .init(
            snapshotID: String(repeating: "c", count: 32), createdAt: "2026-10-27T09:00:00Z",
            inputFingerprint: String(repeating: "d", count: 64), reportIDs: [fixture.report.id],
            provider: "offline", model: "old-model", paperCount: 1, featureCount: 2, groupCount: 1, relationCount: 0))
        let runner = KnowledgeOfflineRunner(mode: .hold, current: old)
        let store = fixture.store(runner: runner)
        let attempt = Task { await store.organizeSelectedTopic() }
        await runner.waitForStart()
        #expect(store.jobs.first?.state == .running)
        await store.organizeSelectedTopic()
        #expect(store.jobs.count == 1)
        await store.cancelActiveJob()
        await attempt.value
        #expect(await runner.cancelCount == 1)
        #expect(store.jobs.first?.state == .cancelled)
        #expect(try await store.readTopicKnowledge(topicID: "memory") == old)
        #expect(store.reports == [fixture.report])
    }

    @Test func failedOrganizationIsNotReportedAsResearchFailure() async throws {
        let fixture = try KnowledgeFixture(); defer { try? fixture.trash() }
        let store = fixture.store(runner: KnowledgeOfflineRunner(mode: .failure))
        await store.organizeSelectedTopic()
        #expect(store.jobs.first?.state == .failed)
        #expect(store.jobs.first?.error?.code == "knowledge_failed")
        #expect(store.todayPresentation.failureCode == nil)
        #expect(store.todayPresentation.latestReport?.id == fixture.report.id)
        #expect(store.reports == [fixture.report])
    }

    @Test func presentationRetainsTopicSnapshotOnReadFailureAndRejectsWrongTopic() async throws {
        let model = TopicKnowledgeModel()
        let old = TopicKnowledgeV1(topicID: "memory", current: .init(
            snapshotID: String(repeating: "e", count: 32), createdAt: "2026-10-27T09:00:00Z",
            inputFingerprint: String(repeating: "f", count: 64), reportIDs: [UUID()],
            provider: "offline", model: "offline-model", paperCount: 1, featureCount: 1, groupCount: 0, relationCount: 0))
        await model.load(topicID: "memory") { _ in old }
        await model.load(topicID: "memory") { _ in throw EngineProtocolError.invalidJSON }
        #expect(model.error(for: "memory") == "knowledge.load_failed")
        #expect(model.current(for: "memory") == old.current)
        await model.load(topicID: "other") { _ in old }
        #expect(model.error(for: "other") == "knowledge.load_failed")
        #expect(model.current(for: "other") == nil)
    }

    @Test func changedConfirmationDoesNotEnqueueAndEmptyTopicDoesNotStartEngine() async throws {
        let fixture = try KnowledgeFixture(); defer { try? fixture.trash() }
        let runner = KnowledgeOfflineRunner()
        let store = fixture.store(runner: runner)
        let changed = OrganizeTopicPayloadV1(topicID: "other", reports: [], researchQuestion: "Other", language: .english)
        await store.organizeSelectedTopic(expectedScope: changed)
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == "knowledge_confirmation_changed")
        let empty = AppStore(configuration: fixture.configuration, runtime: .init(updatedAt: Date()),
            appSupportRoot: fixture.root, engineURL: URL(fileURLWithPath: "/offline"), runner: runner,
            secretStore: KnowledgeNoSecrets())
        await empty.organizeSelectedTopic()
        #expect(empty.jobs.isEmpty && empty.lastErrorCode == "knowledge_no_material")
        #expect(await runner.commands.isEmpty)
    }

    @Test func organizationStatusIsTopicScopedAndUsesAttemptOrderWhenDatesTie() throws {
        let scope = OrganizeTopicPayloadV1(topicID: "memory", reports: [.init(reportID: UUID(),
            reportDate: "2026-10-28", runDirectory: "/tmp/run")], researchQuestion: "Memory", language: .english)
        let first = try JobRecordV1(kind: .organization, topicID: "memory", reportDate: "2026-10-28",
            trigger: .runNow, state: .succeeded, jobDirectory: "/tmp/one", createdAt: Date(timeIntervalSince1970: 0), organization: scope)
        let second = try JobRecordV1(kind: .organization, topicID: "memory", reportDate: "2026-10-28",
            trigger: .runNow, state: .failed, attemptCount: 2, jobDirectory: "/tmp/two", createdAt: first.createdAt, organization: scope)
        #expect(TopicKnowledgePresentation(topicID: "memory", jobs: [second, first]).statusKey == "knowledge.failed")
        #expect(TopicKnowledgePresentation(topicID: "other", jobs: [second, first]).statusKey == nil)
    }

    @Test func deferredWorkspaceReadWaitsForVisibleSelectedTopicAndRunsOnlyOnce() {
        let model = PaperLedgerModel()
        model.deferLoad(for: "topic-b")
        #expect(!model.takeDeferredLoad(topicID: "topic-a", visible: true))
        #expect(!model.takeDeferredLoad(topicID: "topic-b", visible: false))
        #expect(model.takeDeferredLoad(topicID: "topic-b", visible: true))
        #expect(!model.takeDeferredLoad(topicID: "topic-b", visible: true))
        model.deferLoad(for: "topic-b")
        model.deferLoad(for: "topic-c")
        #expect(!model.takeDeferredLoad(topicID: "topic-b", visible: true))
        #expect(model.takeDeferredLoad(topicID: "topic-c", visible: true))
    }

    @Test func otherTopicOrganizationNeverReplacesSelectedResearchFailureTitle() throws {
        let fixture = try KnowledgeFixture(); defer { try? fixture.trash() }
        var config = fixture.configuration
        let other = TopicRecordV1(id: "other", displayName: "Other", researchFocus: "Other question",
                                 queries: ["other"], paperQueries: ["other"], reportLanguage: .english)
        config.topics.append(other)
        let failed = try JobRecordV1(kind: .research, topicID: "memory", reportDate: "2026-10-28",
            trigger: .runNow, state: .failed, jobDirectory: "/tmp/failed", createdAt: Date(),
            error: .init(code: "research_failed", message: "Offline research failure", retryable: false))
        let scope = OrganizeTopicPayloadV1(topicID: "other", reports: [.init(reportID: UUID(),
            reportDate: "2026-10-28", runDirectory: "/tmp/other")], researchQuestion: "Other", language: .english)
        let active = try JobRecordV1(kind: .organization, topicID: "other", reportDate: "2026-10-28",
            trigger: .runNow, state: .running, jobDirectory: "/tmp/organizing", createdAt: Date(), organization: scope)
        let store = AppStore(configuration: config, queueSnapshot: .init(jobs: [failed, active]),
            runtime: .init(updatedAt: Date()), appSupportRoot: fixture.root, secretStore: KnowledgeNoSecrets())
        let view = TodayContentView(store: store, localization: LocalizationStore(preference: .english),
                                    compact: true, openReport: { _ in })
        #expect(store.engineStatusPresentation?.job.kind == .organization)
        #expect(view.statusKey == "today.failed")
    }

    @Test func nativeWorkspaceRetriesDeferredTopicAfterEngineReadFinishes() async throws {
        _ = NSApplication.shared
        let fixture = try KnowledgeFixture(); defer { try? fixture.trash() }
        var config = fixture.configuration
        config.topics.append(.init(id: "other", displayName: "Other", researchFocus: "Other",
            queries: ["other"], paperQueries: ["other"], reportLanguage: .english))
        let runner = KnowledgeOfflineRunner(mode: .holdLedger)
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: [fixture.report]),
            runtime: .init(windowMode: .full, updatedAt: Date()), appSupportRoot: fixture.root,
            engineURL: URL(fileURLWithPath: "/offline-engine"), runner: runner, secretStore: KnowledgeNoSecrets())
        let model = PaperLedgerModel()
        let host = NSHostingView(rootView: PaperLedgerView(store: store,
            localization: LocalizationStore(preference: .english), presentation: WindowPresentationState(),
            model: model, open: { _, _, _ in }))
        host.sizingOptions = []
        let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 720, height: 580),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close(); Task { await runner.finishRead() } }
        for _ in 0..<100 {
            if await runner.commands.first == .readPaperLedger { break }
            await Task.yield(); host.layoutSubtreeIfNeeded()
            try await Task.sleep(for: .milliseconds(10))
        }
        try #require(await runner.commands.first == .readPaperLedger)
        try store.selectTopic("other")
        host.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(100))
        await runner.finishRead()
        for _ in 0..<100 {
            if await runner.readTopics.contains("other"), !store.isEngineRunning { break }
            await Task.yield(); host.layoutSubtreeIfNeeded()
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(model.topicID == "other")
        #expect(model.snapshot?.topicID == "other")
        #expect(await runner.readTopics == ["other"])
        #expect(model.errorKey == nil)
    }
}

@MainActor private struct KnowledgeFixture {
    let root: URL
    let configuration: AppConfigurationV1
    let report: ReportRecordV1
    init() throws {
        root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "How is memory selected?",
            queries: ["memory"], paperQueries: ["memory papers"], reportLanguage: .chinese)]
        configuration = config
        let run = root.appending(path: "workspace/runs/saved")
        report = .init(topicID: "memory", reportDate: "2026-10-27", runDirectory: run.path,
            articleDraftPath: run.appending(path: "article_draft.json").path,
            reportHTMLPath: run.appending(path: "wechat.html").path, title: "Saved report", summary: "Existing",
            sourceCount: 3, deepReadCount: 2, publishableClaimCount: 4, deliveries: [], createdAt: Date())
    }
    func store(runner: any EngineProcessRunning, jobs: JobQueueSnapshotV1 = .init()) -> AppStore {
        AppStore(configuration: configuration, queueSnapshot: jobs, reportSnapshot: .init(reports: [report]),
            runtime: .init(updatedAt: Date()), appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/offline-engine"), runner: runner, secretStore: KnowledgeNoSecrets())
    }
    func trash() throws {
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
        process.arguments = [root.path]; try process.run(); process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
    }
}
