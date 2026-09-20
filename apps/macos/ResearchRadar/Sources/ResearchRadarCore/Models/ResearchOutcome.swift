import Foundation

public struct ResearchOutcomeV1: Codable, Equatable, Sendable {
    public enum Status: String, Codable, CaseIterable, Sendable {
        case ready
        case noNewContent = "no_new_content"
        case incomplete
    }

    public enum Reason: String, Codable, CaseIterable, Sendable {
        case noEligiblePapers = "no_eligible_papers"
        case discoveryFailed = "discovery_failed"
        case fullTextUnavailable = "full_text_unavailable"
        case readingFailed = "reading_failed"
        case evidenceInsufficient = "evidence_insufficient"
        case verificationNoPublicClaims = "verification_no_public_claims"

        public var localizationKey: String { "research_reason.\(rawValue)" }
    }

    public let status: Status
    public let reasons: [Reason]

    public init(status: Status, reasons: [Reason]) {
        self.status = status
        self.reasons = reasons
    }

    private enum CodingKeys: String, CodingKey { case status, reasons }
    private struct FieldKey: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    public init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: FieldKey.self)
        guard Set(fields.allKeys.map(\.stringValue)) == ["status", "reasons"] else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                debugDescription: "Unexpected research outcome fields."))
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try container.decode(Status.self, forKey: .status)
        reasons = try container.decode([Reason].self, forKey: .reasons)
        guard Set(reasons).count == reasons.count else {
            throw DecodingError.dataCorruptedError(forKey: .reasons, in: container,
                debugDescription: "Research outcome reasons must be unique.")
        }
    }

    public static func admitsDelivery(deepReadCount: Int, publishableClaimCount: Int,
                                      outcome: Self?) -> Bool {
        deepReadCount > 0 && publishableClaimCount > 0
            && (outcome == nil || outcome?.status == .ready)
    }
}

extension KeyedDecodingContainer {
    // Both wire and durable records permit omission, but not an explicitly malformed/null field.
    func decodeIfPresent(_ type: ResearchOutcomeV1.Type, forKey key: Key) throws -> ResearchOutcomeV1? {
        contains(key) ? try decode(type, forKey: key) : nil
    }
}
