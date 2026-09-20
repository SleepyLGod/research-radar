import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct TodayViewStatusTests {
    @Test(arguments: [ResearchOutcomeV1.Status.noNewContent, .incomplete])
    func storedOutcomeIsNotOverwrittenByCurrentConfigurationAttention(status: ResearchOutcomeV1.Status) {
        let root = FileManager.default.temporaryDirectory.appending(path: "today-outcome-\(UUID())")
        var configuration = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
        configuration.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let report = ReportRecordV1(topicID: "memory", reportDate: "2026-09-20", runDirectory: root.path,
            articleDraftPath: "/a", reportHTMLPath: "/h", title: "Empty", summary: "",
            sourceCount: 0, deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: Date(),
            researchOutcome: .init(status: status, reasons: [.noEligiblePapers]))
        let store = AppStore(configuration: configuration, reportSnapshot: .init(reports: [report]),
            runtime: .init(updatedAt: Date()), appSupportRoot: root, secretStore: StatusFixtureSecrets())
        let view = TodayContentView(store: store, localization: LocalizationStore(), compact: true, openReport: { _ in })
        #expect(view.statusKey == (status == .noNewContent ? "today.noNewContent" : "today.incomplete"))
    }

    @Test func reportReadyDoesNotHideDeliveryAttentionInHeadline() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "today-status-\(UUID())")
        var configuration = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
        configuration.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "Memory", queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let report = ReportRecordV1(topicID: "memory", reportDate: "2026-09-19", runDirectory: root.path,
            articleDraftPath: root.appending(path: "article_draft.json").path,
            reportHTMLPath: root.appending(path: "wechat.html").path, title: "Report", summary: "Summary",
            sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1,
            deliveries: [.init(channel: .email, state: .unknown)], createdAt: Date())
        let job = try JobRecordV1(kind: .delivery, topicID: "memory", reportDate: report.reportDate,
            deliveryChannel: .email, trigger: .runNow, state: .deliveryUnknown,
            jobDirectory: root.path, runDirectory: root.path, createdAt: Date())
        let store = AppStore(configuration: configuration, queueSnapshot: .init(jobs: [job]),
            reportSnapshot: .init(reports: [report]), runtime: .init(updatedAt: Date()),
            appSupportRoot: root, secretStore: StatusFixtureSecrets())
        let view = TodayContentView(store: store, localization: LocalizationStore(), compact: true, openReport: { _ in })
        #expect(view.statusKey == "today.partialSuccess")
        #expect(store.todayPresentation.latestReport?.id == report.id)
    }
}

private struct StatusFixtureSecrets: SecretStoring {
    func set(_ value: Data, account: String) throws {}
    func read(account: String) throws -> Data? { nil }
    func contains(account: String) throws -> Bool { false }
    func remove(account: String) throws {}
}
