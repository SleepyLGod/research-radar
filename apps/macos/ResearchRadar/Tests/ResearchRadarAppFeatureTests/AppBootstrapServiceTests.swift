import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@MainActor @Suite struct AppBootstrapServiceTests {
    @Test func existingConfigurationMigratesOnlyLegacyFlashRoutesOnDisk() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "app-bootstrap-\(UUID().uuidString)")
        defer { try? trashBootstrapRoot(root) }
        let persistence = AtomicJSONStore(root: root)
        var saved = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        saved.routes[0].model = "deepseek-v4-flash"
        saved.routes[1].model = "custom-model"
        try persistence.write(saved, to: "config/app-config.json")
        let service = AppBootstrapService(appSupportRoot: root, launchAgentsDirectory: root.appending(path: "missing-LaunchAgents"))
        let loaded = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        #expect(loaded.configuration.routes[0].model == "deepseek-flash")
        #expect(loaded.configuration.routes[1].model == "custom-model")
        let stored = try persistence.read(AppConfigurationV1.self, from: "config/app-config.json")
        #expect(stored == loaded.configuration)
        let bytes = try Data(contentsOf: root.appending(path: "config/app-config.json"))
        _ = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        #expect(try Data(contentsOf: root.appending(path: "config/app-config.json")) == bytes)
    }

    @Test func firstLaunchCreatesTypedPrivateStateAndSecondLaunchReusesIt() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "app-bootstrap-\(UUID().uuidString)")
        defer { try? trashBootstrapRoot(root) }
        let service = AppBootstrapService(appSupportRoot: root, launchAgentsDirectory: root.appending(path: "missing-LaunchAgents"))

        let first = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        #expect(first.legacyScheduleTopics.isEmpty)
        try first.setUILanguage(.simplifiedChinese)
        let second = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))

        #expect(second.configuration.uiLanguage == .simplifiedChinese)
        let attributes = try FileManager.default.attributesOfItem(
            atPath: root.appending(path: "config/app-config.json").path
        )
        #expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
    }

    @Test func corruptStateStopsBootstrapWithoutOverwritingBytes() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "app-bootstrap-\(UUID().uuidString)")
        defer { try? trashBootstrapRoot(root) }
        let service = AppBootstrapService(appSupportRoot: root, launchAgentsDirectory: root.appending(path: "missing-LaunchAgents"))
        _ = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        let state = root.appending(path: "state/queue.json")
        let corrupt = Data("broken".utf8); try corrupt.write(to: state)

        #expect(throws: AtomicJSONStoreError.self) {
            _ = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        }
        #expect(try Data(contentsOf: state) == corrupt)
    }

    @Test(arguments: [false, true])
    func inconclusiveLegacyInspectionStopsBootstrapWithoutWritingState(unreadable: Bool) throws {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath()
            .appending(path: "app-bootstrap-\(UUID().uuidString)")
        defer { try? trashBootstrapRoot(root) }
        let launchAgents = root.appending(path: "LaunchAgents")
        let appRoot = root.appending(path: "AppSupport")
        try FileManager.default.createDirectory(at: launchAgents, withIntermediateDirectories: true)
        let candidate = launchAgents.appending(path: "ai.research-radar.daily-draft.memory.plist")
        let bytes = Data("malformed plist".utf8)
        try bytes.write(to: candidate)
        if unreadable {
            try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: launchAgents.path)
        }
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: launchAgents.path) }
        let service = AppBootstrapService(appSupportRoot: appRoot, launchAgentsDirectory: launchAgents)
        do {
            _ = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
            Issue.record("Bootstrap continued despite inconclusive scheduler inspection")
        } catch LegacyStateMigrationError.scheduleInspectionFailed(let actual) {
            let expected = unreadable ? launchAgents : candidate
            #expect(actual.resolvingSymlinksInPath().path == expected.resolvingSymlinksInPath().path)
        }
        #expect(!FileManager.default.fileExists(atPath: appRoot.path))
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: launchAgents.path)
        #expect(try Data(contentsOf: candidate) == bytes)
    }

    @Test func validatedLegacyConflictReachesAppStore() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "app-bootstrap-\(UUID().uuidString)")
        defer { try? trashBootstrapRoot(root) }
        let launchAgents = root.appending(path: "LaunchAgents")
        try FileManager.default.createDirectory(at: launchAgents, withIntermediateDirectories: true)
        let label = "ai.research-radar.daily-draft.memory"
        try PropertyListSerialization.data(fromPropertyList: ["Label": label], format: .xml, options: 0)
            .write(to: launchAgents.appending(path: label + ".plist"))
        let service = AppBootstrapService(appSupportRoot: root.appending(path: "AppSupport"), launchAgentsDirectory: launchAgents)
        let store = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        #expect(store.legacyScheduleTopics == ["memory"])
    }
}

private func trashBootstrapRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
