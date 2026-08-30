import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct StorageUsageServiceTests {
    @Test func measuresOnDemandAndClearsOnlyModelCache() throws {
        let root = try temporaryRoot()
        defer { try? trashRoot(root) }
        let cache = root.appending(path: "workspace/cache/model_calls", directoryHint: .isDirectory)
        let reports = root.appending(path: "workspace/runs/report", directoryHint: .isDirectory)
        let history = root.appending(path: "workspace/data/source_history", directoryHint: .isDirectory)
        let jobs = root.appending(path: "jobs/failure", directoryHint: .isDirectory)
        for directory in [cache, reports, history, jobs] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
        try Data(repeating: 1, count: 10).write(to: cache.appending(path: "cache.json"))
        try Data(repeating: 1, count: 5).write(to: cache.appending(path: ".hidden-cache"))
        try Data(repeating: 2, count: 20).write(to: reports.appending(path: "report.html"))
        try Data(repeating: 3, count: 30).write(to: history.appending(path: "memory.jsonl"))
        try Data(repeating: 4, count: 40).write(to: jobs.appending(path: "stderr.log"))
        let reportBytes = try Data(contentsOf: reports.appending(path: "report.html"))
        let historyBytes = try Data(contentsOf: history.appending(path: "memory.jsonl"))
        let service = StorageUsageService(appSupportRoot: root) {
            Date(timeIntervalSince1970: 100)
        }

        let before = try service.snapshot()
        #expect(before.modelCacheBytes == 15)
        #expect(before.reportsBytes == 20)
        #expect(before.jobDiagnosticsBytes == 40)

        let after = try service.clearModelCache()
        #expect(after.modelCacheBytes == 0)
        #expect(try Data(contentsOf: reports.appending(path: "report.html")) == reportBytes)
        #expect(try Data(contentsOf: history.appending(path: "memory.jsonl")) == historyBytes)
    }

    @Test func rejectsSymlinkInsideMeasuredStorage() throws {
        let root = try temporaryRoot()
        let outside = try temporaryRoot()
        defer { try? trashRoot(root); try? trashRoot(outside) }
        let cache = root.appending(path: "workspace/cache/model_calls", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        try Data("outside".utf8).write(to: outside.appending(path: "secret"))
        try FileManager.default.createSymbolicLink(
            at: cache.appending(path: "escape"), withDestinationURL: outside.appending(path: "secret")
        )

        #expect(throws: StorageUsageError.self) {
            _ = try StorageUsageService(appSupportRoot: root).snapshot()
        }
    }
}

private func temporaryRoot() throws -> URL {
    let url = FileManager.default.temporaryDirectory.appending(path: "storage-usage-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
    return url
}

private func trashRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
