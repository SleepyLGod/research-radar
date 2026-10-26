import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct TodayViewStatusTests {
    @Test(arguments: [false, true])
    func quietReportHidesRepeatedAttemptDetailsWithoutHidingChannelAttention(compact: Bool) {
        let root = FileManager.default.temporaryDirectory.appending(path: "overview-\(UUID())")
        var configuration = AppConfigurationDefaults.make(workspaceRoot: root,
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        configuration.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let report = ReportRecordV1(topicID: "memory", reportDate: ReportDate.string(for: Date()),
            runDirectory: root.path, articleDraftPath: root.appending(path: "article_draft.json").path,
            reportHTMLPath: root.appending(path: "wechat.html").path, title: "Report", summary: "Summary",
            sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1,
            deliveries: [.init(channel: .email, state: .unknown)], createdAt: Date())
        let store = AppStore(configuration: configuration, reportSnapshot: .init(reports: [report]),
            runtime: .init(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: root, secretStore: StatusFixtureSecrets(present: true))
        let view = TodayContentView(store: store, localization: LocalizationStore(), compact: compact, openReport: { _ in })
        #expect(!view.showsAttemptDetails)
        #expect(store.todayPresentation.latestReport?.deliveries.first?.state == .unknown)
        let missingCredentials = AppStore(configuration: configuration, reportSnapshot: .init(reports: [report]),
            runtime: .init(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: root, secretStore: StatusFixtureSecrets())
        #expect(TodayContentView(store: missingCredentials, localization: LocalizationStore(),
            compact: compact, openReport: { _ in }).showsAttemptDetails)
    }

    @Test(arguments: [JobState.pending, .running, .cancelling, .failed, .cancelled, .interrupted])
    func newAttemptKeepsDetailsAheadOfRetainedReport(state: JobState) throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "overview-attempt-\(UUID())")
        var configuration = AppConfigurationDefaults.make(workspaceRoot: root,
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        configuration.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .english)]
        let report = task3Report(topic: "memory", run: root.appending(path: "old"), date: 1)
        let job = try JobRecordV1(kind: .research, topicID: "memory", reportDate: ReportDate.string(for: Date()),
            trigger: .runNow, state: state, stage: .deepReading, jobDirectory: root.appending(path: "job").path,
            createdAt: Date(), error: state == .failed ? .init(code: "model_transport_failed", message: "Offline", retryable: true) : nil)
        let store = AppStore(configuration: configuration, queueSnapshot: .init(jobs: [job]),
            reportSnapshot: .init(reports: [report]),
            runtime: .init(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: root, secretStore: StatusFixtureSecrets(present: true))
        let view = TodayContentView(store: store, localization: LocalizationStore(), compact: true, openReport: { _ in })
        #expect(view.showsAttemptDetails)
        #expect(!store.todayPresentation.prefersReportFirst)
    }

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
        #expect(view.showsAttemptDetails)
    }

    @Test func deliveryAttentionStaysWithReportInsteadOfResearchHeadline() throws {
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
        #expect(view.statusKey == "today.succeeded")
        #expect(store.todayPresentation.status == .partialSuccess)
        #expect(store.todayPresentation.latestReport?.id == report.id)
        #expect(store.todayPresentation.latestReport?.deliveries.first?.state == .unknown)
    }
}

private struct StatusFixtureSecrets: SecretStoring {
    var present = false
    func set(_ value: Data, account: String) throws {}
    func read(account: String) throws -> Data? { nil }
    func contains(account: String) throws -> Bool { present }
    func remove(account: String) throws {}
}
