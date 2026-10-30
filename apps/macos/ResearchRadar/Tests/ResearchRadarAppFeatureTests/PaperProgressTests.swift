import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@Suite struct PaperProgressTests {
    @Test func papersAreMergedByIdentityNotTitleAndNeverInventAnUntouchedPaper() throws {
        let request = UUID()
        var snapshot = PaperProgressSnapshot(requestID: request)
        #expect(snapshot.papers.isEmpty)
        snapshot.receive(try paperEvent(request, sequence: 1, status: "acquiring"))
        snapshot.receive(try paperEvent(request, sequence: 2, status: "reading"))
        snapshot.receive(try paperEvent(request, sequence: 3, status: "read"))
        snapshot.receive(try paperEvent(request, sequence: 4, sourceID: String(repeating: "b", count: 64), status: "skipped"))
        #expect(snapshot.papers.map(\.status) == [.read, .skipped])
        #expect(snapshot.papers.map(\.title) == ["Agent memory / 智能体记忆", "Agent memory / 智能体记忆"])
        // A stale event and an unrelated attempt cannot overwrite the observed result.
        snapshot.receive(try paperEvent(request, sequence: 1, status: "acquiring"))
        snapshot.receive(try paperEvent(UUID(), sequence: 100, status: "reading_failed"))
        #expect(snapshot.papers.map(\.status) == [.read, .skipped])
        #expect(PaperProgressSnapshot(requestID: UUID()).papers.isEmpty)
    }

    @Test(arguments: [JobState.cancelling, .cancelled, .interrupted, .failed, .succeeded, .partialSuccess])
    func terminalAttemptDoesNotLeaveAnActiveSpinnerOrTurnReadsIntoVerifiedClaims(state: JobState) throws {
        let request = UUID()
        var snapshot = PaperProgressSnapshot(requestID: request)
        snapshot.receive(try paperEvent(request, sequence: 1, status: "read"))
        snapshot.receive(try paperEvent(request, sequence: 2, sourceID: String(repeating: "b", count: 64), status: "reading"))
        let rows = snapshot.rows(jobState: state)
        #expect(rows[0].statusKey == "paper_progress.read")
        #expect(rows[1].statusKey == (state == .cancelling ? "paper_progress.stopping"
            : state == .cancelled ? "paper_progress.stopped" : "paper_progress.unconfirmed"))
        #expect(!rows[0].isActive && !rows[1].isActive)
        #expect(!rows.contains { $0.statusKey.contains("verified") })
    }

    @Test func perPaperFailureIsNotAnOverallAttemptFailure() throws {
        var snapshot = PaperProgressSnapshot(requestID: UUID())
        snapshot.receive(try paperEvent(snapshot.requestID, sequence: 1, status: "reading_failed"))
        let row = try #require(snapshot.rows(jobState: .running).first)
        #expect(row.isWarning)
        #expect(row.statusKey == "paper_progress.reading_failed")
        #expect(!row.isActive)
    }

    @MainActor @Test func storeScopesProgressToTopicAndCurrentResearchAttempt() throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let first = try JobRecordV1(kind: .research, topicID: "one", reportDate: "2026-10-27",
            trigger: .runNow, state: .running, jobDirectory: root.appending(path: "jobs/one").path, createdAt: Date())
        let second = try JobRecordV1(kind: .research, topicID: "two", reportDate: "2026-10-27",
            trigger: .runNow, state: .pending, jobDirectory: root.appending(path: "jobs/two").path, createdAt: Date())
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = ["one", "two"].map {
            .init(id: $0, displayName: $0, researchFocus: $0, queries: [$0], paperQueries: [$0], reportLanguage: .english)
        }
        let store = AppStore(configuration: config, queueSnapshot: .init(jobs: [first, second]),
            runtime: .init(selectedTopicID: "one", updatedAt: Date()), appSupportRoot: root, secretStore: AdmissionSecrets())
        store.receivePaperProgress(try paperEvent(first.id, sequence: 1, status: "reading"))
        #expect(store.selectedTopicPaperProgress.map(\.statusKey) == ["paper_progress.reading"])
        try store.selectTopic("two")
        #expect(store.selectedTopicPaperProgress.isEmpty)
        try store.selectTopic("one")
        try store.setWindowMode(.compact)
        try store.setWindowMode(.full)
        #expect(store.selectedTopicPaperProgress.count == 1)
        store.receivePaperProgress(try paperEvent(UUID(), sequence: 100, status: "read"))
        #expect(store.selectedTopicPaperProgress.map(\.statusKey) == ["paper_progress.reading"])
    }

    @MainActor @Test func cancellationRetainsTheAttemptAndANewAttemptStartsEmpty() async throws {
        let root = try task3Root(); defer { task3Trash(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        config.topics = [.init(id: "one", displayName: "One", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let prior = task3Report(topic: "one", run: root.appending(path: "workspace/runs/prior"), date: 1)
        let runner = CancellingPaperRunner()
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: [prior]),
            runtime: .init(selectedTopicID: "one", updatedAt: Date()), appSupportRoot: root,
            engineURL: root.appending(path: "fixture-engine"), runner: runner, secretStore: AdmissionSecrets())
        let execution = Task { await store.runSelectedTopicNow() }
        for _ in 0..<200 {
            if !store.selectedTopicPaperProgress.isEmpty { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(store.selectedTopicPaperProgress.map(\.statusKey) == ["paper_progress.reading"])
        await store.cancelActiveJob()
        #expect(store.selectedTopicPaperProgress.map(\.statusKey) == ["paper_progress.stopping"])
        try await runner.finishCancellation()
        await execution.value
        #expect(store.jobs.first?.state == .cancelled)
        #expect(store.selectedTopicPaperProgress.map(\.statusKey) == ["paper_progress.stopped"])
        #expect(store.reports.map(\.id) == [prior.id])
        let oldID = store.jobs.first?.id
        await store.enqueueRunNow(topicID: "one", reportDate: ReportDate.string(for: Date()))
        #expect(store.jobs.last?.id != oldID)
        #expect(store.jobs.last?.state == .pending)
        #expect(store.selectedTopicPaperProgress.isEmpty)
        #expect(store.reports.map(\.id) == [prior.id])
        await store.shutdown()
    }
}

actor CancellingPaperRunner: EngineProcessRunning {
    private let twoPapers: Bool
    private var requestID: UUID?
    private var errorURL: URL?
    private var continuation: CheckedContinuation<EngineProcessOutcome, Never>?

    init(twoPapers: Bool = false) { self.twoPapers = twoPapers }

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let requestIndex = try #require(arguments.firstIndex(of: "--request"))
        let errorIndex = try #require(arguments.firstIndex(of: "--error"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: URL(fileURLWithPath: arguments[requestIndex + 1])))
        requestID = request.requestID
        errorURL = URL(fileURLWithPath: arguments[errorIndex + 1])
        let events = twoPapers ? try [
            paperEvent(request.requestID, sequence: 1, status: "read",
                title: "MemConflict: Evaluating Long-Term Memory Systems Under Memory Conflicts"),
            paperEvent(request.requestID, sequence: 2, sourceID: String(repeating: "b", count: 64),
                status: "reading", title: "MemGuide: Intent-Driven Memory Selection for Goal-Oriented Multi-Session LLM Agents"),
        ] : [try paperEvent(request.requestID, sequence: 1)]
        var data = Data()
        for event in events { data.append(try EngineProtocolCodec.encode(event)); data.append(10) }
        try data.write(to: eventsURL)
        return await withCheckedContinuation { continuation = $0 }
    }

    func cancel() async {}

    func finishCancellation() throws {
        let id = try #require(requestID), url = try #require(errorURL)
        try JSONSerialization.data(withJSONObject: [
            "schema_version": 1, "request_id": id.uuidString, "status": "failed", "stage": "deep_reading",
            "code": "cancelled", "message": "Stopped.", "retryable": false,
            "completed_at": "2026-10-27T09:00:00Z",
        ]).write(to: url)
        continuation?.resume(returning: .init(exitCode: 130, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data()))
        continuation = nil
    }
}

func paperEvent(_ requestID: UUID, sequence: Int, sourceID: String? = nil,
                status: String = "reading", title: String? = nil) throws -> EngineEventV1 {
    let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .deletingLastPathComponent().appending(path: "Fixtures/Protocol/paper-progress-event.json")
    var object = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: fixture)) as? [String: Any])
    object["request_id"] = requestID.uuidString
    object["sequence"] = sequence
    var paper = try #require(object["paper"] as? [String: String])
    paper["status"] = status
    if let sourceID { paper["source_id"] = sourceID }
    if let title { paper["title"] = title }
    object["paper"] = paper
    object["stage"] = ["reading", "read", "reading_failed"].contains(status) ? "deep_reading" : "acquisition"
    return try EngineProtocolCodec.decodeEvent(JSONSerialization.data(withJSONObject: object))
}
