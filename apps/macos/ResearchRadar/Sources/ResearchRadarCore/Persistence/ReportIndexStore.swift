import Foundation

public enum ReportIndexStoreError: Error, Equatable, Sendable {
    case reportNotFound
    case deliveryNotFound
}

/// Persists and updates the durable report index.
public actor ReportIndexStore {
    private var index: ReportIndexV1
    private let store: AtomicJSONStore
    private let relativePath: String

    public init(
        index: ReportIndexV1 = ReportIndexV1(),
        store: AtomicJSONStore,
        relativePath: String = "state/report-index.json"
    ) {
        self.index = index
        self.store = store
        self.relativePath = relativePath
    }

    public func reports() -> [ReportRecordV1] { index.reports }

    public func upsert(_ report: ReportRecordV1) throws {
        var updated = index
        if let existing = updated.reports.firstIndex(where: { $0.id == report.id }) {
            updated.reports[existing] = report
        } else {
            updated.reports.append(report)
        }
        updated.reports.sort { $0.createdAt > $1.createdAt }
        try store.write(updated, to: relativePath)
        index = updated
    }

    public func updateDelivery(
        reportID: UUID,
        channel: DeliveryChannel,
        state: DeliveryState,
        error: RedactedEngineErrorV1?,
        at date: Date
    ) throws {
        guard let reportIndex = index.reports.firstIndex(where: { $0.id == reportID }) else {
            throw ReportIndexStoreError.reportNotFound
        }
        guard let deliveryIndex = index.reports[reportIndex].deliveries.firstIndex(where: {
            $0.channel == channel
        }) else { throw ReportIndexStoreError.deliveryNotFound }
        var updated = index
        updated.reports[reportIndex].deliveries[deliveryIndex].state = state
        updated.reports[reportIndex].deliveries[deliveryIndex].lastAttemptAt = date
        updated.reports[reportIndex].deliveries[deliveryIndex].error = error
        if state == .created || state == .sent {
            updated.reports[reportIndex].deliveries[deliveryIndex].completedAt = date
        }
        try store.write(updated, to: relativePath)
        index = updated
    }

    public func updateDelivery(
        runDirectory: String,
        channel: DeliveryChannel,
        state: DeliveryState,
        error: RedactedEngineErrorV1?,
        at date: Date
    ) throws {
        guard let report = index.reports.first(where: { $0.runDirectory == runDirectory }) else {
            throw ReportIndexStoreError.reportNotFound
        }
        try updateDelivery(reportID: report.id, channel: channel, state: state, error: error, at: date)
    }
}
