import Foundation
import Testing
@testable import ResearchRadarAppFeature
import ResearchRadarCore

@MainActor
private final class FakeLoginItemController: LoginItemControlling {
    var status: LoginItemStatus
    private(set) var registerCount = 0
    private(set) var unregisterCount = 0

    init(status: LoginItemStatus) {
        self.status = status
    }

    func register() throws {
        registerCount += 1
        status = .enabled
    }

    func unregister() async throws {
        unregisterCount += 1
        status = .notRegistered
    }
}

@MainActor
@Suite struct LoginItemServiceTests {
    @Test func disablingLoginItemPreservesPreferencesChangedWhileAwaitingController() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "login-item-race-\(UUID())")
        defer {
            let cleanup = Process()
            cleanup.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
            cleanup.arguments = [root.path]
            do { try cleanup.run(); cleanup.waitUntilExit(); #expect(cleanup.terminationStatus == 0) }
            catch { Issue.record(error) }
        }
        let controller = SuspendedLoginItemController()
        var configuration = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        configuration.startAtLogin = true
        let store = AppStore(configuration: configuration, runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets(),
            loginItemService: LoginItemService(controller: controller))
        let disabling = Task { await store.setStartAtLogin(false) }
        await controller.waitUntilSuspended()
        let changed = store.performAction {
            try store.setUIAppearance(.dark)
            try store.setUILanguage(.english)
        }
        controller.resume()
        await disabling.value
        #expect(changed)
        #expect(store.lastErrorCode == nil)
        #expect(!store.configuration.startAtLogin)
        #expect(store.configuration.uiAppearance == .dark)
        #expect(store.configuration.uiLanguage == .english)
        let saved = try AtomicJSONStore(root: root).read(AppConfigurationV1.self, from: "config/app-config.json")
        #expect(!saved.startAtLogin)
        #expect(saved.uiAppearance == .dark)
        #expect(saved.uiLanguage == .english)
        await store.shutdown()
    }

    @Test func exposesTypedStatus() {
        let controller = FakeLoginItemController(status: .requiresApproval)
        let service = LoginItemService(controller: controller)

        #expect(service.status == .requiresApproval)
    }

    @Test func enablingAndDisablingUseTheInjectedController() async throws {
        let controller = FakeLoginItemController(status: .notRegistered)
        let service = LoginItemService(controller: controller)

        try await service.setEnabled(true)
        try await service.setEnabled(true)
        #expect(controller.registerCount == 1)
        #expect(service.status == .enabled)

        try await service.setEnabled(false)
        try await service.setEnabled(false)
        #expect(controller.unregisterCount == 1)
        #expect(service.status == .notRegistered)
    }
}

@MainActor
private final class SuspendedLoginItemController: LoginItemControlling {
    var status: LoginItemStatus = .enabled
    private var suspended: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?

    func register() throws { Issue.record("This regression must only unregister the fake login item") }

    func unregister() async throws {
        await withCheckedContinuation { continuation in
            suspended = continuation
            started?.resume()
            started = nil
        }
        status = .notRegistered
    }

    func waitUntilSuspended() async {
        if suspended != nil { return }
        await withCheckedContinuation { started = $0 }
    }

    func resume() {
        suspended?.resume()
        suspended = nil
    }
}
