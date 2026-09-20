import AppKit
import ResearchRadarCore
import SwiftUI

enum WorkspaceSection: String, CaseIterable, Identifiable {
    case overview, topics, reports, settings, diagnostics
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .overview: "sun.max"
        case .topics: "text.magnifyingglass"
        case .reports: "doc.richtext"
        case .settings: "gearshape"
        case .diagnostics: "stethoscope"
        }
    }
}

struct WorkspaceNavigation {
    var section: WorkspaceSection = .overview {
        didSet { if section != .reports { showingReport = false } }
    }
    private(set) var reportID: UUID?
    private var showingReport = false
    var isReading: Bool { section == .reports && showingReport && reportID != nil }
    mutating func openReport(_ id: UUID) { section = .reports; reportID = id; showingReport = true }
    mutating func showReportList() { showingReport = false }
}

struct FullWorkspaceView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    @Bindable var presentation: WindowPresentationState
    @State private var navigation = WorkspaceNavigation()
    @State private var columns: NavigationSplitViewVisibility = .all
    @State private var restoredSelection = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Button { columns = columns == .detailOnly ? .all : .detailOnly } label: {
                    Image(systemName: "sidebar.left")
                }
                .help(localization.text("action.toggle_sidebar"))
                .accessibilityLabel(localization.text("action.toggle_sidebar"))
                Text(localization.text("nav.\(navigation.section.rawValue)"))
                    .font(.system(size: 13, weight: .medium))
                Spacer()
                Button { store.performAction { try store.setWindowMode(.compact) } } label: {
                    Image(systemName: "arrow.down.right.and.arrow.up.left")
                }
                .help(localization.text("action.compact"))
                .accessibilityLabel(localization.text("action.compact"))
            }
            .buttonStyle(.glass).padding(.horizontal, 14).padding(.vertical, 10)
            Divider()
            NavigationSplitView(columnVisibility: $columns) {
                List(WorkspaceSection.allCases, selection: $navigation.section) { section in
                    Label(localization.text("nav.\(section.rawValue)"), systemImage: section.symbol)
                        .padding(.vertical, 2)
                        .tag(section)
                }
                .navigationSplitViewColumnWidth(min: 155, ideal: 180, max: 220)
                .safeAreaInset(edge: .bottom) {
                    Label("ResearchRadar", systemImage: "dot.radiowaves.left.and.right")
                        .font(.system(size: 12)).foregroundStyle(.secondary).padding(12)
                }
            } detail: {
                detail
            }
            .toolbar(removing: .sidebarToggle)
        }
        .onAppear {
            if let id = presentation.requestedReportID {
                navigation.openReport(id); presentation.requestedReportID = nil
            } else if let section = presentation.requestedSection {
                navigation.section = section; presentation.requestedSection = nil
            } else if !restoredSelection, let id = store.selectedReportID { navigation.openReport(id) }
            restoredSelection = true
        }
        .onChange(of: store.selectedReportID) { _, id in
            if let id { navigation.openReport(id) } else { navigation.showReportList() }
        }
        .onChange(of: store.runtime.selectedTopicID) { _, _ in navigation.showReportList() }
        .onChange(of: presentation.requestedSection) { _, section in
            if let section { navigation.section = section; presentation.requestedSection = nil }
        }
        .onChange(of: presentation.requestedReportID) { _, id in
            if let id { navigation.openReport(id); presentation.requestedReportID = nil }
        }
    }

    @ViewBuilder private var detail: some View {
        switch navigation.section {
        case .overview:
            TodayContentView(store: store, localization: localization, compact: false, configure: {
                navigation.section = .settings
            }) { report in
                store.selectReport(report.id)
                navigation.openReport(report.id)
            }
        case .topics:
            TopicsView(store: store, localization: localization)
        case .reports:
            reports
        case .settings:
            WorkspaceSettingsView(store: store, localization: localization)
        case .diagnostics:
            WorkspaceDiagnosticsView(store: store, localization: localization)
        }
    }

    @ViewBuilder private var reports: some View {
        if navigation.isReading,
           let report = store.reports.first(where: { $0.id == navigation.reportID && $0.topicID == store.selectedTopic?.id }) {
            VStack(spacing: 0) {
                HStack {
                    Button { navigation.showReportList() } label: {
                        Label(localization.text("action.back_reports"), systemImage: "chevron.left")
                    }
                    Spacer()
                    Text(report.reportDate).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                }.padding(16)
                Divider()
                if presentation.isVisible && store.runtime.windowMode == .full {
                    ReportReaderView(report: report, workspaceRoot: URL(fileURLWithPath: store.configuration.workspaceRoot), localization: localization).id(report.id)
                } else {
                    Color.clear
                }
            }
        } else {
            ReportListView(store: store, localization: localization) { report in
                store.selectReport(report.id)
                navigation.openReport(report.id)
            }
        }
    }
}

private struct ReportListView: View {
    @Bindable var store: AppStore
    let localization: LocalizationStore
    let open: (ReportRecordV1) -> Void

    private var reports: [ReportRecordV1] {
        store.selectedTopicReports
    }

    var body: some View {
        VStack(spacing: 0) {
            TopicSelectionView(store: store, localization: localization).padding(20)
            Divider()
            if reports.isEmpty {
                ContentUnavailableView(localization.text("empty.reports"), systemImage: "doc.text")
            } else {
                List(reports) { report in
                    Button { open(report) } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(report.reportDate).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                            Text(report.title).font(.headline).foregroundStyle(.primary)
                                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                            Text(report.summary).font(.callout).foregroundStyle(.secondary)
                                .lineLimit(2).multilineTextAlignment(.leading)
                            Label(localization.text("action.open_report"), systemImage: "arrow.up.right")
                                .font(.callout).foregroundStyle(.blue)
                        }.padding(.vertical, 10).frame(maxWidth: .infinity, alignment: .leading)
                    }.buttonStyle(.plain)
                }.listStyle(.inset)
            }
        }
    }
}

private struct WorkspaceDiagnosticsView: View {
    let store: AppStore
    let localization: LocalizationStore
    var body: some View {
        Form {
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
