import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct LegacyStateMigrationServiceTests {
    @Test func detectsOnlyValidatedResearchRadarDailyDraftPlists() throws {
        let root = try testDirectory()
        defer { try? trash(root) }
        try writePlist(
            label: "ai.research-radar.daily-draft.agent-memory",
            to: root.appending(path: "ai.research-radar.daily-draft.agent-memory.plist")
        )
        try writePlist(
            label: "com.example.unrelated",
            to: root.appending(path: "com.example.unrelated.plist")
        )
        try writePlist(
            label: "ai.research-radar.daily-draft.wrong-label",
            to: root.appending(path: "ai.research-radar.daily-draft.llm-inference.plist")
        )

        let topics = try LegacyStateMigrationService().legacyScheduleTopics(
            launchAgentsDirectory: root
        )

        #expect(topics == ["agent-memory"])
    }

    @Test func importsOnlyValidatedSourceHistoryWithoutMutatingSource() throws {
        let root = try testDirectory()
        defer { try? trash(root) }
        let legacyRoot = root.appending(path: "legacy", directoryHint: .isDirectory)
        let historyRoot = legacyRoot.appending(path: "data/source_history", directoryHint: .isDirectory)
        let workspaceRoot = root.appending(path: "workspace", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: historyRoot, withIntermediateDirectories: true)
        let source = historyRoot.appending(path: "agent-memory.jsonl")
        let sourceData = Data("{\"paper\":1}\n{\"paper\":2}\n".utf8)
        try sourceData.write(to: source)
        try Data("do-not-copy".utf8).write(to: legacyRoot.appending(path: "config.yaml"))
        try FileManager.default.createDirectory(
            at: legacyRoot.appending(path: "runs", directoryHint: .isDirectory),
            withIntermediateDirectories: true
        )

        let summary = try LegacyStateMigrationService().importSourceHistory(
            from: legacyRoot,
            to: workspaceRoot
        )

        #expect(summary == ImportSummary(sourceFileCount: 1, rowCount: 2))
        #expect(try Data(contentsOf: source) == sourceData)
        #expect(
            try Data(contentsOf: workspaceRoot.appending(path: "data/source_history/agent-memory.jsonl"))
                == sourceData
        )
        #expect(!FileManager.default.fileExists(atPath: workspaceRoot.appending(path: "config.yaml").path))
        #expect(!FileManager.default.fileExists(atPath: workspaceRoot.appending(path: "runs").path))
        let attributes = try FileManager.default.attributesOfItem(
            atPath: workspaceRoot.appending(path: "data/source_history/agent-memory.jsonl").path
        )
        #expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
    }

    @Test func rejectsMalformedHistoryAndLeavesDestinationEmpty() throws {
        let roots = try migrationRoots()
        defer { try? trash(roots.root) }
        try Data("{\"valid\":true}\nnot-json\n".utf8).write(
            to: roots.history.appending(path: "agent-memory.jsonl")
        )

        #expect(throws: LegacyStateMigrationError.self) {
            try LegacyStateMigrationService().importSourceHistory(
                from: roots.legacy,
                to: roots.workspace
            )
        }
        #expect(!FileManager.default.fileExists(atPath: roots.workspace.path))
    }

    @Test func rejectsSymlinkedHistoryFile() throws {
        let roots = try migrationRoots()
        defer { try? trash(roots.root) }
        let outside = roots.root.appending(path: "outside.jsonl")
        try Data("{\"paper\":1}\n".utf8).write(to: outside)
        try FileManager.default.createSymbolicLink(
            at: roots.history.appending(path: "agent-memory.jsonl"),
            withDestinationURL: outside
        )

        #expect(throws: LegacyStateMigrationError.self) {
            try LegacyStateMigrationService().importSourceHistory(
                from: roots.legacy,
                to: roots.workspace
            )
        }
    }

    @Test func rejectsNonemptyDestinationHistory() throws {
        let roots = try migrationRoots()
        defer { try? trash(roots.root) }
        try Data("{\"paper\":1}\n".utf8).write(
            to: roots.history.appending(path: "agent-memory.jsonl")
        )
        let destination = roots.workspace.appending(path: "data/source_history", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        try Data("{\"existing\":true}\n".utf8).write(
            to: destination.appending(path: "existing.jsonl")
        )

        #expect(throws: LegacyStateMigrationError.self) {
            try LegacyStateMigrationService().importSourceHistory(
                from: roots.legacy,
                to: roots.workspace
            )
        }
    }

    @Test func missingHistoryDirectoryIsANoOp() throws {
        let root = try testDirectory()
        defer { try? trash(root) }

        let summary = try LegacyStateMigrationService().importSourceHistory(
            from: root.appending(path: "legacy"),
            to: root.appending(path: "workspace")
        )

        #expect(summary == ImportSummary(sourceFileCount: 0, rowCount: 0))
        #expect(!FileManager.default.fileExists(atPath: root.appending(path: "workspace").path))
    }
}

private func migrationRoots() throws -> (
    root: URL,
    legacy: URL,
    history: URL,
    workspace: URL
) {
    let root = try testDirectory()
    let legacy = root.appending(path: "legacy", directoryHint: .isDirectory)
    let history = legacy.appending(path: "data/source_history", directoryHint: .isDirectory)
    try FileManager.default.createDirectory(at: history, withIntermediateDirectories: true)
    return (root, legacy, history, root.appending(path: "workspace", directoryHint: .isDirectory))
}

private func testDirectory() throws -> URL {
    let url = FileManager.default.temporaryDirectory
        .appending(path: "research-radar-service-tests-\(UUID().uuidString)")
    try FileManager.default.createDirectory(
        at: url,
        withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
    )
    return url
}

private func writePlist(label: String, to url: URL) throws {
    let data = try PropertyListSerialization.data(
        fromPropertyList: ["Label": label],
        format: .xml,
        options: 0
    )
    try data.write(to: url)
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
