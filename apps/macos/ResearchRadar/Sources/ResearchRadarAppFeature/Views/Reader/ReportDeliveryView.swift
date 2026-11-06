import ResearchRadarCore
import SwiftUI

struct ReportDeliveryView: View {
    let store: AppStore
    let report: ReportRecordV1
    let localization: LocalizationStore
    let configure: () -> Void
    @Binding var disclosure: ReportDeliveryDisclosureState

    private var snapshot: ReportDeliverySnapshot {
        .init(report: report, jobs: store.jobs, settings: store.configuration.delivery,
            busy: store.behaviorChangesBlocked)
    }

    var body: some View {
        DisclosureGroup(isExpanded: $disclosure.isExpanded) {
            VStack(spacing: 0) {
                ReportWeChatView(store: store, report: report, localization: localization, configure: configure)
                Divider()
                ReportEmailView(store: store, report: report, localization: localization, configure: configure)
            }
        } label: {
            HStack(spacing: 16) {
                Text(localization.text("delivery.section"))
                    .font(.system(size: 13, weight: .medium))
                Spacer(minLength: 8)
                channelStatus(.wechat, state: snapshot.wechat)
                channelStatus(.email, state: snapshot.email)
            }
        }
        // Keep split-view minimum-size probes from wrapping channel text at near-zero width.
        .frame(minWidth: 320)
        .padding(.horizontal, 16).padding(.vertical, 10)
        .accessibilityIdentifier("report.delivery")
    }

    private func channelStatus(_ channel: DeliveryChannel, state: DeliveryState) -> some View {
        Label(localization.text(channel == .wechat ? "setting.wechat" : "setting.email")
            + ": " + localization.text("delivery.\(state.rawValue)"),
            systemImage: channel == .wechat ? "doc.badge.plus" : "envelope")
            .font(.system(size: 12))
            .foregroundStyle(state == .failed || state == .unknown ? Color.orange : Color.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier(channel == .wechat ? "delivery.summary.wechat" : "delivery.summary.email")
    }
}
