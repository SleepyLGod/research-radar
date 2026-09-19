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
        let service = AppBootstrapService(appSupportRoot: root)
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
        let service = AppBootstrapService(appSupportRoot: root)

        let first = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
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
        let service = AppBootstrapService(appSupportRoot: root)
        _ = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        let state = root.appending(path: "state/queue.json")
        let corrupt = Data("broken".utf8); try corrupt.write(to: state)

        #expect(throws: AtomicJSONStoreError.self) {
            _ = try service.load(engineURL: URL(fileURLWithPath: "/fake/engine"))
        }
        #expect(try Data(contentsOf: state) == corrupt)
    }
}

private func trashBootstrapRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
