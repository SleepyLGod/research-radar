import Foundation

public struct DeliveryRecordV1: Codable, Equatable, Sendable {
    public let channel: DeliveryChannel
    public var state: DeliveryState
    public var lastAttemptAt: Date?
    public var completedAt: Date?
    public var error: RedactedEngineErrorV1?

    public init(
        channel: DeliveryChannel, state: DeliveryState, lastAttemptAt: Date? = nil,
        completedAt: Date? = nil, error: RedactedEngineErrorV1? = nil
    ) {
        self.channel = channel; self.state = state; self.lastAttemptAt = lastAttemptAt
        self.completedAt = completedAt; self.error = error
    }
}

public struct ReportRecordV1: Codable, Equatable, Identifiable, Sendable {
    public let schemaVersion: Int
    public let id: UUID
    public let topicID: String
    public let reportDate: String
    public let runDirectory: String
    public let articleDraftPath: String
    public let reportHTMLPath: String
    public let title: String
    public let summary: String
    public let sourceCount: Int
    public let deepReadCount: Int
    public let publishableClaimCount: Int
    public var deliveries: [DeliveryRecordV1]
    public let createdAt: Date

    public init(
        schemaVersion: Int = 1, id: UUID = UUID(), topicID: String, reportDate: String,
        runDirectory: String, articleDraftPath: String, reportHTMLPath: String,
        title: String, summary: String, sourceCount: Int, deepReadCount: Int,
        publishableClaimCount: Int, deliveries: [DeliveryRecordV1], createdAt: Date
    ) {
        self.schemaVersion = schemaVersion; self.id = id; self.topicID = topicID
        self.reportDate = reportDate; self.runDirectory = runDirectory
        self.articleDraftPath = articleDraftPath; self.reportHTMLPath = reportHTMLPath
        self.title = title; self.summary = summary; self.sourceCount = sourceCount
        self.deepReadCount = deepReadCount; self.publishableClaimCount = publishableClaimCount
        self.deliveries = deliveries; self.createdAt = createdAt
    }
}

public struct ReportIndexV1: Codable, Equatable, Sendable, ValidatableDurableState {
    public let schemaVersion: Int
    public var reports: [ReportRecordV1]

    public init(schemaVersion: Int = 1, reports: [ReportRecordV1] = []) {
        self.schemaVersion = schemaVersion
        self.reports = reports
    }

    public func validate() throws {
        guard Set(reports.map(\.id)).count == reports.count,
              Set(reports.map(\.runDirectory)).count == reports.count
        else { throw DurableStateValidationError.duplicateIdentifier }
        for report in reports {
            guard report.schemaVersion == 1,
                  !report.topicID.isEmpty,
                  !report.reportDate.isEmpty,
                  !report.runDirectory.isEmpty,
                  !report.articleDraftPath.isEmpty,
                  !report.reportHTMLPath.isEmpty,
                  report.sourceCount >= 0,
                  report.deepReadCount >= 0,
                  report.publishableClaimCount >= 0,
                  Set(report.deliveries.map(\.channel)).count == report.deliveries.count
            else { throw DurableStateValidationError.invalidValue }
        }
    }
}

public struct StorageUsageSnapshot: Equatable, Sendable {
    public let modelCacheBytes: UInt64
    public let reportsBytes: UInt64
    public let jobDiagnosticsBytes: UInt64
    public let totalBytes: UInt64
    public let measuredAt: Date

    public init(
        modelCacheBytes: UInt64, reportsBytes: UInt64, jobDiagnosticsBytes: UInt64,
        totalBytes: UInt64, measuredAt: Date
    ) {
        self.modelCacheBytes = modelCacheBytes; self.reportsBytes = reportsBytes
        self.jobDiagnosticsBytes = jobDiagnosticsBytes; self.totalBytes = totalBytes
        self.measuredAt = measuredAt
    }
}
