import Foundation
import Observation
import ResearchRadarCore

public enum ReportNotificationAuthorization: Sendable { case notDetermined, allowed, denied }

public struct ReportNotificationMessage: Equatable, Sendable {
    public let jobID: UUID
    public let title: String
    public let subtitle: String
    public let body: String
}

@MainActor
public protocol ReportNotificationClient: AnyObject {
    func authorizationStatus() async -> ReportNotificationAuthorization
    func requestAuthorization() async throws -> Bool
    func add(_ message: ReportNotificationMessage) async throws
    func activate(onOpen: @escaping @MainActor @Sendable (UUID) -> Void)
}

/// Best-effort local reminders for freshly completed research, never historical replay or delivery.
@MainActor @Observable
final class NotificationService {
    enum Issue: String { case permissionDenied, permissionUnavailable, preferenceSaveFailed, submissionFailed }
    private(set) var issue: Issue?
    var isChangingPreference = false
    @ObservationIgnored private let client: any ReportNotificationClient
    @ObservationIgnored private var handledJobs: Set<UUID> = []

    init(client: any ReportNotificationClient) { self.client = client }

    func activate(onOpen: @escaping @MainActor @Sendable (UUID) -> Void) {
        client.activate(onOpen: onOpen)
    }

    /// Called only by an explicit enable action, not at startup or from task completion.
    func authorize() async -> Bool {
        issue = nil
        do {
            switch await client.authorizationStatus() {
            case .allowed: return true
            case .denied: issue = .permissionDenied; return false
            case .notDetermined:
                if try await client.requestAuthorization() { return true }
                issue = .permissionDenied
            }
        } catch { issue = .permissionUnavailable }
        return false
    }

    func preferenceSaveFailed() { issue = .preferenceSaveFailed }
    func clearIssue() { issue = nil }

    func notify(job: JobRecordV1, report: ReportRecordV1?, language: AppLanguagePreference,
        shouldDeliver: @MainActor () -> Bool) async {
        guard shouldDeliver(), job.kind == .research, !handledJobs.contains(job.id) else { return }
        let ready = [.succeeded, .partialSuccess].contains(job.state)
            && report?.id == job.id && report?.isEffectiveDeepReport == true
        guard ready || [.failed, .interrupted].contains(job.state) else { return }
        // Mark before suspension: an uncertain OS response must not cause duplicate reminders.
        handledJobs.insert(job.id)
        guard await client.authorizationStatus() == .allowed else { issue = .permissionDenied; return }
        guard shouldDeliver() else { return }
        let localization = LocalizationStore(preference: language)
        let stageKey = "failure_stage.\(job.stage?.rawValue ?? "unknown")"
        let stage = localization.text(stageKey)
        let message = ReportNotificationMessage(jobID: job.id,
            title: localization.text(ready ? "notification.ready" : "notification.failed"),
            subtitle: ready || stage == stageKey ? "" : stage,
            body: localization.text(ready ? "notification.ready_body" : "notification.failed_body"))
        do { try await client.add(message); issue = nil }
        catch { issue = .submissionFailed }
    }
}
