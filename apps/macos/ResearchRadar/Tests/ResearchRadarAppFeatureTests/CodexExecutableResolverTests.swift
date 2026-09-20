import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct CodexExecutableResolverTests {
    @Test(arguments: ["ChatGPT.app", "Codex.app"])
    func discoversUserInstalledAppWithoutLaunchingIt(app: String) throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "codex-app-\(UUID())")
        defer { try? trashResolverRoot(root) }
        let executable = root.appending(path: "Applications/\(app)/Contents/Resources/codex")
        try FileManager.default.createDirectory(at: executable.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/sh\nexit 99\n".utf8).write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        let resolved = CodexExecutableResolver(systemExecutableDirectories: [], systemApplicationDirectories: [])
            .resolve(savedPath: nil, environmentPath: nil, homeDirectory: root)
        #expect(resolved == executable.resolvingSymlinksInPath())
    }

    @Test func installedAppFallbackDoesNotReplaceValidCustomExecutable() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "codex-system-app-\(UUID())")
        defer { try? trashResolverRoot(root) }
        let apps = root.appending(path: "SystemApplications")
        let executable = apps.appending(path: "ChatGPT.app/Contents/Resources/codex")
        try FileManager.default.createDirectory(at: executable.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/sh\nexit 99\n".utf8).write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        let custom = root.appending(path: "custom-codex")
        try Data("#!/bin/sh\nexit 99\n".utf8).write(to: custom)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: custom.path)
        let resolver = CodexExecutableResolver(systemExecutableDirectories: [], systemApplicationDirectories: [apps])
        #expect(resolver.resolve(savedPath: custom.path, environmentPath: nil, homeDirectory: root) == custom.resolvingSymlinksInPath())
        #expect(resolver.resolve(savedPath: "/nonexistent/custom-codex", environmentPath: nil, homeDirectory: root) == executable.resolvingSymlinksInPath())
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: executable.path)
        #expect(resolver.resolve(savedPath: nil, environmentPath: nil, homeDirectory: root) == nil)
        #expect(resolver.resolve(savedPath: root.path, environmentPath: nil, homeDirectory: root) == nil)
    }

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

        let resolved = CodexExecutableResolver(systemExecutableDirectories: [], systemApplicationDirectories: []).resolve(
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
