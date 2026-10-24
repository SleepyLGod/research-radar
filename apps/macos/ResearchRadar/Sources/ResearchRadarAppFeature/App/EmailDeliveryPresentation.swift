import Foundation
import ResearchRadarCore

enum EmailDeliveryActionError: Error, Equatable {
    case blocked(String)
    var code: String { switch self { case .blocked(let code): code } }
}

/// A confirmation captures the exact report, saved destination and prior attempts shown to the user.
struct EmailSendConfirmation: Equatable, Identifiable {
    let report: ReportRecordV1
    let settings: EmailDeliverySettingsV1
    let priorJobIDs: [UUID]
    let previouslySent: Bool
    let allowResend: Bool
    let acknowledgeUnknownOutcome: Bool
    var id: UUID { report.id }
}

struct EmailDeliveryPresentation {
    let state: DeliveryState
    let actionKey: String
    let blockedReason: String?
    let previouslySent: Bool
    let allowResend: Bool
    let acknowledgeUnknownOutcome: Bool
    let lastErrorCode: String?
    let completedAt: Date?

    init(report: ReportRecordV1, jobs: [JobRecordV1], settings: EmailDeliverySettingsV1, busy: Bool) {
        let delivery = report.deliveries.first { $0.channel == .email }
        let attempts = jobs.filter { $0.deliveryChannel == .email && $0.runDirectory == report.runDirectory }
        let active = attempts.first { [.pending, .running, .cancelling].contains($0.state) }
        state = active.map { $0.state == .pending ? DeliveryState.pending : .sending }
            ?? delivery?.state ?? .notRequested
        previouslySent = delivery?.state == .sent || attempts.contains { $0.state == .succeeded }
        acknowledgeUnknownOutcome = delivery?.state == .unknown || attempts.contains { $0.state == .deliveryUnknown }
        // The SMTP publisher's override covers both a previous success and an unresolved attempt.
        allowResend = previouslySent || acknowledgeUnknownOutcome
        actionKey = acknowledgeUnknownOutcome ? "email.review_send"
            : previouslySent ? "email.resend" : state == .failed ? "email.retry" : "email.send"
        lastErrorCode = delivery?.error?.code
        completedAt = delivery?.completedAt
        if !report.isEffectiveDeepReport {
            blockedReason = "email.no_public_report"
        } else if !settings.enabled || settings.smtpHost.isEmpty || settings.username.isEmpty
            || settings.passwordSecret.isEmpty || settings.fromAddress.isEmpty || settings.toAddress.isEmpty
            || !(1...65_535).contains(settings.smtpPort) || settings.timeoutSeconds <= 0 {
            blockedReason = "email.configure_first"
        } else if busy {
            blockedReason = "email.busy"
        } else {
            blockedReason = nil
        }
    }
}
