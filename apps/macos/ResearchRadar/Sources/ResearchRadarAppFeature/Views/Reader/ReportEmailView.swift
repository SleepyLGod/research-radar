import ResearchRadarCore
import SwiftUI

struct ReportEmailView: View {
    let store: AppStore
    let report: ReportRecordV1
    let localization: LocalizationStore
    let configure: () -> Void
    @State private var confirmation: EmailSendConfirmation?

    private var presentation: EmailDeliveryPresentation {
        EmailDeliveryPresentation(report: report, jobs: store.jobs,
            settings: store.configuration.delivery.email, busy: store.behaviorChangesBlocked)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                Label(localization.text("setting.email"), systemImage: "envelope")
                Text(localization.text("delivery.\(presentation.state.rawValue)"))
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("email.status")
                Spacer()
                if presentation.blockedReason == "email.configure_first" {
                    Button(localization.text("email.configure"), action: configure)
                        .accessibilityIdentifier("email.configure")
                } else {
                    Button {
                        do { confirmation = try store.prepareEmailDelivery(reportID: report.id) }
                        catch let error as EmailDeliveryActionError {
                            store.showEmailDeliveryError(error)
                        } catch { store.showEmailDeliveryError(.blocked("delivery_retry_blocked")) }
                    } label: {
                        Label(localization.text(presentation.actionKey), systemImage: "paperplane")
                    }
                    .disabled(presentation.blockedReason != nil)
                    .accessibilityIdentifier("email.send")
                }
            }
            if let reason = presentation.blockedReason {
                Text(localization.text(reason)).foregroundStyle(.secondary)
            } else {
                Text(localization.text("email.destination") + " " + store.configuration.delivery.email.toAddress)
                    .foregroundStyle(.secondary).textSelection(.enabled)
            }
            if let code = presentation.lastErrorCode {
                Text(UserFacingErrorCatalog(localization: localization).message(for: code))
                    .foregroundStyle(.secondary)
            }
            if let date = presentation.completedAt {
                HStack(spacing: 4) {
                    Text(localization.text("email.last_sent"))
                    Text(date, format: .dateTime.year().month().day().hour().minute())
                }.foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 12)).padding(.horizontal, 16).padding(.vertical, 10)
        .sheet(item: $confirmation) { value in
            EmailSendConfirmationView(confirmation: value, localization: localization,
                cancel: { confirmation = nil }, send: {
                    confirmation = nil
                    Task { await store.sendEmail(value) }
                })
        }
        .onChange(of: report.id) { _, _ in confirmation = nil }
    }
}

struct EmailSendConfirmationView: View {
    let confirmation: EmailSendConfirmation
    let localization: LocalizationStore
    let cancel: () -> Void
    let send: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(localization.text("email.confirm_title"), systemImage: "envelope")
                .font(.headline)
            Text(confirmation.report.title).fixedSize(horizontal: false, vertical: true)
            LabeledContent(localization.text("label.from")) {
                Text(confirmation.settings.fromAddress).textSelection(.enabled)
            }
            LabeledContent(localization.text("label.to")) {
                Text(confirmation.settings.toAddress).textSelection(.enabled)
            }
            Text(localization.text("email.confirm_detail")).foregroundStyle(.secondary)
            if confirmation.acknowledgeUnknownOutcome {
                Label(localization.text("email.unknown_warning"), systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            }
            if confirmation.previouslySent {
                Text(localization.text("email.resend_warning"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button(localization.text("action.cancel"), action: cancel).keyboardShortcut(.cancelAction)
                Button(localization.text(confirmation.allowResend || confirmation.acknowledgeUnknownOutcome
                    ? "email.confirm_resend" : "email.send"), action: send)
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("email.confirm_send")
            }
        }
        .font(.system(size: 13)).padding(20).frame(width: 420)
    }
}
