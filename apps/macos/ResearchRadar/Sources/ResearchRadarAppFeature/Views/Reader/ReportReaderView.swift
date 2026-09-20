import Foundation
import ResearchRadarCore
import SwiftUI

/// The parent mounts this view only while a selected report is visible.
/// Dismantling releases WebKit; this view never observes or controls windows.
/// After memory pressure, remounting (or selecting another report) loads again.
@MainActor
public struct ReportReaderView: View {
    public let report: ReportRecordV1
    public let workspaceRoot: URL
    public let localization: LocalizationStore
    @State private var errorKey: String?

    public init(report: ReportRecordV1, workspaceRoot: URL, localization: LocalizationStore) {
        self.report = report
        self.workspaceRoot = workspaceRoot
        self.localization = localization
    }

    public var body: some View {
        VStack(spacing: 0) {
            if let errorKey {
                Text(localization.text(errorKey))
                    .foregroundStyle(.secondary)
                    .padding()
                    .accessibilityIdentifier("reader.error")
            }
            ReportReaderRepresentable(report: report, workspaceRoot: workspaceRoot, errorKey: $errorKey)
        }
    }
}

@MainActor
struct ReportReaderRepresentable: NSViewRepresentable {
    let report: ReportRecordV1
    let workspaceRoot: URL
    @Binding var errorKey: String?

    func makeNSView(context: Context) -> ReportReaderHost { ReportReaderHost() }

    func updateNSView(_ host: ReportReaderHost, context: Context) {
        host.onError = { key in
            Task { @MainActor in errorKey = key }
        }
        host.requestDisplay(report, workspaceRoot: workspaceRoot)
    }

    static func dismantleNSView(_ host: ReportReaderHost, coordinator: ()) {
        host.onError = nil
        host.releaseReader()
    }
}
