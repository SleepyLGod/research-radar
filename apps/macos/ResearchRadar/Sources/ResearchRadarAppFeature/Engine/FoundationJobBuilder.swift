import Foundation
import ResearchRadarCore

public struct FoundationJobPaths: Sendable {
    public let jobDirectory: URL
    public let request: URL
    public let events: URL
    public let result: URL
    public let error: URL
}

public enum FoundationJobBuilder {
    public static func create(appSupportRoot: URL) throws -> FoundationJobPaths {
        let fileManager = FileManager.default
        try createPrivateDirectory(appSupportRoot, fileManager: fileManager)
        let jobs = appSupportRoot.appending(path: "jobs", directoryHint: .isDirectory)
        try createPrivateDirectory(jobs, fileManager: fileManager)
        let requestID = UUID()
        let job = jobs.appending(path: requestID.uuidString.lowercased(), directoryHint: .isDirectory)
        try createPrivateDirectory(job, fileManager: fileManager)

        let paths = FoundationJobPaths(
            jobDirectory: job,
            request: job.appending(path: "request.json"),
            events: job.appending(path: "events.jsonl"),
            result: job.appending(path: "result.json"),
            error: job.appending(path: "error.json")
        )
        let request = EngineRequestV1.preflight(
            requestID: requestID,
            createdAt: Date(),
            appSupportRoot: appSupportRoot,
            configPath: nil
        )
        try writePrivate(EngineProtocolCodec.encode(request), to: paths.request)
        return paths
    }

    public static func developmentRoot() throws -> URL {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appending(path: "ResearchRadar-Dev", directoryHint: .isDirectory)
    }

    private static func createPrivateDirectory(_ url: URL, fileManager: FileManager) throws {
        try fileManager.createDirectory(
            at: url,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: url.path)
    }

    private static func writePrivate(_ data: Data, to url: URL) throws {
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }
}
