import ResearchRadarCore
import ServiceManagement

@MainActor
public protocol LoginItemControlling: AnyObject {
    var status: LoginItemStatus { get }
    func register() throws
    func unregister() async throws
}

@MainActor
public final class MainAppLoginItemController: LoginItemControlling {
    private let service: SMAppService

    public init(service: SMAppService = .mainApp) {
        self.service = service
    }

    public var status: LoginItemStatus {
        switch service.status {
        case .notRegistered: .notRegistered
        case .enabled: .enabled
        case .requiresApproval: .requiresApproval
        case .notFound: .unavailable
        @unknown default: .unavailable
        }
    }

    public func register() throws { try service.register() }
    public func unregister() async throws { try await service.unregister() }
}

@MainActor
public final class LoginItemService {
    private let controller: LoginItemControlling

    public init(controller: LoginItemControlling = MainAppLoginItemController()) {
        self.controller = controller
    }

    public var status: LoginItemStatus { controller.status }

    public func setEnabled(_ enabled: Bool) async throws {
        if enabled {
            guard controller.status != .enabled else { return }
            try controller.register()
        } else {
            guard controller.status != .notRegistered else { return }
            try await controller.unregister()
        }
    }
}
