import Foundation

/// A local comparison of saved public materials, not an inference or a paper-quality score.
public struct KnowledgeCoverageV1: Codable, Equatable, Sendable {
    public enum Status: String, Codable, Sendable { case current, changes, unorganized, unknown }
    public struct Paper: Codable, Equatable, Identifiable, Sendable {
        public enum Status: String, Codable, Sendable {
            case included, updated, removed
            case newPaper = "new_paper", newVersion = "new_version"
            public var localizationKey: String { "knowledge.coverage.\(rawValue)" }
        }
        public let paperKey: String
        public let paperID: String
        public let version: String?
        public let title: String
        public let status: Status
        public let reportIDs: [UUID]
        public var id: String { paperKey }
        public init(paperKey: String, paperID: String, version: String?, title: String,
                    status: Status, reportIDs: [UUID]) {
            self.paperKey = paperKey; self.paperID = paperID; self.version = version
            self.title = title; self.status = status; self.reportIDs = reportIDs
        }
        private enum CodingKeys: String, CodingKey {
            case paperKey = "paper_key", paperID = "paper_id", version, title, status, reportIDs = "report_ids"
        }
        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(paperKey, forKey: .paperKey); try c.encode(paperID, forKey: .paperID)
            try c.encode(version, forKey: .version); try c.encode(title, forKey: .title)
            try c.encode(status, forKey: .status); try c.encode(reportIDs, forKey: .reportIDs)
        }
    }
    public let status: Status
    public let papers: [Paper]
    public init(status: Status, papers: [Paper]) { self.status = status; self.papers = papers }
    public var changes: [Paper] { papers.filter { $0.status != .included } }
    public var newCount: Int { papers.filter { $0.status == .newPaper || $0.status == .newVersion }.count }
    public var updatedCount: Int { papers.filter { $0.status == .updated }.count }
    public var removedCount: Int { papers.filter { $0.status == .removed }.count }
    public var needsUpdate: Bool { status == .changes }

    public func validate() throws {
        guard Set(papers.map(\.paperKey)).count == papers.count,
              papers.allSatisfy({ paper in
                  [paper.paperKey, paper.paperID].allSatisfy {
                      $0.count == 64 && $0.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
                  } && !paper.title.isEmpty && paper.version.map { !$0.isEmpty } != false
                    && !paper.reportIDs.isEmpty && Set(paper.reportIDs).count == paper.reportIDs.count
              }),
              status != .unknown || papers.isEmpty,
              status != .current || changes.isEmpty,
              status != .changes || !changes.isEmpty,
              status != .unorganized || papers.allSatisfy({ $0.status == .newPaper })
        else { throw EngineProtocolError.invalidValue }
    }
}
