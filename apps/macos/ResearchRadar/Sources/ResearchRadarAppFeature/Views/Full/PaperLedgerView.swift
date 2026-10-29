import AppKit
import ResearchRadarCore
import SwiftUI

struct PaperLedgerView: View {
    @Bindable var store: AppStore
    let localization: LocalizationStore
    @Bindable var presentation: WindowPresentationState
    @Bindable var model: PaperLedgerModel
    var openEvidence: ((KnowledgeEvidenceTarget) -> Void)? = nil
    let open: (PaperOccurrenceV1, Bool, Bool) -> Void
    private var knowledge: TopicKnowledgeModel { store.topicKnowledge }
    var organizationControlsVisible: Bool {
        model.selectedPaper == nil || TopicKnowledgePresentation(topicID: store.selectedTopic?.id ?? "", jobs: store.jobs).isActive
    }

    private var references: [LedgerReportReferenceV1] {
        store.selectedTopicReports.map {
            .init(reportID: $0.id, reportDate: $0.reportDate, runDirectory: $0.runDirectory)
        }
    }
    private struct LoadKey: Equatable {
        let topic: String?
        let reports: [LedgerReportReferenceV1]
        let visible: Bool
        let organization: JobRecordV1?
    }
    private var loadKey: LoadKey {
        .init(topic: store.selectedTopic?.id, reports: references,
            visible: presentation.isVisible && presentation.windowMode(saved: store.runtime.windowMode) == .full,
            organization: store.selectedTopic.flatMap { TopicKnowledgePresentation(topicID: $0.id, jobs: store.jobs).job })
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                TopicSelectionView(store: store, localization: localization)
                Spacer()
                if organizationControlsVisible {
                    TopicKnowledgeView(store: store, model: knowledge, localization: localization)
                }
                Button { Task { await load(force: true) } } label: {
                    Image(systemName: "arrow.clockwise")
                }.help(localization.text("ledger.refresh"))
                    .accessibilityLabel(localization.text("ledger.refresh"))
                    .disabled(model.loading || store.behaviorChangesBlocked)
            }.controlSize(.small).padding(.horizontal, 20).padding(.vertical, 10)
            TopicKnowledgeNotice(store: store, model: knowledge, localization: localization)
            Divider()
            if let key = model.errorKey {
                Label(localization.text(key), systemImage: "exclamationmark.circle")
                    .font(.system(size: 13)).foregroundStyle(.secondary).padding(12)
            }
            if model.snapshot?.unavailableReports.isEmpty == false {
                Label(localization.text("ledger.partial"), systemImage: "doc.badge.ellipsis")
                    .font(.system(size: 12)).foregroundStyle(.secondary).padding(.horizontal, 20).padding(.vertical, 8)
            }
            if model.topicID != store.selectedTopic?.id {
                if store.behaviorChangesBlocked {
                    Text(localization.text("ledger.busy")).font(.system(size: 13)).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else if let paper = model.selectedPaper {
                paperHistory(paper)
            } else if knowledge.graph(for: store.selectedTopic?.id ?? "") != nil {
                knowledgeWorkspace
            } else {
                paperList
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .textBackgroundColor))
        .task(id: loadKey) { if loadKey.visible { await load() } }
        .onChange(of: store.behaviorChangesBlocked) { _, blocked in
            if !blocked, model.takeDeferredLoad(topicID: store.selectedTopic?.id, visible: loadKey.visible) {
                Task { await load() }
            }
        }
    }

    private var knowledgeWorkspace: some View {
        VStack(spacing: 0) {
            if let topicID = store.selectedTopic?.id {
                HStack(spacing: 14) {
                    Picker(localization.text("graph.view"), selection: Binding(
                        get: { knowledge.graphSelection(for: topicID).mode },
                        set: { knowledge.setGraphMode($0, topicID: topicID) })) {
                        Label(localization.text("graph.relations"), systemImage: "point.3.connected.trianglepath.dotted")
                            .tag(KnowledgeGraphSelection.Mode.relations)
                        Label(localization.text("graph.classification"), systemImage: "square.grid.2x2")
                            .tag(KnowledgeGraphSelection.Mode.classification)
                        Label(localization.text("graph.ledger"), systemImage: "list.bullet")
                            .tag(KnowledgeGraphSelection.Mode.ledger)
                    }.pickerStyle(.segmented).labelsHidden().fixedSize()
                    if knowledge.graphSelection(for: topicID).mode != .ledger {
                        if knowledge.graphSelection(for: topicID).paperKey == nil {
                            KnowledgeGraphControls(topicID: topicID, model: knowledge, localization: localization)
                        } else { Spacer() }
                    } else { ledgerFilters }
                }.controlSize(.small).padding(.horizontal, 20).padding(.vertical, 12)
                Divider()
                if knowledge.graphSelection(for: topicID).mode != .ledger {
                    KnowledgeGraphView(topicID: topicID, model: knowledge, localization: localization,
                        historyPaperIDs: Set(model.snapshot?.papers.map(\.id) ?? []), openHistory: { paper in
                        model.select(paper.paperID)
                    }, availableReferences: availableReferenceIDs(topicID: topicID), openEvidence: { reference in
                        guard let graph = knowledge.graph(for: topicID),
                              let target = model.evidenceTarget(reference: reference, graph: graph) else { return }
                        openEvidence?(target)
                    })
                } else { paperResults }
            }
        }
    }

