import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@MainActor @Suite struct Task3AEventIntegrationTests {
    @Test func liveStagesReachStoreAndDiskButCompletedEventIsNotSuccess() async throws {
        let root = try task3Root(); defer { task3Trash(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        config.topics = [TopicRecordV1(id: "one", displayName: "One", researchFocus: "One", queries: ["one"], paperQueries: ["one"], reportLanguage: .english)]
        let runner = Task3LiveRunner()
        let store = AppStore(configuration: config, runtime: .init(selectedTopicID: "one", updatedAt: Date()),
            appSupportRoot: root, engineURL: URL(fileURLWithPath: "/fake/engine"), runner: runner, secretStore: AdmissionSecrets())
        let work = Task { await store.runNow(topicID: "one", reportDate: "2026-09-19") }
        await runner.waitForStart()
        let sawReading = await waitForStage(store, .reading)
        #expect(sawReading)
        #expect(store.todayPresentation.status == .running)
        let disk = try AtomicJSONStore(root: root).read(JobQueueSnapshotV1.self, from: "state/queue.json")
        #expect(disk.jobs.first?.stage == .deepReading)
        #expect(store.todayPresentation.activeJob?.error == nil)
        #expect(store.todayPresentation.activeJob?.jobDirectory == "")
        let before = try Data(contentsOf: root.appending(path: "state/queue.json"))
        let timestamp = Date(timeIntervalSince1970: 100)
        try FileManager.default.setAttributes([.modificationDate: timestamp], ofItemAtPath: root.appending(path: "state/queue.json").path)
        try await runner.emit(sequence: 2, stage: "deep_reading", type: "progress")
        try await Task.sleep(for: .milliseconds(250))
        #expect(try Data(contentsOf: root.appending(path: "state/queue.json")) == before)
        #expect(try FileManager.default.attributesOfItem(atPath: root.appending(path: "state/queue.json").path)[.modificationDate] as? Date == timestamp)
        try await runner.emit(sequence: 3, stage: "complete", type: "completed")
        await runner.finish()
        await work.value
        #expect(store.jobs.first?.state == .interrupted)
        #expect(store.reports.isEmpty)
        // With no terminal artifact, the last progress remains audit data, not a failure stage.
        #expect(store.todayPresentation.stage == nil)
        #expect(store.jobs.first?.stage == .deepReading)
        #expect(!store.isEngineRunning)
        try await runner.emit(sequence: 4, stage: "compose", type: "stage_changed")
        try await Task.sleep(for: .milliseconds(150))
        #expect(store.jobs.first?.stage == .deepReading)
    }

    private func waitForStage(_ store: AppStore, _ stage: PublicResearchStage) async -> Bool {
        for _ in 0..<100 {
            if store.todayPresentation.stage == stage { return true }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return false
    }
}

private actor Task3LiveRunner: EngineProcessRunning {
    private var eventsURL: URL?
    private var requestID: UUID?
    private var completion: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let index = try #require(arguments.firstIndex(of: "--request"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: URL(fileURLWithPath: arguments[index + 1])))
        self.eventsURL = eventsURL; requestID = request.requestID
        try task3Event(id: request.requestID, sequence: 1, stage: "deep_reading").write(to: eventsURL)
        await withCheckedContinuation { completion = $0; started?.resume(); started = nil }
        return EngineProcessOutcome(exitCode: 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
    }

    func waitForStart() async {
        if completion != nil { return }
        await withCheckedContinuation { started = $0 }
    }

    func emit(sequence: Int, stage: String, type: String) throws {
        try task3Append(task3Event(id: #require(requestID), sequence: sequence, stage: stage, type: type), to: #require(eventsURL))
    }

    func finish() { completion?.resume(); completion = nil }
    func cancel() { finish() }
}
