import ResearchRadarCore
import SwiftUI

/// Native browser of saved classification partitions and exact source material.
struct KnowledgeGraphView: View {
    let topicID: String
    let model: TopicKnowledgeModel
    let localization: LocalizationStore
    let historyPaperIDs: Set<String>
    let openHistory: (KnowledgePaperV1) -> Void
    var availableReferences: Set<String> = []
    var openEvidence: ((KnowledgeReferenceV1) -> Void)? = nil
    private var graph: KnowledgeGraphV1? { model.graph(for: topicID) }
    private var selection: KnowledgeGraphSelection { model.graphSelection(for: topicID) }

    var body: some View {
        if let graph {
            if let paper = graph.papers.first(where: { $0.id == selection.paperKey }) {
                KnowledgePaperDetailView(paper: paper, graph: graph, localization: localization,
                    back: { model.selectGraphPaper(nil, topicID: topicID) },
                    openHistory: historyPaperIDs.contains(paper.paperID) ? { openHistory(paper) } : nil)
                    .id(graph.snapshotID + paper.id)
            } else {
                if selection.mode == .relations {
                    KnowledgeRelationView(topicID: topicID, model: model, graph: graph, localization: localization,
                        availableReferences: availableReferences, openEvidence: openEvidence)
                } else { classification }
            }
        }
    }

    private var classification: some View {
        let groups = model.visibleGraphGroups(for: topicID)
        let selectedGroup = groups.first { $0.id == selection.groupID }
        let sections = KnowledgeClassificationLayout.sections(groups: selectedGroup.map { [$0] } ?? groups,
            papers: model.visibleGraphPapers(for: topicID))
        return VStack(spacing: 0) {
            if let selectedGroup {
                HStack {
                    Button { model.selectGroup(nil, topicID: topicID) } label: {
                        Label(selectedGroup.label, systemImage: "xmark")
                    }.buttonStyle(.borderless).help(localization.text("graph.clear_group"))
                    Spacer()
                }.font(.system(size: 12)).padding(.horizontal, 20).padding(.vertical, 8)
            }
            if sections.isEmpty {
                WorkspaceEmptyState(title: localization.text("graph.no_match"), symbol: "line.3.horizontal.decrease",
                    clearTitle: localization.text("action.clear_filters"), clearFilters: hasFilters ? {
                        model.clearGraphFilters(topicID: topicID)
                    } : nil)
            } else {
                KnowledgeClassificationCanvas(sections: sections, localization: localization,
                    position: Binding(get: {
                        guard let key = selection.scrollPaperKey,
                              let section = sections.first(where: { $0.id == selection.scrollSectionID && $0.papers.contains { $0.id == key } })
                                ?? sections.first(where: { $0.papers.contains { $0.id == key } }) else { return nil }
                        return .init(sectionID: section.id, paperKey: key)
                    }, set: { target in
                        model.setGraphScrollPosition(target?.paperKey, sectionID: target?.sectionID, topicID: topicID)
                    }), selectGroup: { model.selectGroup($0, topicID: topicID) },
                    selectPaper: { model.selectGraphPaper($0, topicID: topicID) })
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var hasFilters: Bool { selection.groupID != nil || !selection.query.isEmpty || !selection.keywords.isEmpty }
}

struct KnowledgeGraphControls: View {
    let topicID: String
    let model: TopicKnowledgeModel
    let localization: LocalizationStore
    private var selection: KnowledgeGraphSelection { model.graphSelection(for: topicID) }

    var body: some View {
        if let graph = model.graph(for: topicID) {
            HStack(spacing: 12) {
                if selection.mode != .relations && !graph.facets.isEmpty {
                    Picker(localization.text("graph.facet"), selection: Binding(
                        get: { selection.facetID ?? graph.facets[0].id },
                        set: { model.selectFacet($0, topicID: topicID) })) {
                        ForEach(graph.facets) { Text($0.label).tag($0.id) }
                    }.labelsHidden().frame(width: 140)
                        .help(graph.facets.first(where: { $0.id == selection.facetID })?.description ?? "")
                }
                Spacer(minLength: 4)
                Menu {
                    Toggle(localization.text("graph.match_all"), isOn: Binding(
                        get: { selection.matchAll }, set: { model.setKeywordMatchAll($0, topicID: topicID) }))
                    Divider()
                    ForEach(Array(Set(graph.papers.flatMap { $0.keywords.map(\.label) })).sorted(), id: \.self) { word in
                        Toggle(word, isOn: Binding(get: { selection.keywords.contains(word) },
                            set: { _ in model.toggleKeyword(word, topicID: topicID) }))
                    }
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "tag")
                        if !selection.keywords.isEmpty { Text("\(selection.keywords.count)").monospacedDigit() }
                    }
                }.menuStyle(.borderlessButton).fixedSize()
                    .help(localization.text("graph.keywords"))
                    .accessibilityLabel(localization.text("graph.keywords"))
                TextField(localization.text("ledger.search"), text: Binding(
                    get: { selection.query }, set: { model.setGraphQuery($0, topicID: topicID) }))
                    .textFieldStyle(.roundedBorder).frame(minWidth: 96, maxWidth: 180)
            }
        }
    }
}
