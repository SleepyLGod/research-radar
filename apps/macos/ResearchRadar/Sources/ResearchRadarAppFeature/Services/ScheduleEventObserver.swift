import AppKit
import Foundation

/// Recomputes one-shot schedules when wall-clock assumptions change.
@MainActor
public final class ScheduleEventObserver {
    private let notificationCenter: NotificationCenter
    private let workspaceNotificationCenter: NotificationCenter
    private let refresh: @MainActor () -> Void
    private var tokens: [NSObjectProtocol] = []

    public init(
        notificationCenter: NotificationCenter = .default,
        workspaceNotificationCenter: NotificationCenter = NSWorkspace.shared.notificationCenter,
        refresh: @escaping @MainActor () -> Void
    ) {
        self.notificationCenter = notificationCenter
        self.workspaceNotificationCenter = workspaceNotificationCenter
        self.refresh = refresh
    }

    public func start() {
        guard tokens.isEmpty else { return }
        tokens.append(notificationCenter.addObserver(
            forName: NSNotification.Name.NSSystemClockDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        })
        tokens.append(notificationCenter.addObserver(
            forName: NSNotification.Name.NSSystemTimeZoneDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        })
        tokens.append(workspaceNotificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        })
    }

    public func stop() {
        for token in tokens {
            notificationCenter.removeObserver(token)
            workspaceNotificationCenter.removeObserver(token)
        }
        tokens.removeAll()
    }
}
