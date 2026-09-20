import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct TodayResearchFailureTests {
    @Test func newerSuccessfulResearchClearsTheFailureButNotOtherTopicState() throws {
        let failed = try research(code: "model_response_retry_exhausted", stage: .sourceGist)
        var succeeded = try research(code: nil, stage: .complete)
        succeeded.state = .succeeded
        succeeded.createdAt = Date(timeIntervalSince1970: 30)
        let report = task3Report(topic: "one", run: URL(fileURLWithPath: "/tmp/new"), date: 31)
        let other = try JobRecordV1(kind: .research, topicID: "two", reportDate: "2026-09-19",
            trigger: .runNow, state: .failed, stage: .sourceGist, jobDirectory: "/tmp/other",
            createdAt: Date(timeIntervalSince1970: 40))
        let model = projection(jobs: [other, succeeded, failed], reports: [report])
        #expect(model.status == .succeeded)
        #expect(model.failureCode == nil)
        #expect(model.researchFailureTime == nil)
        #expect(model.latestResearchJob?.id == succeeded.id)
        #expect(model.latestReport?.id == report.id)
    }

    @Test func anotherActiveTopicCannotOfferUnconfirmedRetry() throws {
        let failed = try research(code: "model_response_retry_exhausted", stage: .sourceGist)
        let other = try JobRecordV1(kind: .research, topicID: "two", reportDate: "2026-09-19",
            trigger: .runNow, state: .running, stage: .deepReading, jobDirectory: "/tmp/other",
            createdAt: Date(timeIntervalSince1970: 40))
        #expect(projection(jobs: [other, failed]).otherActiveTopicID == "two")
        #expect(!projection(jobs: [other, failed]).canQueueResearch)
        #expect(projection(jobs: [other]).canQueueResearch)
    }

    @Test func newerDeliveryCannotHideLatestResearchFailureOrReplaceSuccessfulReport() throws {
        let failed = try research(code: "model_response_retry_exhausted", stage: .sourceGist)
        let delivery = try JobRecordV1(kind: .delivery, topicID: "one", reportDate: "2026-09-19",
            deliveryChannel: .email, trigger: .retry, state: .failed, jobDirectory: "/tmp/delivery",
            createdAt: Date(timeIntervalSince1970: 30),
            error: .init(code: "delivery_failed", message: "private delivery details", retryable: true))
        let report = task3Report(topic: "one", run: URL(fileURLWithPath: "/tmp/old"), date: 1)
        let model = projection(jobs: [delivery, failed], reports: [report])
        #expect(model.status == .failed)
        #expect(model.job?.id == failed.id)
        #expect(model.failureCode == "model_response_retry_exhausted")
        #expect(model.stage == .discovery)
        #expect(model.latestResearchJob?.completedAt == Date(timeIntervalSince1970: 22))
        #expect(model.latestResearchJob?.error == nil)
        #expect(model.latestReport?.id == report.id)
        #expect(model.latestReport?.sourceCount == 1)
        #expect(model.researchFailureStageKey == "failure_stage.source_gist")
        #expect(model.researchFailureTime == Date(timeIntervalSince1970: 22))
    }

    @Test func legacyFailureDoesNotClaimAStageFromOldOrMessageData() throws {
        let failed = try research(code: "research_failed", stage: .deepReading)
        #expect(JobPresentation(job: failed).stage == nil)
        #expect(projection(jobs: [failed]).stage == nil)
        #expect(projection(jobs: [failed]).failureCode == "research_failed")
        #expect(projection(jobs: [failed]).researchFailureStageKey == nil)
    }

    @Test(arguments: ["engine_crashed", "cancelled", "parent_lost", "future_error"])
    func legacyTerminalStageIsNotTreatedAsObservedProgress(code: String) throws {
        let failed = try research(code: code, stage: .discovery)
        #expect(JobPresentation(job: failed).stage == nil)
        #expect(projection(jobs: [failed]).researchFailureStageKey == nil)
    }

    @Test func unknownFailureUsesGenericCodeWithoutParsingMessage() throws {
        let failed = try research(code: "future_error", stage: nil)
        #expect(projection(jobs: [failed]).failureCode == "engine_failed")
        #expect(projection(jobs: [failed]).stage == nil)
    }

    @Test func deliveryAttentionNeverTurnsSuccessfulResearchIntoFailure() throws {
        var successful = try research(code: nil, stage: .complete)
        successful.state = .partialSuccess
        var report = task3Report(topic: "one", run: URL(fileURLWithPath: "/tmp/old"), date: 25)
        report.deliveries = [.init(channel: .email, state: .failed)]
        let model = projection(jobs: [successful], reports: [report])
        #expect(model.status == .partialSuccess)
        #expect(model.failureCode == nil)
        #expect(model.stage == nil)
    }

    @Test func modelFailuresHaveDistinctLocalizedCatalogReasons() {
        for language: AppLanguagePreference in [.english, .simplifiedChinese] {
            let localization = LocalizationStore(preference: language)
            let catalog = UserFacingErrorCatalog(localization: localization)
            let codes = ["model_transport_failed", "model_response_interrupted", "model_response_retry_exhausted"]
            let messages = codes.map { catalog.message(for: $0) }
            #expect(Set(messages).count == 3)
            for message in messages {
                #expect(message != localization.text("error.generic"))
                #expect(!message.hasPrefix("error."))
            }
        }
    }

    @Test func failureWithoutReportUsesStartTimeAndOnlyTypedStage() throws {
        var failed = try research(code: "model_transport_failed", stage: .verifier)
        failed.completedAt = nil
        failed.startedAt = Date(timeIntervalSince1970: 21)
        let model = projection(jobs: [failed])
        #expect(model.latestReport == nil)
        #expect(model.researchFailureTime == Date(timeIntervalSince1970: 21))
        #expect(model.researchFailureStageKey == "failure_stage.verifier")
        failed.stage = .complete
        #expect(projection(jobs: [failed]).researchFailureStageKey == nil)
    }

    @Test(arguments: [false, true])
    func confirmedRetryCreatesNewAttemptWithCurrentlyEnabledChannels(emailEnabled: Bool) async throws {
        // No engine is installed in this fixture; enqueue is real, execution cannot reach services.
        let root = FileManager.default.temporaryDirectory.appending(path: "today-retry-\(UUID())")
        defer { task3Trash(root) }
        var config = AppConfigurationDefaults.make(workspaceRoot: root,
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        config.topics = [.init(id: "one", displayName: "One", researchFocus: "Research",
            queries: ["research"], paperQueries: ["research"], reportLanguage: .english)]
        config.delivery.email = .init(enabled: emailEnabled, smtpHost: "smtp.example.test",
            username: "test", fromAddress: "from@example.test", toAddress: "to@example.test")
        config.delivery.wechat.enabled = false
        let formatter = DateFormatter(); formatter.calendar = .current; formatter.dateFormat = "yyyy-MM-dd"
        let date = formatter.string(from: Date())
        let report = ReportRecordV1(topicID: "one", reportDate: date, runDirectory: root.path,
            articleDraftPath: root.appending(path: "article.json").path,
            reportHTMLPath: root.appending(path: "report.html").path, title: "Old successful report",
            summary: "Old summary", sourceCount: 7, deepReadCount: 3, publishableClaimCount: 2,
            deliveries: [], createdAt: Date(timeIntervalSince1970: 1))
        let failed = try research(code: "model_response_interrupted", stage: .sourceGist)
        let store = AppStore(configuration: config, queueSnapshot: .init(jobs: [failed]),
            reportSnapshot: .init(reports: [report]), runtime: .init(selectedTopicID: "one", updatedAt: Date()),
            appSupportRoot: root, secretStore: RetryFixtureSecrets())
        store.refreshSecretPresence()
        let view = TodayContentView(store: store, localization: LocalizationStore(), compact: true,
            openReport: { _ in Issue.record("Retry must not open the old report") })
        #expect(view.showsResearchFailure)
        #expect(view.attentionCode == "model_response_interrupted")
        await view.confirmRunAgain()
        #expect(store.jobs.count == 2)
        let newJob = try #require(store.jobs.first { $0.id != failed.id })
        #expect(newJob.reportDate == date)
        #expect(newJob.requestedDeliveryChannels == (emailEnabled ? [.email] : []))
        #expect(store.selectedReportID == nil)
        #expect(store.reports.first?.sourceCount == 7)
    }

    private func research(code: String?, stage: EngineStage?) throws -> JobRecordV1 {
        try JobRecordV1(kind: .research, topicID: "one", reportDate: "2026-09-19",
            trigger: .runNow, state: .failed, stage: stage, jobDirectory: "/private/hidden",
            createdAt: Date(timeIntervalSince1970: 20), completedAt: Date(timeIntervalSince1970: 22),
            error: code.map { .init(code: $0, message: "source_gist timeout /private/secret", retryable: false) })
    }

    private func projection(jobs: [JobRecordV1], reports: [ReportRecordV1] = []) -> TodayPresentation {
        TodayPresentation(topic: .init(id: "one", displayName: "One", researchFocus: "Research",
            queries: ["research"], paperQueries: ["research"], reportLanguage: .english),
            jobs: jobs, reports: reports, schedules: [], schedulesPaused: false,
            now: Date(timeIntervalSince1970: 40), calendar: .current)
    }
}

private struct RetryFixtureSecrets: SecretStoring {
    func set(_ value: Data, account: String) throws {}
    func read(account: String) throws -> Data? { Issue.record("No secret reads expected"); return nil }
    func contains(account: String) throws -> Bool { true }
    func remove(account: String) throws {}
}
