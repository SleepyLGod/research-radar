import Foundation

/// Durable-state names follow JSONCoding; wire names are translated only at the bridge boundary.
public struct OrganizationJobScopeV1: Codable, Equatable, Sendable {
    public struct Report: Codable, Equatable, Sendable {
        public let reportID: UUID
        public let reportDate: String
        public let runDirectory: String
    }
    public let topicID: String
    public let reports: [Report]
    public let researchQuestion: String
    public let language: ReportLanguageV1

    public init(payload: OrganizeTopicPayloadV1) {
        topicID = payload.topicID; researchQuestion = payload.researchQuestion; language = payload.language
        reports = payload.reports.map { .init(reportID: $0.reportID, reportDate: $0.reportDate, runDirectory: $0.runDirectory) }
    }
    public var payload: OrganizeTopicPayloadV1 {
        .init(topicID: topicID, reports: reports.map {
            .init(reportID: $0.reportID, reportDate: $0.reportDate, runDirectory: $0.runDirectory)
        }, researchQuestion: researchQuestion, language: language)
    }
}

/// Immutable input scope for an explicit organization, not a new research request.
public struct OrganizeTopicPayloadV1: Codable, Equatable, Sendable {
    public let topicID: String
    public let reports: [LedgerReportReferenceV1]
    public let researchQuestion: String
    public let language: ReportLanguageV1

    public init(topicID: String, reports: [LedgerReportReferenceV1], researchQuestion: String,
                language: ReportLanguageV1) {
        self.topicID = topicID; self.reports = reports
        self.researchQuestion = researchQuestion; self.language = language
    }
    public func validate() throws {
        guard !topicID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !researchQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              researchQuestion.count <= 10_000, !reports.isEmpty,
              Set(reports.map(\.reportID)).count == reports.count,
              reports.allSatisfy({ $0.runDirectory.hasPrefix("/") && !$0.reportDate.isEmpty })
        else { throw EngineProtocolError.invalidValue }
    }
    private enum CodingKeys: String, CodingKey {
        case topicID = "topic_id", researchQuestion = "research_question", reports, language
    }
}

public struct ReadTopicKnowledgePayloadV1: Codable, Equatable, Sendable {
    public let topicID: String
    public init(topicID: String) { self.topicID = topicID }
    private enum CodingKeys: String, CodingKey { case topicID = "topic_id" }
}

/// Read-only projection; Python remains the source of the immutable knowledge snapshot.
public struct TopicKnowledgeV1: Codable, Equatable, Sendable {
    public let topicID: String
    public let current: KnowledgeSummaryV1?
    public let graph: KnowledgeGraphV1?
    public init(topicID: String, current: KnowledgeSummaryV1?, graph: KnowledgeGraphV1? = nil) {
        self.topicID = topicID; self.current = current; self.graph = graph
    }
    private enum CodingKeys: String, CodingKey { case topicID = "topic_id", current, graph }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(topicID, forKey: .topicID); try c.encode(current, forKey: .current)
        try c.encodeIfPresent(graph, forKey: .graph)
    }
}

public struct KnowledgeSummaryV1: Codable, Equatable, Sendable {
    public let snapshotID: String
    public let createdAt: String
    public let inputFingerprint: String
    public let reportIDs: [UUID]
    public let provider: String
    public let model: String
    public let paperCount: Int
    public let featureCount: Int
    public let groupCount: Int
    public let relationCount: Int

    public init(snapshotID: String, createdAt: String, inputFingerprint: String, reportIDs: [UUID],
                provider: String, model: String, paperCount: Int, featureCount: Int,
                groupCount: Int, relationCount: Int) {
        self.snapshotID = snapshotID; self.createdAt = createdAt
        self.inputFingerprint = inputFingerprint; self.reportIDs = reportIDs
        self.provider = provider; self.model = model; self.paperCount = paperCount
        self.featureCount = featureCount; self.groupCount = groupCount; self.relationCount = relationCount
    }
    private enum CodingKeys: String, CodingKey {
        case snapshotID = "snapshot_id", createdAt = "created_at", inputFingerprint = "input_fingerprint"
        case reportIDs = "report_ids", provider, model, paperCount = "paper_count"
        case featureCount = "feature_count", groupCount = "group_count", relationCount = "relation_count"
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(snapshotID, forKey: .snapshotID); try c.encode(createdAt, forKey: .createdAt)
        try c.encode(inputFingerprint, forKey: .inputFingerprint)
        try c.encode(reportIDs.map { $0.uuidString.lowercased() }, forKey: .reportIDs)
        try c.encode(provider, forKey: .provider); try c.encode(model, forKey: .model)
        try c.encode(paperCount, forKey: .paperCount); try c.encode(featureCount, forKey: .featureCount)
        try c.encode(groupCount, forKey: .groupCount); try c.encode(relationCount, forKey: .relationCount)
    }
}
