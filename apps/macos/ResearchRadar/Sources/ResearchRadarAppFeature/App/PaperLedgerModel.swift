import Foundation
import Observation
import ResearchRadarCore

struct PaperLedgerEntry: Equatable {
    let reportID: UUID
    let paperIndex: Int?
    let sourceURL: String
    let evidence: Bool
    var reportSHA256: String? = nil
    var evidenceClaimIndex: Int? = nil
}

struct KnowledgeEvidenceTarget {
    let occurrence: PaperOccurrenceV1
    let reference: KnowledgeReferenceV1
}

/// Keeps only presentation state; Python alone assigns paper and occurrence identity.
@MainActor @Observable final class PaperLedgerModel {
    enum Filter: String, CaseIterable { case all, publicReading, sourceOnly }
    private struct TopicState {
        var reports: [LedgerReportReferenceV1] = []
        var snapshot: TopicPaperLedgerV1?
        var query = ""
        var filter = Filter.all
        var selectedID: String?
    }
    private var topics: [String: TopicState] = [:]
    private var generation = UUID()
    private var topicRequests: [String: UUID] = [:]
    private var pending: [String: (id: UUID, reports: [LedgerReportReferenceV1])] = [:]
    private var deferredTopicID: String?
    private(set) var topicID: String?
    private(set) var loading = false
    private(set) var errorKey: String?
    var snapshot: TopicPaperLedgerV1? { topicID.flatMap { topics[$0]?.snapshot } }
    var query: String { topicID.flatMap { topics[$0]?.query } ?? "" }
    var filter: Filter { topicID.flatMap { topics[$0]?.filter } ?? .all }
    var selectedPaper: LedgerPaperV1? {
        guard let topicID, let id = topics[topicID]?.selectedID else { return nil }
        return snapshot?.papers.first { $0.id == id }
    }
    var papers: [LedgerPaperV1] {
        (snapshot?.papers ?? []).filter { paper in
            (filter == .all || (filter == .publicReading ? paper.hasPublicReading : !paper.hasPublicReading))
            && (query.isEmpty || paper.title.localizedCaseInsensitiveContains(query))
        }
    }
    func deferLoad(for topicID: String?) { deferredTopicID = topicID }
    func takeDeferredLoad(topicID: String?, visible: Bool) -> Bool {
        guard visible, let topicID, deferredTopicID == topicID else { return false }
        deferredTopicID = nil
        return true
    }
    func select(_ id: String?) { if let topicID { topics[topicID, default: .init()].selectedID = id } }
    func setQuery(_ value: String) { if let topicID { topics[topicID, default: .init()].query = value } }
    func setFilter(_ value: Filter) { if let topicID { topics[topicID, default: .init()].filter = value } }

    func evidenceTarget(reference: KnowledgeReferenceV1, graph: KnowledgeGraphV1) -> KnowledgeEvidenceTarget? {
        guard let paper = graph.papers.first(where: { $0.id == reference.paperKey }),
              let occurrence = snapshot?.papers.first(where: { $0.id == paper.paperID })?.occurrences.first(where: { occurrence in
                  occurrence.reportID == reference.reportID && occurrence.version == paper.version && occurrence.paperIndex != nil
              }) else { return nil }
        return .init(occurrence: occurrence, reference: reference)
    }

    func load(topicID: String, reports: [LedgerReportReferenceV1], force: Bool = false,
              fetch: (String, [LedgerReportReferenceV1]) async throws -> TopicPaperLedgerV1) async {
        let request = UUID()
        generation = request; self.topicID = topicID; errorKey = nil; loading = false
        let references = reports.sorted { $0.reportID.uuidString < $1.reportID.uuidString }
        if let active = pending[topicID], active.reports == references {
            generation = active.id; loading = true
            return
        }
        if !force, topics[topicID]?.snapshot != nil, topics[topicID]?.reports == references {
            topicRequests[topicID] = request
            return
        }
        topicRequests[topicID] = request
        pending[topicID] = (request, references)
        loading = true
        defer {
            if pending[topicID]?.id == request { pending[topicID] = nil }
            if generation == request { loading = false }
        }
        do {
            let value = try await fetch(topicID, references)
            guard topicRequests[topicID] == request else { return }
            guard value.topicID == topicID else { throw EngineProtocolError.invalidValue }
            topics[topicID, default: .init()].snapshot = value
            topics[topicID, default: .init()].reports = references
        } catch {
            guard generation == request else { return }
            errorKey = (error as? AppStoreError) == .busy ? "ledger.busy" : "ledger.load_failed"
        }
    }
}
