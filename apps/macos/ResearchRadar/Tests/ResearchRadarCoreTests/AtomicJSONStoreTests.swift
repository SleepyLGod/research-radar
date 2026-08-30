import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct AtomicJSONStoreTests {
    @Test func JSONEncodingIsDeterministic() throws {
        let value = StoredValue(name: "radar", count: 2)

        let first = try JSONCoding.encode(value)
        let second = try JSONCoding.encode(value)

        #expect(first == second)
        #expect(String(decoding: first, as: UTF8.self) == #"{"count":2,"name":"radar"}"#)
    }

    @Test func writesAndReadsPrivateJSON() throws {
        let root = try temporaryRoot()
        defer { try? trash(root) }
        let store = AtomicJSONStore(root: root)

        try store.write(StoredValue(name: "first", count: 1), to: "state/app.json")
        try store.write(StoredValue(name: "second", count: 2), to: "state/app.json")

        let value = try store.read(StoredValue.self, from: "state/app.json")
        #expect(value == StoredValue(name: "second", count: 2))
        #expect(try permissions(at: root) == 0o700)
        #expect(try permissions(at: root.appending(path: "state")) == 0o700)
        #expect(try permissions(at: root.appending(path: "state/app.json")) == 0o600)
        #expect(try FileManager.default.contentsOfDirectory(atPath: root.appending(path: "state").path) == ["app.json"])
    }

    @Test func corruptJSONIsPreserved() throws {
        let root = try temporaryRoot()
        defer { try? trash(root) }
        let store = AtomicJSONStore(root: root)
        let original = Data("{not-json}".utf8)
        try original.write(to: root.appending(path: "state.json"))

        do {
            _ = try store.read(StoredValue.self, from: "state.json")
            Issue.record("Expected corrupt JSON to be rejected")
        } catch let error as AtomicJSONStoreError {
            guard case .corruptFile(let path) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
            #expect(path == root.appending(path: "state.json"))
        }

        #expect(try Data(contentsOf: root.appending(path: "state.json")) == original)
    }

    @Test func unsupportedSchemaIsPreservedAndRejected() throws {
        let root = try temporaryRoot()
        defer { try? trash(root) }
        let store = AtomicJSONStore(root: root)
        let snapshot = JobQueueSnapshotV1(schemaVersion: 2)
        try store.write(snapshot, to: "state/queue.json")
        let file = root.appending(path: "state/queue.json")
        let original = try Data(contentsOf: file)

        #expect(throws: AtomicJSONStoreError.unsupportedSchema(file, 2)) {
            _ = try store.read(JobQueueSnapshotV1.self, from: "state/queue.json")
        }
        #expect(try Data(contentsOf: file) == original)
    }

    @Test func semanticallyInvalidDurableStateIsPreservedAndRejected() throws {
        let root = try temporaryRoot()
        defer { try? trash(root) }
        let store = AtomicJSONStore(root: root)
        let invalid = ScheduleSnapshotV1(schedules: [
            DailyScheduleV1(topicID: "memory", hour: 25, minute: 0),
        ])
        try store.write(invalid, to: "state/schedules.json")
        let file = root.appending(path: "state/schedules.json")
        let original = try Data(contentsOf: file)

        #expect(throws: AtomicJSONStoreError.corruptFile(file)) {
            _ = try store.read(ScheduleSnapshotV1.self, from: "state/schedules.json")
        }
        #expect(try Data(contentsOf: file) == original)
    }

    @Test func rejectsPathsOutsideRoot() throws {
        let root = try temporaryRoot()
        defer { try? trash(root) }
        let store = AtomicJSONStore(root: root)

        #expect(throws: AtomicJSONStoreError.self) {
            try store.write(StoredValue(name: "escape", count: 1), to: "../escape.json")
        }
        #expect(throws: AtomicJSONStoreError.self) {
            try store.write(StoredValue(name: "escape", count: 1), to: "/tmp/escape.json")
        }
    }

    @Test func rejectsSymlinkEscapes() throws {
        let root = try temporaryRoot()
        let outside = try temporaryRoot()
        defer {
            try? trash(root)
            try? trash(outside)
        }
        try FileManager.default.createSymbolicLink(
            at: root.appending(path: "state"),
            withDestinationURL: outside
        )
        let store = AtomicJSONStore(root: root)

        #expect(throws: AtomicJSONStoreError.self) {
            try store.write(StoredValue(name: "escape", count: 1), to: "state/app.json")
        }
        #expect(!FileManager.default.fileExists(atPath: outside.appending(path: "app.json").path))
    }
}

private struct StoredValue: Codable, Equatable {
    let name: String
    let count: Int
}

private func temporaryRoot() throws -> URL {
    let root = FileManager.default.temporaryDirectory
        .appending(path: "research-radar-json-store-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    return root
}

private func permissions(at url: URL) throws -> Int {
    let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
    return try #require(attributes[.posixPermissions] as? NSNumber).intValue
}

private func trash(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw CocoaError(.fileWriteUnknown)
    }
}
