import ResearchRadarCore
import SwiftUI

struct KnowledgeRelationView: View {
    let topicID: String
    let model: TopicKnowledgeModel
    let graph: KnowledgeGraphV1
    let localization: LocalizationStore
    var availableReferences: Set<String> = []
    var openEvidence: ((KnowledgeReferenceV1) -> Void)? = nil

    private var selection: KnowledgeGraphSelection { model.graphSelection(for: topicID) }
    private var papers: [KnowledgePaperV1] { model.visibleRelationPapers(for: topicID) }
    private var relations: [KnowledgeRelationV1] { model.visibleRelations(for: topicID) }
    private var selectedRelation: KnowledgeRelationV1? { relations.first { $0.id == selection.relationID } }

    var body: some View {
        VStack(spacing: 0) {
            if papers.isEmpty {
                WorkspaceEmptyState(title: localization.text("graph.no_match"), symbol: "line.3.horizontal.decrease",
                    clearTitle: localization.text("action.clear_filters"), clearFilters: {
                        model.clearGraphFilters(topicID: topicID)
                    })
            } else {
                HStack(spacing: 0) {
                    KnowledgeRelationCanvas(papers: papers, relations: relations,
                        camera: Binding(get: { selection.relationCamera },
                            set: { model.setRelationCamera($0, topicID: topicID) }),
                        selectedRelationID: selectedRelation?.id, focusedPaperKey: selection.focusedRelationPaperKey,
                        localization: localization, selectPaper: { id in
                            model.focusRelationPaper(id, topicID: topicID)
                            model.selectGraphPaper(id, topicID: topicID)
                        }, selectRelation: { model.selectRelation($0, topicID: topicID) })
                    if let relation = selectedRelation {
                        Divider()
                        KnowledgeRelationDetailView(relation: relation, graph: graph, localization: localization,
                            availableReferences: availableReferences, openEvidence: openEvidence,
                            selectPaper: { model.selectGraphPaper($0, topicID: topicID) },
                            close: { model.selectRelation(nil, topicID: topicID) })
                            .frame(width: 300)
                    }
                }
            }
            Divider()
            HStack(spacing: 4) {
                ForEach(KnowledgeRelationV1.Kind.allCases, id: \.self) { kind in
                    Button { model.toggleRelationKind(kind, topicID: topicID) } label: {
                        HStack(spacing: 5) {
                            Rectangle().fill(kind.tint).frame(width: 14, height: 2)
                            Text(localization.text("graph.relation_kind.\(kind.rawValue)"))
                        }.opacity(selection.relationKinds.contains(kind) ? 1 : 0.4)
                    }.buttonStyle(.borderless)
                        .accessibilityAddTraits(selection.relationKinds.contains(kind) ? .isSelected : [])
                }
                Spacer(minLength: 0)
                Text("\(papers.count) / \(relations.count)").monospacedDigit().foregroundStyle(.secondary)
                    .help(localization.text("graph.relation_counts"))
            }.font(.system(size: 12)).controlSize(.small).padding(.horizontal, 12).padding(.vertical, 9)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: .textBackgroundColor))
    }
}

private struct KnowledgeRelationDetailView: View {
    let relation: KnowledgeRelationV1
    let graph: KnowledgeGraphV1
    let localization: LocalizationStore
    let availableReferences: Set<String>
    let openEvidence: ((KnowledgeReferenceV1) -> Void)?
    let selectPaper: (String) -> Void
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(localization.text("graph.relation_details")).foregroundStyle(.secondary)
                Spacer()
                Button(action: close) { Image(systemName: "xmark") }
                    .help(localization.text("action.close"))
                    .accessibilityLabel(localization.text("action.close"))
            }.font(.system(size: 12)).buttonStyle(.borderless).padding(12)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(localization.text("graph.relation_kind.\(relation.kind.rawValue)"))
                        .font(.system(size: 17, weight: .semibold))
                    Text(localization.text("graph.basis.\(relation.basis.rawValue)"))
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                    Text(relation.reason).font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
                    ForEach([relation.source, relation.target], id: \.self) { id in
                        if let paper = graph.papers.first(where: { $0.id == id }) {
                            Divider()
                            Button { selectPaper(id) } label: {
                                HStack(alignment: .top) {
                                    Text(paper.title).font(.system(size: 14, weight: .semibold))
                                        .fixedSize(horizontal: false, vertical: true)
                                    Spacer(minLength: 4)
                                    Image(systemName: "chevron.right")
                                }.frame(maxWidth: .infinity, alignment: .leading)
                            }.buttonStyle(.plain).help(localization.text("paper.open"))
                            if let version = paper.version {
                                Text(version).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                            }
                            KnowledgeReferencesView(ids: graph.references.filter {
                                $0.paperKey == id && relation.refIDs.contains($0.id)
                            }.map(\.id), graph: graph, localization: localization,
                                initiallyExpanded: true, availableReferences: availableReferences, openEvidence: openEvidence)
                        }
                    }
                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

extension KnowledgeRelationV1.Kind {
    var tint: Color {
        switch self {
        case .sharedProblem: .blue
        case .relatedMechanism: .teal
        case .differentAssumption: .orange
        case .sharedEvaluation: .pink
        }
    }
}
