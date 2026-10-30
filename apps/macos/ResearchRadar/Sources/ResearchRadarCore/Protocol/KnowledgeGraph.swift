import Foundation

/// Saved organization and exact source material, never view coordinates or UI-inferred edges.
public struct KnowledgeGraphV1: Codable, Equatable, Sendable {
    public let snapshotID: String
    public let researchQuestion: String
    public let facets: [KnowledgeFacetV1]
    public let groups: [KnowledgeGroupV1]
    public let papers: [KnowledgePaperV1]
    public let relations: [KnowledgeRelationV1]
    public let references: [KnowledgeReferenceV1]
    private enum CodingKeys: String, CodingKey {
        case snapshotID = "snapshot_id", researchQuestion = "research_question", facets, groups, papers, relations, references
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        snapshotID = try c.decode(String.self, forKey: .snapshotID)
        researchQuestion = try c.decode(String.self, forKey: .researchQuestion)
        facets = try c.decode([KnowledgeFacetV1].self, forKey: .facets)
        groups = try c.decode([KnowledgeGroupV1].self, forKey: .groups)
        papers = try c.decode([KnowledgePaperV1].self, forKey: .papers)
        // Older zero-relation projections omitted this field. The codec verifies the count.
        relations = try c.decodeIfPresent([KnowledgeRelationV1].self, forKey: .relations) ?? []
        references = try c.decode([KnowledgeReferenceV1].self, forKey: .references)
    }
}

public struct KnowledgeRelationV1: Codable, Equatable, Sendable, Identifiable {
    public enum Kind: String, Codable, CaseIterable, Sendable {
        case sharedProblem = "shared_problem", relatedMechanism = "related_mechanism"
        case differentAssumption = "different_assumption", sharedEvaluation = "shared_evaluation"
    }
    public enum Basis: String, Codable, Sendable { case sourceStatement = "source_statement", synthesis }
    public let id: String
    public let source: String
    public let target: String
    public let kind: Kind
    public let basis: Basis
    public let reason: String
    public let refIDs: [String]
    private enum CodingKeys: String, CodingKey { case id, source, target, kind, basis, reason, refIDs = "ref_ids" }
}

public struct KnowledgeFacetV1: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let description: String
}

public struct KnowledgeGroupV1: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let facetID: String
    public let label: String
    public let members: [KnowledgeMembershipV1]
    private enum CodingKeys: String, CodingKey { case id, facetID = "facet_id", label, members }
}

public struct KnowledgeMembershipV1: Codable, Equatable, Sendable {
    public let paperKey: String
    public let reason: String
    public let refIDs: [String]
    private enum CodingKeys: String, CodingKey { case paperKey = "paper_key", reason, refIDs = "ref_ids" }
}

public struct KnowledgePaperV1: Codable, Equatable, Sendable, Identifiable {
    public let paperKey: String
    public let paperID: String
    public let version: String?
    public let title: String
    public let keywords: [KnowledgeKeywordV1]
    public let features: [KnowledgeFeatureV1]
    public var id: String { paperKey }
    private enum CodingKeys: String, CodingKey {
        case paperKey = "paper_key", paperID = "paper_id", version, title, keywords, features
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(paperKey, forKey: .paperKey); try c.encode(paperID, forKey: .paperID)
        try c.encode(version, forKey: .version); try c.encode(title, forKey: .title)
        try c.encode(keywords, forKey: .keywords); try c.encode(features, forKey: .features)
    }
}

public struct KnowledgeKeywordV1: Codable, Equatable, Sendable {
    public let label: String
    public let refIDs: [String]
    private enum CodingKeys: String, CodingKey { case label, refIDs = "ref_ids" }
}

public struct KnowledgeFeatureV1: Codable, Equatable, Sendable {
    public enum Basis: String, Codable, Sendable { case sourceStatement = "source_statement", synthesis, unknown }
    public let name: String
    public let value: String?
    public let basis: Basis
    public let refIDs: [String]
    public let missingReason: String?
    private enum CodingKeys: String, CodingKey {
        case name, value, basis, refIDs = "ref_ids", missingReason = "missing_reason"
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name); try c.encode(value, forKey: .value)
        try c.encode(basis, forKey: .basis); try c.encode(refIDs, forKey: .refIDs)
        try c.encode(missingReason, forKey: .missingReason)
    }
}

public struct KnowledgeReferenceV1: Codable, Equatable, Sendable, Identifiable {
    public let refID: String
    public let paperKey: String
    public let reportID: UUID
    public let reportDate: String
    public let reportSHA256: String
    public let jsonPointer: String
    public let text: String
    public let evidence: [KnowledgeEvidenceV1]
    public var id: String { refID }
    private enum CodingKeys: String, CodingKey {
        case refID = "ref_id", paperKey = "paper_key", reportID = "report_id", reportDate = "report_date"
        case reportSHA256 = "report_sha256", jsonPointer = "json_pointer", text, evidence
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(refID, forKey: .refID); try c.encode(paperKey, forKey: .paperKey)
        try c.encode(reportID.uuidString.lowercased(), forKey: .reportID)
        try c.encode(reportDate, forKey: .reportDate); try c.encode(reportSHA256, forKey: .reportSHA256)
        try c.encode(jsonPointer, forKey: .jsonPointer); try c.encode(text, forKey: .text)
        try c.encode(evidence, forKey: .evidence)
    }
}

public struct KnowledgeEvidenceV1: Codable, Equatable, Sendable {
    public let sourceURL: String
    public let quote: String
    public let location: String
    private enum CodingKeys: String, CodingKey { case sourceURL = "source_url", quote, location }
}
