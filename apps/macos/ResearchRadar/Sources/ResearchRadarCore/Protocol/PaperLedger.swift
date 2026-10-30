import Foundation

/// A rebuildable projection of immutable public reports, not a research database.
public struct TopicPaperLedgerV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let topicID: String
    public let reportIDs: [UUID]
    public let papers: [LedgerPaperV1]
    public let unavailableReports: [UUID]

    public init(schemaVersion: Int = 1, topicID: String, reportIDs: [UUID],
                papers: [LedgerPaperV1], unavailableReports: [UUID] = []) {
        self.schemaVersion = schemaVersion; self.topicID = topicID; self.reportIDs = reportIDs
        self.papers = papers; self.unavailableReports = unavailableReports
    }
    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", topicID = "topic_id", reportIDs = "report_ids"
        case papers, unavailableReports = "unavailable_reports"
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(schemaVersion, forKey: .schemaVersion); try c.encode(topicID, forKey: .topicID)
        try c.encode(reportIDs.map { $0.uuidString.lowercased() }, forKey: .reportIDs)
        try c.encode(papers, forKey: .papers)
        try c.encode(unavailableReports.map { $0.uuidString.lowercased() }, forKey: .unavailableReports)
    }
}

public struct LedgerPaperV1: Codable, Equatable, Sendable, Identifiable {
    public let paperID: String
    public let title: String
    public let occurrences: [PaperOccurrenceV1]
    public var id: String { paperID }
    public var firstIncluded: String? { occurrences.map(\.reportDate).min() }
    public var lastIncluded: String? { occurrences.map(\.reportDate).max() }
    public var hasPublicReading: Bool { occurrences.contains { $0.paperIndex != nil } }

    public init(paperID: String, title: String, occurrences: [PaperOccurrenceV1]) {
        self.paperID = paperID; self.title = title; self.occurrences = occurrences
    }
    private enum CodingKeys: String, CodingKey { case paperID = "paper_id", title, occurrences }
}

public struct PaperOccurrenceV1: Codable, Equatable, Sendable, Identifiable {
    public let occurrenceID: String
    public let reportID: UUID
    public let reportDate: String
    public let version: String?
    public let sourceURL: String
    public let title: String
    public let paperIndex: Int?
    public var id: String { occurrenceID }

    public init(occurrenceID: String, reportID: UUID, reportDate: String, version: String?,
                sourceURL: String, title: String, paperIndex: Int?) {
        self.occurrenceID = occurrenceID; self.reportID = reportID; self.reportDate = reportDate
        self.version = version; self.sourceURL = sourceURL; self.title = title; self.paperIndex = paperIndex
    }
    private enum CodingKeys: String, CodingKey {
        case occurrenceID = "occurrence_id", reportID = "report_id", reportDate = "report_date"
        case version, sourceURL = "source_url", title, paperIndex = "paper_index"
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(occurrenceID, forKey: .occurrenceID)
        try c.encode(reportID.uuidString.lowercased(), forKey: .reportID)
        try c.encode(reportDate, forKey: .reportDate); try c.encode(version, forKey: .version)
        try c.encode(sourceURL, forKey: .sourceURL); try c.encode(title, forKey: .title)
        try c.encode(paperIndex, forKey: .paperIndex)
    }
}

public struct LedgerReportReferenceV1: Codable, Equatable, Sendable {
    public let reportID: UUID
    public let reportDate: String
    public let runDirectory: String

    public init(reportID: UUID, reportDate: String, runDirectory: String) {
        self.reportID = reportID; self.reportDate = reportDate; self.runDirectory = runDirectory
    }
    private enum CodingKeys: String, CodingKey {
        case reportID = "report_id", reportDate = "report_date", runDirectory = "run_dir"
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(reportID.uuidString.lowercased(), forKey: .reportID)
        try c.encode(reportDate, forKey: .reportDate); try c.encode(runDirectory, forKey: .runDirectory)
    }
}

public struct ReadPaperLedgerPayloadV1: Codable, Equatable, Sendable {
    public let topicID: String
    public let reports: [LedgerReportReferenceV1]
    public init(topicID: String, reports: [LedgerReportReferenceV1]) {
        self.topicID = topicID; self.reports = reports
    }
    private enum CodingKeys: String, CodingKey { case topicID = "topic_id", reports }
}
