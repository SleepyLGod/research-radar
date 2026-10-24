import ResearchRadarCore
import SwiftUI

struct ReportWeChatView: View {
    let store: AppStore
    let report: ReportRecordV1
    let localization: LocalizationStore
    let configure: () -> Void
    @State private var confirmation: WeChatDraftConfirmation?

    private var presentation: WeChatDraftPresentation {
        .init(report: report, jobs: store.jobs,
            settings: store.configuration.delivery.wechat, busy: store.behaviorChangesBlocked)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                Label(localization.text("setting.wechat"), systemImage: "doc.badge.plus")
                Text(localization.text("delivery.\(presentation.state.rawValue)"))
                    .foregroundStyle(.secondary).accessibilityIdentifier("wechat.status")
                Spacer()
                if presentation.blockedReason == "wechat.configure_first" {
                    Button(localization.text("wechat.configure"), action: configure)
                        .accessibilityIdentifier("wechat.configure")
                } else {
                    Button {
                        do { confirmation = try store.prepareWeChatDraft(reportID: report.id) }
                        catch let error as WeChatDraftActionError { store.showWeChatDraftError(error) }
                        catch { store.showWeChatDraftError(.blocked("delivery_retry_blocked")) }
                    } label: {
                        Label(localization.text(presentation.actionKey), systemImage: "doc.badge.plus")
                    }
                    .disabled(presentation.blockedReason != nil)
                    .accessibilityIdentifier("wechat.create")
                }
            }
            Text(localization.text(presentation.blockedReason ?? "wechat.draft_only"))
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let code = presentation.lastErrorCode {
                Text(UserFacingErrorCatalog(localization: localization).message(for: code))
                    .foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 12)).padding(.horizontal, 16).padding(.vertical, 10)
        .sheet(item: $confirmation) { value in
            WeChatDraftConfirmationView(confirmation: value, localization: localization,
                cancel: { confirmation = nil }, create: {
                    confirmation = nil
                    Task { await store.createWeChatDraft(value) }
                })
        }
        .onChange(of: report.id) { _, _ in confirmation = nil }
    }
}

struct WeChatDraftConfirmationView: View {
    let confirmation: WeChatDraftConfirmation
    let localization: LocalizationStore
    let cancel: () -> Void
    let create: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(localization.text("wechat.confirm_title"), systemImage: "doc.badge.plus").font(.headline)
            Text(confirmation.report.title).fixedSize(horizontal: false, vertical: true)
            LabeledContent(localization.text("label.author")) {
                Text(confirmation.settings.author.isEmpty ? "ResearchRadar" : confirmation.settings.author)
            }
            Text(localization.text("wechat.saved_cover"))
            Text(localization.text("wechat.confirm_detail"))
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if confirmation.acknowledgeUnknownOutcome {
                Label(localization.text("wechat.unknown_warning"), systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            }
            if confirmation.previouslyCreated {
                Text(localization.text("wechat.duplicate_warning"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button(localization.text("action.cancel"), action: cancel).keyboardShortcut(.cancelAction)
                Button(localization.text(confirmation.allowResend ? "wechat.confirm_again" : "wechat.create"), action: create)
                    .keyboardShortcut(.defaultAction).accessibilityIdentifier("wechat.confirm_create")
            }
        }
        .font(.system(size: 13)).padding(20).frame(width: 420)
    }
}
