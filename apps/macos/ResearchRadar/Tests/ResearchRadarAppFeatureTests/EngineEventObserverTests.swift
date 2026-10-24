import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@Suite struct EngineEventObserverTests {
    @Test func typedRequestSequenceValidationAndPartialLines() async throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let url = root.appending(path: "events.jsonl")
        let id = UUID()
        let observer = EngineEventObserver(eventsURL: url, requestID: id)
        #expect(try await observer.readAvailable().isEmpty)
        var bytes = Data("not-json\n".utf8)
        bytes.append(try task3Event(id: UUID(), sequence: 90))
        bytes.append(try task3Event(id: id, sequence: 0))
        bytes.append(try task3Event(id: id, sequence: 80, stage: "unknown_stage"))
        bytes.append(try task3Event(id: id, sequence: 1))
        bytes.append(try task3Event(id: id, sequence: 1, stage: "verifier"))
        let next = try task3Event(id: id, sequence: 2, stage: "deep_reading")
        bytes.append(next.prefix(next.count / 2))
        try bytes.write(to: url)
        let first = try await observer.readAvailable()
        #expect(first.map(\.sequence) == [1])
        #expect(first.first?.stage == .discovery)
        try task3Append(Data(next.dropFirst(next.count / 2)), to: url)
        #expect(try await observer.readAvailable().map(\.stage) == [.deepReading])
        #expect(try await observer.readAvailable().isEmpty)
    }

    @Test func oversizedLinesAreDiscardedWithoutLosingFollowingEvents() async throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let url = root.appending(path: "events.jsonl")
        let id = UUID()
        var data = Data(repeating: 65, count: 300_000)
        data.append(10)
        data.append(try task3Event(id: id, sequence: 5, stage: "verifier"))
        try data.write(to: url)
        let observer = EngineEventObserver(eventsURL: url, requestID: id)
        #expect(try await observer.readAvailable().map(\.sequence) == [5])
    }

    @Test func stopDrainsAndDoesNotObserveIdleWrites() async throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let url = root.appending(path: "events.jsonl")
        let id = UUID()
        let recorder = Task3EventRecorder()
        let observer = EngineEventObserver(eventsURL: url, requestID: id)
        await observer.start(onEvent: { await recorder.add($0) }, onFailure: { await recorder.failed() })
        try task3Event(id: id, sequence: 1).write(to: url)
        await observer.stop()
        #expect(await recorder.sequences == [1])
        #expect(await recorder.failures == 0)
        #expect(await observer.isObserving == false)
        try task3Append(task3Event(id: id, sequence: 2), to: url)
        try await Task.sleep(for: .milliseconds(150))
        #expect(await recorder.sequences == [1])
    }
}

actor Task3EventRecorder {
    private(set) var sequences: [Int] = []
    private(set) var failures = 0
    func add(_ event: EngineEventV1) { sequences.append(event.sequence) }
    func failed() { failures += 1 }
}

func task3Event(id: UUID, sequence: Int, stage: String = "discovery", type: String = "stage_changed") throws -> Data {
    var data = try JSONSerialization.data(withJSONObject: [
        "schema_version": 1, "sequence": sequence, "request_id": id.uuidString,
        "emitted_at": "2026-09-19T00:00:00Z", "type": type, "stage": stage,
        "status": "running", "message": "secret raw provider error", "completed": NSNull(),
        "total": NSNull(), "delivery_channel": NSNull(), "run_dir": NSNull(), "error": NSNull()
    ])
    data.append(10)
    return data
}

func task3Append(_ data: Data, to url: URL) throws {
    let handle = try FileHandle(forWritingTo: url)
    defer { try? handle.close() }
    try handle.seekToEnd(); try handle.write(contentsOf: data)
}
