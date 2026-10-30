import Foundation
import Observation
import ResearchRadarCore

/// Only holds topic-scoped presentation; Python validates and persists the actual snapshot.
@MainActor @Observable final class TopicKnowledgeModel {
    private var values: [String: TopicKnowledgeV1] = [:]
    private var errors: [String: String] = [:]
    private var requests: [String: UUID] = [:]
    private var selections: [String: KnowledgeGraphSelection] = [:]

    func current(for topicID: String) -> KnowledgeSummaryV1? { values[topicID]?.current }
    func error(for topicID: String) -> String? { errors[topicID] }
    func graph(for topicID: String) -> KnowledgeGraphV1? { values[topicID]?.graph }
    func graphSelection(for topicID: String) -> KnowledgeGraphSelection { selections[topicID] ?? .init() }

    func accept(_ value: TopicKnowledgeV1) {
        requests[value.topicID] = UUID()
        values[value.topicID] = value
        errors[value.topicID] = nil
        reconcileSelection(topicID: value.topicID)
    }

    func load(topicID: String, fetch: (String) async throws -> TopicKnowledgeV1) async {
        let request = UUID()
        requests[topicID] = request
        do {
            let value = try await fetch(topicID)
            guard requests[topicID] == request else { return }
            guard value.topicID == topicID else { throw EngineProtocolError.invalidValue }
            accept(value)
        } catch {
            guard requests[topicID] == request else { return }
            errors[topicID] = "knowledge.load_failed"
        }
    }

    func setGraphMode(_ mode: KnowledgeGraphSelection.Mode, topicID: String) {
        selections[topicID, default: .init()].mode = mode
    }
    func selectFacet(_ id: String?, topicID: String) {
        guard id == nil || graph(for: topicID)?.facets.contains(where: { $0.id == id }) == true else { return }
        selections[topicID, default: .init()].facetID = id
        selections[topicID, default: .init()].groupID = nil
    }
    func selectGroup(_ id: String?, topicID: String) {
        guard id == nil || visibleGraphGroups(for: topicID).contains(where: { $0.id == id }) else { return }
        selections[topicID, default: .init()].groupID = id
    }
    func selectGraphPaper(_ id: String?, topicID: String) {
        guard id == nil || graph(for: topicID)?.papers.contains(where: { $0.id == id }) == true else { return }
        selections[topicID, default: .init()].paperKey = id
    }
    func setGraphQuery(_ query: String, topicID: String) { selections[topicID, default: .init()].query = query }
    func setRelationCamera(_ camera: KnowledgeRelationCamera, topicID: String) {
        guard camera.zoom.isFinite, camera.offset.x.isFinite, camera.offset.y.isFinite else { return }
        selections[topicID, default: .init()].relationCamera = .init(
            zoom: min(2.5, max(0.6, camera.zoom)), offset: camera.offset)
    }
    func selectRelation(_ id: String?, topicID: String) {
        guard id == nil || visibleRelations(for: topicID).contains(where: { $0.id == id }) else { return }
        selections[topicID, default: .init()].relationID = id
    }
    func focusRelationPaper(_ id: String?, topicID: String) {
        guard id == nil || graph(for: topicID)?.papers.contains(where: { $0.id == id }) == true else { return }
        selections[topicID, default: .init()].focusedRelationPaperKey = id
    }
    func toggleRelationKind(_ kind: KnowledgeRelationV1.Kind, topicID: String) {
        if !selections[topicID, default: .init()].relationKinds.insert(kind).inserted {
            selections[topicID, default: .init()].relationKinds.remove(kind)
        }
    }
    func visibleRelations(for topicID: String) -> [KnowledgeRelationV1] {
        let ids = Set(visibleRelationPapers(for: topicID).map(\.id))
        let kinds = graphSelection(for: topicID).relationKinds
        return graph(for: topicID)?.relations.filter { kinds.contains($0.kind) && ids.contains($0.source) && ids.contains($0.target) } ?? []
    }
    func relationReferences(_ relation: KnowledgeRelationV1, paperKey: String, topicID: String) -> [KnowledgeReferenceV1] {
        guard [relation.source, relation.target].contains(paperKey) else { return [] }
        return graph(for: topicID)?.references.filter { $0.paperKey == paperKey && relation.refIDs.contains($0.id) } ?? []
    }
    func clearGraphFilters(topicID: String) {
        selections[topicID, default: .init()].query = ""
        selections[topicID, default: .init()].groupID = nil
        selections[topicID, default: .init()].keywords = []
    }
    func setGraphScrollPosition(_ id: String?, sectionID: String? = nil, topicID: String) {
        guard id == nil || graph(for: topicID)?.papers.contains(where: { $0.id == id }) == true else { return }
        selections[topicID, default: .init()].scrollPaperKey = id
        selections[topicID, default: .init()].scrollSectionID = id == nil ? nil : sectionID
    }
    func setKeywordMatchAll(_ all: Bool, topicID: String) { selections[topicID, default: .init()].matchAll = all }
    func toggleKeyword(_ keyword: String, topicID: String) {
        guard graph(for: topicID)?.papers.contains(where: { $0.keywords.contains(where: { $0.label == keyword }) }) == true else { return }
        if selections[topicID, default: .init()].keywords.contains(keyword) {
            selections[topicID, default: .init()].keywords.remove(keyword)
        } else { selections[topicID, default: .init()].keywords.insert(keyword) }
    }
    func visibleGraphGroups(for topicID: String) -> [KnowledgeGroupV1] {
        let selection = graphSelection(for: topicID)
        return graph(for: topicID)?.groups.filter { $0.facetID == selection.facetID } ?? []
    }
    func visibleGraphPapers(for topicID: String) -> [KnowledgePaperV1] {
        matchingPapers(for: topicID, includeGroup: true)
    }
    func visibleRelationPapers(for topicID: String) -> [KnowledgePaperV1] {
        matchingPapers(for: topicID, includeGroup: false)
    }
    private func matchingPapers(for topicID: String, includeGroup: Bool) -> [KnowledgePaperV1] {
        let selection = graphSelection(for: topicID)
        let group = includeGroup ? visibleGraphGroups(for: topicID).first { $0.id == selection.groupID } : nil
        return (graph(for: topicID)?.papers ?? []).filter { paper in
            let matchesGroup = group.map { $0.members.contains { $0.paperKey == paper.id } } ?? true
            let terms = Set(paper.keywords.map(\.label)), selected = selection.keywords
            let matchesKeywords = selected.isEmpty || (selection.matchAll ? selected.isSubset(of: terms) : !selected.isDisjoint(with: terms))
            let text = ([paper.title] + paper.keywords.map(\.label) + paper.features.compactMap(\.value)).joined(separator: "\n")
            return matchesGroup && matchesKeywords && (selection.query.isEmpty || text.localizedCaseInsensitiveContains(selection.query))
        }
    }
    func unclassifiedPaperKeys(for topicID: String) -> Set<String> {
        let grouped = Set(visibleGraphGroups(for: topicID).flatMap { $0.members.map(\.paperKey) })
        return Set((graph(for: topicID)?.papers ?? []).map(\.id)).subtracting(grouped)
    }