    private var paperList: some View {
        VStack(spacing: 0) {
            ledgerFilters.padding(.horizontal, 20).padding(.vertical, 12)
            paperResults
        }
    }

    private func availableReferenceIDs(topicID: String) -> Set<String> {
        guard openEvidence != nil, let graph = knowledge.graph(for: topicID) else { return [] }
        return Set(graph.references.filter { model.evidenceTarget(reference: $0, graph: graph) != nil }.map(\.id))
    }

    private var ledgerFilters: some View {
        HStack {
            TextField(localization.text("ledger.search"), text: Binding(get: { model.query }, set: { model.setQuery($0) }))
                .textFieldStyle(.roundedBorder)
            Picker(localization.text("ledger.filter"), selection: Binding(get: { model.filter }, set: { model.setFilter($0) })) {
                ForEach(PaperLedgerModel.Filter.allCases, id: \.self) { filter in
                    Text(localization.text("ledger.filter.\(filter.rawValue)")).tag(filter)
                }
            }.pickerStyle(.segmented).frame(maxWidth: 310).labelsHidden()
        }
    }

    private var paperResults: some View {
        Group {
            if model.loading && model.snapshot == nil {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.papers.isEmpty {
                WorkspaceEmptyState(title: localization.text("ledger.empty"), symbol: "books.vertical",
                    clearTitle: localization.text("action.clear_filters"), clearFilters: model.query.isEmpty && model.filter == .all ? nil : {
                        model.setQuery(""); model.setFilter(.all)
                    })
            } else {
                List(model.papers) { paper in
                    Button { model.select(paper.id) } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(paper.title).font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(.primary).lineLimit(3).help(paper.title)
                            HStack {
                                Label(localization.text(paper.hasPublicReading ? "ledger.reading" : "ledger.source_only"),
                                    systemImage: paper.hasPublicReading ? "doc.text.magnifyingglass" : "link")
                                Spacer(minLength: 8)
                                Text([paper.firstIncluded, paper.lastIncluded].compactMap { $0 }
                                    .reduce(into: [String]()) { if $0.last != $1 { $0.append($1) } }.joined(separator: " – "))
                                    .monospacedDigit()
                            }.font(.system(size: 12)).foregroundStyle(.secondary)
                        }.padding(.vertical, 10).frame(maxWidth: .infinity, alignment: .leading)
                    }.buttonStyle(.plain)
                }.listStyle(.inset)
            }
        }
    }

    private func paperHistory(_ paper: LedgerPaperV1) -> some View {
        VStack(spacing: 0) {
            HStack {
                Button { model.select(nil) } label: { Label(localization.text("ledger.back"), systemImage: "chevron.left") }
                Spacer()
            }.padding(.horizontal, 20).padding(.vertical, 12)
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text(paper.title).font(.system(size: 20, weight: .semibold)).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    ForEach(paper.occurrences) { occurrence in
                        VStack(alignment: .leading, spacing: 12) {
                            Divider()
                            HStack {
                                Text(occurrence.reportDate).monospacedDigit()
                                Text(occurrence.version ?? localization.text("ledger.version_unknown")).monospaced()
                                Spacer()
                                Text(localization.text(occurrence.paperIndex == nil ? "ledger.source_only" : "ledger.reading"))
                            }.font(.system(size: 12)).foregroundStyle(.secondary)
                            if occurrence.title != paper.title { Text(occurrence.title).font(.system(size: 14)) }
                            HStack(spacing: 16) {
                                Button(localization.text("ledger.report")) { open(occurrence, false, false) }
                                if occurrence.paperIndex != nil {
                                    Button(localization.text("paper.open")) { open(occurrence, false, true) }
                                    Button(localization.text("ledger.evidence")) { open(occurrence, true, true) }
                                }
                                if let url = URL(string: occurrence.sourceURL) {
                                    Link(destination: url) { Image(systemName: "arrow.up.right") }
                                        .help(localization.text("paper.original"))
                                        .accessibilityLabel(localization.text("paper.original"))
                                }
                            }.controlSize(.small)
                        }
                    }
                }.frame(maxWidth: 700, alignment: .leading).padding(20)
                    .frame(maxWidth: .infinity, alignment: .top)
            }
        }
    }

    private func load(force: Bool = false) async {
        guard let topicID = store.selectedTopic?.id else { return }
        guard !store.behaviorChangesBlocked else { model.deferLoad(for: topicID); return }
        model.deferLoad(for: nil)
        await model.load(topicID: topicID, reports: references, force: force) { topic, reports in
            try await store.readPaperLedger(topicID: topic, reports: reports)
        }
        guard store.selectedTopic?.id == topicID, loadKey.visible else { return }
        await knowledge.load(topicID: topicID) { try await store.readTopicKnowledge(topicID: $0) }
    }
}
