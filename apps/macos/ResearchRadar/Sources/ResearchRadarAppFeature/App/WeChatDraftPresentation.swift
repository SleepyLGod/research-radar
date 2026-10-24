import Foundation
import ResearchRadarCore

enum WeChatDraftActionError: Error, Equatable {
    case blocked(String)
    var code: String { switch self { case .blocked(let code): code } }
}

/// Binds explicit approval to the saved cover, author, report and WeChat attempts.
struct WeChatDraftConfirmation: Equatable, Identifiable {
    let report: ReportRecordV1
    let settings: WeChatDeliverySettingsV1
    let priorJobIDs: [UUID]
    let credentialRevision: UUID
    let previouslyCreated: Bool
    let acknowledgeUnknownOutcome: Bool
    var allowResend: Bool { previouslyCreated || acknowledgeUnknownOutcome }
    var id: UUID { report.id }
}

struct WeChatDraftPresentation {
    let state: DeliveryState
    let actionKey: String
    let blockedReason: String?
    let previouslyCreated: Bool
    let acknowledgeUnknownOutcome: Bool
    let lastErrorCode: String?

    init(report: ReportRecordV1, jobs: [JobRecordV1], settings: WeChatDeliverySettingsV1, busy: Bool) {
        let delivery = report.deliveries.first { $0.channel == .wechat }
        let attempts = jobs.filter { $0.deliveryChannel == .wechat && $0.runDirectory == report.runDirectory }
        let active = attempts.first { [.pending, .running, .cancelling].contains($0.state) }
        state = active.map { $0.state == .pending ? DeliveryState.pending : .sending }
            ?? delivery?.state ?? .notRequested
        previouslyCreated = delivery?.state == .created || attempts.contains { $0.state == .succeeded }
        acknowledgeUnknownOutcome = delivery?.state == .unknown || attempts.contains { $0.state == .deliveryUnknown }
        actionKey = acknowledgeUnknownOutcome ? "wechat.review_create" : previouslyCreated ? "wechat.create_again"
            : state == .failed ? "wechat.retry" : "wechat.create"
        lastErrorCode = delivery?.error?.code
        if !report.isEffectiveDeepReport { blockedReason = "wechat.no_public_report" }
        else if !settings.enabled || settings.thumbMediaID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || settings.appIDSecret.isEmpty || settings.appSecretSecret.isEmpty {
            blockedReason = "wechat.configure_first"
        } else if busy { blockedReason = "wechat.busy" }
        else { blockedReason = nil }
    }
}
