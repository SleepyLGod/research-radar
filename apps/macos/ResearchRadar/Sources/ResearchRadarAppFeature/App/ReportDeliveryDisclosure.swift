import Foundation
import ResearchRadarCore

/// Channel status only; sending and retry policy remain in the existing presentations.
struct ReportDeliverySnapshot: Equatable {
    let reportID: UUID
    let wechat: DeliveryState
    let email: DeliveryState

    init(reportID: UUID, wechat: DeliveryState, email: DeliveryState) {
        self.reportID = reportID
        self.wechat = wechat
        self.email = email
    }

    init(report: ReportRecordV1, jobs: [JobRecordV1], settings: DeliverySettingsV1, busy: Bool) {
        self.init(reportID: report.id,
            wechat: WeChatDraftPresentation(report: report, jobs: jobs, settings: settings.wechat, busy: busy).state,
            email: EmailDeliveryPresentation(report: report, jobs: jobs, settings: settings.email, busy: busy).state)
    }

    static func needsAttention(_ state: DeliveryState) -> Bool {
        [.pending, .sending, .failed, .unknown].contains(state)
    }
}

/// Ephemeral fold preference for one report, never durable delivery state.
struct ReportDeliveryDisclosureState {
    private(set) var snapshot: ReportDeliverySnapshot
    var isExpanded: Bool

    init(snapshot: ReportDeliverySnapshot) {
        self.snapshot = snapshot
        isExpanded = ReportDeliverySnapshot.needsAttention(snapshot.wechat)
            || ReportDeliverySnapshot.needsAttention(snapshot.email)
    }

    mutating func update(_ next: ReportDeliverySnapshot) {
        if next.reportID != snapshot.reportID {
            self = Self(snapshot: next)
            return
        }
        if next.wechat != snapshot.wechat && ReportDeliverySnapshot.needsAttention(next.wechat)
            || next.email != snapshot.email && ReportDeliverySnapshot.needsAttention(next.email) {
            isExpanded = true
        }
        snapshot = next
    }
}
