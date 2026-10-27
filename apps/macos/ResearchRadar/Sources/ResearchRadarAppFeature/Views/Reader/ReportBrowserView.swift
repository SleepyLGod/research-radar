import AppKit
import ResearchRadarCore
import SwiftUI

struct ReportBrowserView: View {
    @Bindable var store: AppStore
    let report: ReportRecordV1
    let localization: LocalizationStore
    @Bindable var presentation: WindowPresentationState
    let back: () -> Void
    let configure: () -> Void
    @State var browser = ReportBrowserModel()
    @State private var figures = PaperFiguresModel()
    @State private var deliveryDisclosure: ReportDeliveryDisclosureState

    private var workspace: URL { URL(fileURLWithPath: store.configuration.workspaceRoot) }
    private var visible: Bool {
        presentation.isVisible && presentation.windowMode(saved: store.runtime.windowMode) == .full
    }
    private var deliverySnapshot: ReportDeliverySnapshot {
        .init(report: report, jobs: store.jobs, settings: store.configuration.delivery, busy: store.behaviorChangesBlocked)
    }
    private var selectedFigures: [PaperFiguresModel.Figure] {
        guard visible, let paper = browser.selectedPaper else { return [] }
        return figures.images(for: paper.id)
    }

    init(store: AppStore, report: ReportRecordV1, localization: LocalizationStore,
         presentation: WindowPresentationState, back: @escaping () -> Void,
         configure: @escaping () -> Void, browser: ReportBrowserModel = ReportBrowserModel()) {
        self.store = store; self.report = report; self.localization = localization
        self.presentation = presentation; self.back = back; self.configure = configure
        _browser = State(initialValue: browser)
        _deliveryDisclosure = State(initialValue: .init(snapshot: .init(report: report,
            jobs: store.jobs, settings: store.configuration.delivery, busy: store.behaviorChangesBlocked)))
    }

    var body: some View {
        ScrollViewReader { proxy in
            VStack(spacing: 0) {
                navigationHeader
                Divider()
                if browser.showsDelivery {
                    ReportDeliveryView(store: store, report: report, localization: localization,
                        configure: configure, disclosure: $deliveryDisclosure)
                    Divider()
                }
                if let paper = browser.selectedPaper, let contents = browser.contents {
                    PaperReadingControls(papers: contents.papers, selected: paper,
                        sections: paper.readingSections(hasAvailableFigures: !selectedFigures.isEmpty), localization: localization,
                        select: browser.openPaper, jump: { proxy.scrollTo($0, anchor: .top) })
                    Divider()
                }
                if browser.page == .fullReport {
                    if visible {
                        ReportReaderView(report: report, workspaceRoot: workspace, localization: localization)
                    } else { Color.clear }
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 28) {
                            if let paper = browser.selectedPaper {
                                PaperDetailView(paper: paper, figures: selectedFigures, localization: localization)
                            } else {
                                overview
                            }
                        }
                        .frame(maxWidth: browser.selectedPaper == nil ? 760 : 700, alignment: .leading)
                        .padding(.horizontal, 20).padding(.vertical, 24)
                        .frame(maxWidth: .infinity, alignment: .top)
                    }
                    .id(browser.page)
                }
            }
        }
        .background(Color(nsColor: .textBackgroundColor))
        .task(id: report.id) { await browser.load(report: report, workspaceRoot: workspace) }
        .task(id: visible ? browser.selectedPaper?.id : nil) {
            await figures.load(paper: visible ? browser.selectedPaper : nil, report: report, workspace: workspace)
        }
        .onChange(of: deliverySnapshot, initial: true) { _, snapshot in deliveryDisclosure.update(snapshot) }
    }

    private var navigationHeader: some View {
        HStack {
            Button {
                if browser.page == .overview { back() } else { browser.back() }
            } label: {
                Label(localization.text(browser.page == .overview ? "action.back_reports" : "paper.back"), systemImage: "chevron.left")
            }
            Spacer(minLength: 8)
            Text(report.reportDate).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
            if browser.page != .fullReport {
                Button { browser.page = .fullReport } label: {
                    Label(localization.text("paper.full_report"), systemImage: "doc.text")
                }
            }
        }.padding(.horizontal, 20).padding(.vertical, 12)
    }

    @ViewBuilder private var overview: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(ReportHeading.title(report: report, topic: store.selectedTopic))
                .font(.system(size: 18, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
            Text(report.summary).font(.system(size: 13)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        if let contents = browser.contents {
            if !contents.papers.isEmpty {
                Text(localization.text("paper.deep_reads")).font(.system(size: 14, weight: .semibold))
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 12)], spacing: 12) {
                    ForEach(contents.papers) { paper in
                        Button { browser.openPaper(paper.id) } label: {
                            PaperPreviewView(paper: paper, localization: localization)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(localization.text("paper.open")): \(paper.title)")
                    }
                }
            } else {
                Text(localization.text("paper.no_deep_reads")).font(.system(size: 13)).foregroundStyle(.secondary)
            }
            if !contents.sources.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text(localization.text("paper.sources")).font(.system(size: 14, weight: .semibold))
                    Text(localization.text("paper.sources_note")).font(.system(size: 12)).foregroundStyle(.secondary)
                }
                ForEach(contents.sources.indices, id: \.self) { index in
                    let source = contents.sources[index]
                    VStack(alignment: .leading, spacing: 6) {
                        if let url = source.sourceURL {
                            Link(source.title ?? "", destination: url)
                        } else { Text(source.title ?? "") }
                        if let gist = source.gist, !gist.isEmpty {
                            Text(gist).font(.system(size: 13)).foregroundStyle(.secondary)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        } else if browser.loadFailed {
            Label(localization.text("paper.unavailable"), systemImage: "doc.text.magnifyingglass")
                .font(.system(size: 13)).foregroundStyle(.secondary)
        } else {
            ProgressView().controlSize(.small)
        }
        Divider()
        DisclosureGroup(localization.text("paper.report_info")) {
            Text(report.title).font(.system(size: 13)).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
        }.font(.system(size: 12)).foregroundStyle(.secondary)
    }
}

private struct PaperPreviewView: View {
    let paper: ReportContents.Paper
    let localization: LocalizationStore

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label(localization.text("paper.deep_read"), systemImage: "doc.text.magnifyingglass")
                Spacer()
                if let version = paper.version { Text(version).monospaced() }
            }.font(.system(size: 12)).foregroundStyle(.secondary)
            Text(paper.title).font(.system(size: 15, weight: .semibold))
                .foregroundStyle(.primary).lineLimit(3).help(paper.title)
            VStack(alignment: .leading, spacing: 5) {
                Text(localization.text(paper.preview.titleKey)).font(.system(size: 12, weight: .medium))
                Text(paper.preview.text).font(.system(size: 14)).foregroundStyle(.primary)
                .lineLimit(3).multilineTextAlignment(.leading)
            }.foregroundStyle(.secondary)
            Spacer(minLength: 0)
            HStack {
                HStack(spacing: 4) {
                    Text("\(paper.claims.count)").monospacedDigit()
                    Text(localization.text("paper.claims"))
                }.foregroundStyle(.secondary).help(localization.text("paper.claims_hint"))
                Spacer()
                Label(localization.text("paper.open"), systemImage: "arrow.right").foregroundStyle(.tint)
            }.font(.system(size: 12))
        }
        .multilineTextAlignment(.leading).padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
        .contentShape(Rectangle())
    }
}
