import Foundation
import ResearchRadarCore

public enum StorageUsageError: Error, Equatable, Sendable {
    case invalidRoot(URL)
    case symbolicLink(URL)
    case unsupportedFile(URL)
    case trashUnavailable
    case trashFailed(URL)
}

/// Measures App-owned storage on demand and clears only rebuildable model cache files.
public struct StorageUsageService: Sendable {
    private let appSupportRoot: URL
    private let clock: @Sendable () -> Date

    public init(appSupportRoot: URL, clock: @escaping @Sendable () -> Date = Date.init) {
        self.appSupportRoot = appSupportRoot.standardizedFileURL
        self.clock = clock
    }

    public func snapshot() throws -> StorageUsageSnapshot {
        let cache = try bytes(in: "workspace/cache/model_calls")
        let reports = try bytes(in: "workspace/runs")
        let diagnostics = try bytes(in: "jobs")
        return StorageUsageSnapshot(
            modelCacheBytes: cache,
            reportsBytes: reports,
            jobDiagnosticsBytes: diagnostics,
            totalBytes: try bytes(in: ""),
            measuredAt: clock()
        )
    }

    public func clearModelCache() throws -> StorageUsageSnapshot {
        let cacheRoot = try containedDirectory("workspace/cache/model_calls", allowMissing: true)
        if FileManager.default.fileExists(atPath: cacheRoot.path) {
            // Validate the entire tree before moving any entry. Never trash task directories.
            let children = try regularFiles(in: cacheRoot)
            guard FileManager.default.isExecutableFile(atPath: "/usr/bin/trash") else {
                throw StorageUsageError.trashUnavailable
            }
            for child in children {
                try requireContained(child, in: cacheRoot)
                let values = try child.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey])
                guard values.isSymbolicLink != true else { throw StorageUsageError.symbolicLink(child) }
                guard values.isRegularFile == true else { throw StorageUsageError.unsupportedFile(child) }
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
                process.arguments = [child.path]
                try process.run()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else {
                    throw StorageUsageError.trashFailed(child)
                }
            }
        }
        return try snapshot()
    }

    private func bytes(in relativePath: String) throws -> UInt64 {
        let directory = try containedDirectory(relativePath, allowMissing: true)
        guard FileManager.default.fileExists(atPath: directory.path) else { return 0 }
        var total: UInt64 = 0
        for item in try regularFiles(in: directory) {
            let values = try item.resourceValues(forKeys: [.fileSizeKey])
            total += UInt64(values.fileSize ?? 0)
        }
        return total
    }

    private func regularFiles(in root: URL) throws -> [URL] {
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .isDirectoryKey, .isSymbolicLinkKey]
        var pending = [root]
        var files: [URL] = []
        while let directory = pending.popLast() {
            let children = try FileManager.default.contentsOfDirectory(
                at: directory, includingPropertiesForKeys: Array(keys), options: []
            )
            for item in children {
                try requireContained(item, in: root)
                let values = try item.resourceValues(forKeys: keys)
                if values.isSymbolicLink == true { throw StorageUsageError.symbolicLink(item) }
                if values.isRegularFile == true { files.append(item) }
                else if values.isDirectory == true { pending.append(item) }
                else { throw StorageUsageError.unsupportedFile(item) }
            }
        }
        return files
    }

    private func containedDirectory(_ relativePath: String, allowMissing: Bool) throws -> URL {
        let rootValues = try appSupportRoot.resourceValues(forKeys: [.isSymbolicLinkKey])
        guard rootValues.isSymbolicLink != true else {
            throw StorageUsageError.symbolicLink(appSupportRoot)
        }
        let root = appSupportRoot.resolvingSymlinksInPath().standardizedFileURL
        let directory = root.appending(path: relativePath, directoryHint: .isDirectory).standardizedFileURL
        try requireContained(directory, in: root)
        if !allowMissing, !FileManager.default.fileExists(atPath: directory.path) {
            throw StorageUsageError.invalidRoot(directory)
        }
        return directory
    }

    private func requireContained(_ url: URL, in root: URL) throws {
        let resolved = url.resolvingSymlinksInPath().standardizedFileURL
        guard resolved.path == root.path || resolved.path.hasPrefix(root.path + "/") else {
            throw StorageUsageError.invalidRoot(url)
        }
    }
}
