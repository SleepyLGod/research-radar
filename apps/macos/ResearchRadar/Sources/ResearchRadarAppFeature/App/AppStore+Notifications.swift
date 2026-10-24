import Foundation
import ResearchRadarCore

extension AppStore {
    public var reportNotificationsEnabled: Bool { runtime.reportNotificationsEnabled == true }

    public func setReportNotificationsEnabled(_ enabled: Bool) async {
        guard !isShuttingDown, !notifications.isChangingPreference else { return }
        notifications.isChangingPreference = true
        defer { notifications.isChangingPreference = false }
        if enabled, !(await notifications.authorize()) { return }
        guard !isShuttingDown else { return }
        var candidate = runtime
        candidate.reportNotificationsEnabled = enabled
        do { try persistRuntime(candidate); notifications.clearIssue() }
        catch { notifications.preferenceSaveFailed() }
    }

    func notifyResearchCompletion(jobID: UUID) async {
        guard reportNotificationsEnabled, !isShuttingDown, !cancellationRequested,
              let job = jobs.first(where: { $0.id == jobID }) else { return }
        await notifications.notify(job: job, report: reports.first { $0.id == jobID },
            language: configuration.uiLanguage,
            shouldDeliver: { self.reportNotificationsEnabled && !self.isShuttingDown && !self.cancellationRequested })
    }

    /// Revalidate IDs against local state; no path or content from a notification is trusted.
    func openReportNotification(jobID: UUID) throws -> UUID? {
        guard !isShuttingDown,
              let job = jobs.first(where: { $0.id == jobID && $0.kind == .research }),
              JobRecordV1.terminalStates.contains(job.state),
              configuration.topics.contains(where: { $0.id == job.topicID }) else {
            throw DurableStateValidationError.invalidValue
        }
        var candidate = runtime
        candidate.selectedTopicID = job.topicID
        candidate.windowMode = .full
        try persistRuntime(candidate)
        let report = reports.first { $0.id == jobID && $0.isEffectiveDeepReport }
        selectReport(report?.id)
        return report?.id
    }
}
