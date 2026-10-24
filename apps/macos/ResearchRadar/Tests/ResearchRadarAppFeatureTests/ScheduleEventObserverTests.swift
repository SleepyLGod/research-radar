import AppKit
import Foundation
import Testing
@testable import ResearchRadarAppFeature

@MainActor
@Suite struct ScheduleEventObserverTests {
    @Test func clockTimeZoneAndWakeEventsRequestARefreshWithoutPolling() {
        let system = NotificationCenter()
        let workspace = NotificationCenter()
        var refreshCount = 0
        let observer = ScheduleEventObserver(
            notificationCenter: system,
            workspaceNotificationCenter: workspace,
            refresh: { refreshCount += 1 }
        )
        observer.start()

        system.post(name: NSNotification.Name.NSSystemClockDidChange, object: nil)
        system.post(name: NSNotification.Name.NSSystemTimeZoneDidChange, object: nil)
        workspace.post(name: NSWorkspace.didWakeNotification, object: nil)

        #expect(refreshCount == 3)
        observer.stop()
        system.post(name: NSNotification.Name.NSSystemClockDidChange, object: nil)
        #expect(refreshCount == 3)
    }
}
