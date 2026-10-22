import Foundation
import UserNotifications

/// The only adapter that accesses macOS notification authorization and presentation.
@MainActor
final class SystemReportNotificationClient: NSObject, ReportNotificationClient, UNUserNotificationCenterDelegate {
    private var onOpen: (@MainActor @Sendable (UUID) -> Void)?
    private var center: UNUserNotificationCenter { .current() }

    func activate(onOpen: @escaping @MainActor @Sendable (UUID) -> Void) {
        self.onOpen = onOpen
        center.delegate = self
    }

    func authorizationStatus() async -> ReportNotificationAuthorization {
        switch await center.notificationSettings().authorizationStatus {
        case .authorized, .provisional: .allowed
        case .notDetermined: .notDetermined
        case .denied: .denied
        @unknown default: .denied
        }
    }

    func requestAuthorization() async throws -> Bool {
        try await center.requestAuthorization(options: [.alert])
    }

    func add(_ message: ReportNotificationMessage) async throws {
        let content = UNMutableNotificationContent()
        content.title = message.title
        content.subtitle = message.subtitle
        content.body = message.body
        content.userInfo = ["job_id": message.jobID.uuidString]
        try await center.add(UNNotificationRequest(identifier: "research.\(message.jobID.uuidString)",
            content: content, trigger: nil))
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping @Sendable (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping @Sendable () -> Void) {
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier,
              let value = response.notification.request.content.userInfo["job_id"] as? String,
              let id = UUID(uuidString: value) else { completionHandler(); return }
        Task { @MainActor [weak self] in
            self?.onOpen?(id)
            completionHandler()
        }
    }
}