    private func reconcileSelection(topicID: String) {
        guard let graph = graph(for: topicID) else { selections[topicID] = .init(); return }
        var state = graphSelection(for: topicID)
        if !graph.facets.contains(where: { $0.id == state.facetID }) { state.facetID = graph.facets.first?.id; state.groupID = nil }
        if !graph.groups.contains(where: { $0.id == state.groupID && $0.facetID == state.facetID }) { state.groupID = nil }
        if !graph.papers.contains(where: { $0.id == state.paperKey }) { state.paperKey = nil }
        if !graph.relations.contains(where: { $0.id == state.relationID }) { state.relationID = nil }
        if !graph.papers.contains(where: { $0.id == state.focusedRelationPaperKey }) { state.focusedRelationPaperKey = nil }
        if !graph.papers.contains(where: { $0.id == state.scrollPaperKey }) { state.scrollPaperKey = nil }
        if state.scrollPaperKey == nil || (state.scrollSectionID != "unclassified"
            && !graph.groups.contains(where: { "group:" + $0.id == state.scrollSectionID })) { state.scrollSectionID = nil }
        state.keywords.formIntersection(Set(graph.papers.flatMap { $0.keywords.map(\.label) }))
        selections[topicID] = state
    }
}

struct KnowledgeGraphSelection {
    enum Mode: Hashable { case relations, classification, ledger }
    var mode = Mode.classification
    var facetID: String?
    var groupID: String?
    var paperKey: String?
    var scrollPaperKey: String?
    var scrollSectionID: String?
    var query = ""
    var keywords: Set<String> = []
    var matchAll = false
    var relationID: String?
    var focusedRelationPaperKey: String?
    var relationKinds = Set(KnowledgeRelationV1.Kind.allCases)
    var relationCamera = KnowledgeRelationCamera()
}

struct TopicKnowledgePresentation {
    let job: JobRecordV1?
    init(topicID: String, jobs: [JobRecordV1]) {
        job = jobs.filter { $0.kind == .organization && $0.topicID == topicID }.max {
            if $0.attemptCount != $1.attemptCount { return $0.attemptCount < $1.attemptCount }
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id.uuidString < $1.id.uuidString
        }
    }
    var isActive: Bool { job.map { [.pending, .running, .cancelling].contains($0.state) } ?? false }
    var statusKey: String? {
        guard let job else { return nil }
        switch job.state {
        case .pending: return "knowledge.queued"
        case .running: return "knowledge.running"
        case .cancelling: return "today.cancelling"
        case .succeeded, .partialSuccess: return "knowledge.ready"
        case .cancelled: return "knowledge.cancelled"
        case .interrupted: return "knowledge.interrupted"
        default: return "knowledge.failed"
        }
    }
}
