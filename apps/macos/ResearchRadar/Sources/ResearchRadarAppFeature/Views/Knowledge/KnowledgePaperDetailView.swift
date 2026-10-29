import ResearchRadarCore
import SwiftUI

struct KnowledgePaperDetailView: View {
    let paper: KnowledgePaperV1
    let graph: KnowledgeGraphV1
    let localization: LocalizationStore
    let back: () -> Void
    let openHistory: (() -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: back) { Label(localization.text("action.back"), systemImage: "chevron.left") }
                Spacer()
                Button { openHistory?() } label: {
                    Label(localization.text("graph.history"), systemImage: "clock.arrow.circlepath")
                }.disabled(openHistory == nil)
                    .help(localization.text(openHistory == nil ? "graph.history_unavailable" : "graph.history"))
            }.controlSize(.small).padding(.horizontal, 20).padding(.vertical, 12)
            Divider()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(paper.title).font(.system(size: 20, weight: .semibold))
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        if let version = paper.version { Text(version).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary) }
                        ForEach(Array(paper.keywords.enumerated()), id: \.offset) { _, keyword in
                            KnowledgeReferencesView(ids: keyword.refIDs, graph: graph,
                                localization: localization, label: keyword.label)
                        }
                    }
                    ForEach(graph.groups.filter { $0.members.contains { $0.paperKey == paper.id } }) { group in
                        if let member = group.members.first(where: { $0.paperKey == paper.id }) {
                            VStack(alignment: .leading, spacing: 10) {
                                Divider()
                                HStack {
                                    Text(group.label).font(.system(size: 15, weight: .semibold))
                                    Spacer()
                                    Text(localization.text("graph.group_interpretation")).font(.system(size: 12)).foregroundStyle(.secondary)
                                }
                                Text(member.reason).font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
                                KnowledgeReferencesView(ids: member.refIDs, graph: graph, localization: localization)
                            }
                        }
                    }
                    ForEach(Array(paper.features.enumerated()), id: \.offset) { _, feature in
                        VStack(alignment: .leading, spacing: 10) {
                            Divider()
                            HStack(alignment: .firstTextBaseline) {
                                Text(feature.name).font(.system(size: 15, weight: .semibold))
                                Spacer()
                                Text(localization.text("graph.basis.\(feature.basis.rawValue)"))
                                    .font(.system(size: 12)).foregroundStyle(.secondary)
                            }
                            Text(feature.value ?? feature.missingReason ?? "")
                                .font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
                            if !feature.refIDs.isEmpty {
                                KnowledgeReferencesView(ids: feature.refIDs, graph: graph, localization: localization)
                            }
                        }
                    }
                }.frame(maxWidth: 700, alignment: .leading).padding(20).frame(maxWidth: .infinity, alignment: .top)
            }
        }
    }
}

struct KnowledgeReferencesView: View {
    let ids: [String]
    let graph: KnowledgeGraphV1
    let localization: LocalizationStore
    var label: String?
    var availableReferences: Set<String> = []
    var openEvidence: ((KnowledgeReferenceV1) -> Void)? = nil
    @State private var expanded: Bool

    init(ids: [String], graph: KnowledgeGraphV1, localization: LocalizationStore, label: String? = nil,
         initiallyExpanded: Bool = false, availableReferences: Set<String> = [],
         openEvidence: ((KnowledgeReferenceV1) -> Void)? = nil) {
        self.ids = ids; self.graph = graph; self.localization = localization; self.label = label
        self.availableReferences = availableReferences; self.openEvidence = openEvidence
        _expanded = State(initialValue: initiallyExpanded)
    }

    var body: some View {
        DisclosureGroup(label ?? localization.text("graph.evidence"), isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(graph.references.filter { ids.contains($0.id) }) { reference in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(reference.reportDate).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                        Text(reference.text).font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
                        if let openEvidence {
                            Button { openEvidence(reference) } label: {
                                Label(localization.text("graph.open_report_evidence"), systemImage: "doc.text.magnifyingglass")
                            }.disabled(!availableReferences.contains(reference.id))
                                .help(localization.text(availableReferences.contains(reference.id)
                                    ? "graph.open_report_evidence" : "graph.history_unavailable"))
                        }
                        ForEach(Array(reference.evidence.enumerated()), id: \.offset) { _, evidence in
                            VStack(alignment: .leading, spacing: 8) {
                                Text(evidence.location).font(.system(size: 12)).foregroundStyle(.secondary)
                                Text(evidence.quote).font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
                                if let url = URL(string: evidence.sourceURL) {
                                    Link(destination: url) { Label(localization.text("paper.original"), systemImage: "arrow.up.right") }
                                        .font(.system(size: 13))
                                }
                            }.padding(.leading, 10)
                                .overlay(alignment: .leading) { Rectangle().fill(.secondary.opacity(0.3)).frame(width: 2) }
                        }
                    }
                }
            }.padding(.top, 10).frame(maxWidth: .infinity, alignment: .leading)
        }.font(.system(size: 13))
    }
}
