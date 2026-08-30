import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct CodexExecutableResolverTests {
    @Test func savedExecutableWinsAndSymlinksResolve() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "codex-resolver-\(UUID().uuidString)")
        defer { try? trashResolverRoot(root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        let executable = root.appending(path: "real-codex")
        #expect(FileManager.default.createFile(atPath: executable.path, contents: Data("#!/bin/sh\n".utf8)))
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        let link = root.appending(path: "codex")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: executable)

        let resolved = CodexExecutableResolver().resolve(
            savedPath: link.path, environmentPath: nil, homeDirectory: root
        )

        #expect(resolved == executable)
    }

    @Test func relativePathEntriesAreIgnored() throws {
        let root = FileManager.default.temporaryDirectory
            .appending(path: "codex-relative-path-\(UUID().uuidString)")
        defer { try? trashResolverRoot(root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)

        let resolved = CodexExecutableResolver().resolve(
            savedPath: nil,
            environmentPath: "relative/bin",
            homeDirectory: root
        )

        #expect(resolved == nil)
    }
}

private func trashResolverRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
