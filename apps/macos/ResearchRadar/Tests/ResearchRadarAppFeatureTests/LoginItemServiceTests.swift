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
