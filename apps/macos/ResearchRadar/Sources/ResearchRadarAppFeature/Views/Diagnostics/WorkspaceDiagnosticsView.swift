import AppKit
import ResearchRadarCore
import SwiftUI

struct WorkspaceDiagnosticsView: View {
    let store: AppStore
    let localization: LocalizationStore
    var pasteboard: NSPasteboard = .general
    @State private var copyFeedback: String?

    var body: some View {
        Form {
            Section {
                Button(localization.text("diagnostics.copy"), systemImage: "doc.on.doc") {
                    do {
                        try DiagnosticsClipboard.copy(from: store, to: pasteboard)
                        copyFeedback = "diagnostics.copied"
                    } catch { copyFeedback = "diagnostics.copy_failed" }
                }
                .accessibilityIdentifier("diagnostics.copy")
                .help(localization.text("diagnostics.copy_detail"))
                if let copyFeedback {
                    Text(localization.text(copyFeedback)).font(.callout).foregroundStyle(.secondary)
                        .accessibilityIdentifier("diagnostics.copy_feedback")
                }
            }
            LabeledContent(localization.text("label.jobs"), value: "\(store.jobs.count)")
            LabeledContent(localization.text("label.reports"), value: "\(store.reports.count)")
            if let preflight = store.preflight {
                ForEach(preflight.checks.filter { $0.status != .ready }, id: \.id) { check in
                    LabeledContent(check.model ?? check.id) {
                        Text(check.message).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                    }
                }
            }
            if let error = store.lastErrorCode {
                Text(UserFacingErrorCatalog(localization: localization).message(for: error))
                Text(error).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
            } else {
                Label(localization.text("diagnostics.none"), systemImage: "checkmark.circle")
            }
        }.formStyle(.grouped).padding(20)
    }
}
