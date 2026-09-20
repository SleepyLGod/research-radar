import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct ReportIndexStoreTests {
    @Test func upsertsBeforeUpdatingIndependentDeliveries() async throws {
        let root = try makeTemporaryDirectory(prefix: "report-index")
        defer { try? trash(root) }
        let store = ReportIndexStore(store: AtomicJSONStore(root: root))
        let report = sampleReport()

        try await store.upsert(report)
        try await store.updateDelivery(
            reportID: report.id, channel: .wechat, state: .created, error: nil,
            at: Date(timeIntervalSince1970: 20)
        )

        let reports = await store.reports()
        #expect(reports.count == 1)
        #expect(reports[0].deliveries.first(where: { $0.channel == .wechat })?.state == .created)
        #expect(reports[0].deliveries.first(where: { $0.channel == .email })?.state == .pending)
    }

    @Test func missingReportOrChannelFailsExplicitly() async throws {
        let root = try makeTemporaryDirectory(prefix: "report-index-missing")
        defer { try? trash(root) }
        let store = ReportIndexStore(store: AtomicJSONStore(root: root))
        let report = sampleReport()

        await #expect(throws: ReportIndexStoreError.reportNotFound) {
            try await store.updateDelivery(
                reportID: report.id,
                channel: .wechat,
                state: .created,
                error: nil,
                at: .now
            )
        }
        try await store.upsert(report)
        var reportWithoutEmail = report
        reportWithoutEmail.deliveries.removeAll { $0.channel == .email }
        try await store.upsert(reportWithoutEmail)
        await #expect(throws: ReportIndexStoreError.deliveryNotFound) {
            try await store.updateDelivery(
                reportID: report.id,
                channel: .email,
                state: .sent,
                error: nil,
                at: .now
            )
        }
    }

    private func sampleReport() -> ReportRecordV1 {
        ReportRecordV1(
            schemaVersion: 1, id: UUID(), topicID: "memory", reportDate: "2026-08-30",
            runDirectory: "/app/runs/one", articleDraftPath: "/app/runs/one/article_draft.json",
            reportHTMLPath: "/app/runs/one/wechat.html", title: "Report", summary: "Summary",
            sourceCount: 2, deepReadCount: 1, publishableClaimCount: 3,
            deliveries: [
                DeliveryRecordV1(channel: .wechat, state: .pending, lastAttemptAt: nil, completedAt: nil, error: nil),
                DeliveryRecordV1(channel: .email, state: .pending, lastAttemptAt: nil, completedAt: nil, error: nil),
            ], createdAt: Date(timeIntervalSince1970: 10)
        )
    }
}

private func makeTemporaryDirectory(prefix: String) throws -> URL {
    let url = FileManager.default.temporaryDirectory.appending(path: "\(prefix)-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
    return url
}

private func trash(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
