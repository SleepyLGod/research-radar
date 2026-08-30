import Foundation

public enum LegacyStateMigrationError: Error, Equatable, Sendable {
    case invalidLegacyRoot
    case destinationNotEmpty
    case invalidHistoryFile(URL)
    case invalidHistoryRow(URL, Int)
    case copyFailed
}

public struct ImportSummary: Equatable, Sendable {
    public let sourceFileCount: Int
    public let rowCount: Int

    public init(sourceFileCount: Int, rowCount: Int) {
        self.sourceFileCount = sourceFileCount
        self.rowCount = rowCount
    }
}

public struct LegacyStateMigrationService: Sendable {
    private static let labelPrefix = "ai.research-radar.daily-draft."

    public init() {}

    public func legacyScheduleTopics(launchAgentsDirectory: URL) throws -> Set<String> {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: launchAgentsDirectory,
            includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey]
        ) else { return [] }
        return Set(files.compactMap(validatedScheduleTopic))
    }

    public func importSourceHistory(
        from legacyRoot: URL,
        to workspaceRoot: URL
    ) throws -> ImportSummary {
        let manager = FileManager.default
        let legacy = legacyRoot.standardizedFileURL
        let history = legacy.appending(path: "data/source_history", directoryHint: .isDirectory)
        var isDirectory: ObjCBool = false
        guard manager.fileExists(atPath: history.path, isDirectory: &isDirectory) else {
            return ImportSummary(sourceFileCount: 0, rowCount: 0)
        }
        guard isDirectory.boolValue, !isSymbolicLink(history) else {
            throw LegacyStateMigrationError.invalidLegacyRoot
        }
        let destination = workspaceRoot
            .appending(path: "data/source_history", directoryHint: .isDirectory)
        if manager.fileExists(atPath: destination.path) {
            let existing = try manager.contentsOfDirectory(atPath: destination.path)
            guard existing.isEmpty else {
                throw LegacyStateMigrationError.destinationNotEmpty
            }
        }

        let files = try manager.contentsOfDirectory(
            at: history,
            includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey]
        ).filter { $0.pathExtension == "jsonl" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        var validated: [(URL, Data, Int)] = []
        for file in files {
            guard !isSymbolicLink(file), isRegularFile(file) else {
                throw LegacyStateMigrationError.invalidHistoryFile(file)
            }
            let data = try Data(contentsOf: file)
            let lines = String(decoding: data, as: UTF8.self)
                .split(separator: "\n", omittingEmptySubsequences: true)
            for (index, line) in lines.enumerated() {
                let object = try? JSONSerialization.jsonObject(with: Data(line.utf8))
                guard object is [String: Any] else {
                    throw LegacyStateMigrationError.invalidHistoryRow(file, index + 1)
                }
            }
            validated.append((file, data, lines.count))
        }
        guard !validated.isEmpty else { return ImportSummary(sourceFileCount: 0, rowCount: 0) }
        let destinationParent = destination.deletingLastPathComponent()
        let staging = destinationParent.appending(
            path: ".source-history-import-\(UUID().uuidString)",
            directoryHint: .isDirectory
        )
        let backup = destinationParent.appending(
            path: ".source-history-backup-\(UUID().uuidString)",
            directoryHint: .isDirectory
        )
        do {
            try manager.createDirectory(
                at: staging,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try manager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: workspaceRoot.path)
            for (source, data, _) in validated {
                let target = staging.appending(path: source.lastPathComponent)
                try data.write(to: target, options: [.atomic])
                try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
            }
            if manager.fileExists(atPath: destination.path) {
                try manager.moveItem(at: destination, to: backup)
            }
            do {
                try manager.moveItem(at: staging, to: destination)
            } catch {
                if manager.fileExists(atPath: backup.path) {
                    try? manager.moveItem(at: backup, to: destination)
                }
                throw error
            }
            try manager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: destination.path)
            if manager.fileExists(atPath: backup.path) {
                try? moveToTrash(backup)
            }
        } catch {
            if manager.fileExists(atPath: staging.path) {
                try? moveToTrash(staging)
            }
            throw LegacyStateMigrationError.copyFailed
        }
        return ImportSummary(
            sourceFileCount: validated.count,
            rowCount: validated.reduce(0) { $0 + $1.2 }
        )
    }

    private func validatedScheduleTopic(_ url: URL) -> String? {
        guard url.pathExtension == "plist", !isSymbolicLink(url), isRegularFile(url),
              let data = try? Data(contentsOf: url),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil),
              let values = plist as? [String: Any],
              let label = values["Label"] as? String,
              label.hasPrefix(Self.labelPrefix)
        else { return nil }
        let topic = String(label.dropFirst(Self.labelPrefix.count))
        guard url.deletingPathExtension().lastPathComponent == label,
              topic.range(of: #"^[a-z0-9]+(?:-[a-z0-9]+)*$"#, options: .regularExpression) != nil
        else { return nil }
        return topic
    }

    private func isSymbolicLink(_ url: URL) -> Bool {
        (try? FileManager.default.destinationOfSymbolicLink(atPath: url.path)) != nil
    }

    private func isRegularFile(_ url: URL) -> Bool {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path) else {
            return false
        }
        return attributes[.type] as? FileAttributeType == .typeRegular
    }

    private func moveToTrash(_ url: URL) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
        process.arguments = [url.path]
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw LegacyStateMigrationError.copyFailed
        }
    }
}
