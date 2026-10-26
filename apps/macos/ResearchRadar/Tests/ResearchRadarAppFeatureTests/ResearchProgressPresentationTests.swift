import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@Suite struct ResearchProgressPresentationTests {
    @Test func runningStageDoesNotInventCompletionOrCounts() throws {
        let reading = try job(state: .running, stage: .deepReading)
        let today = projection(jobs: [reading])
        let progress = today.researchProgress
        #expect(progress.isActive)
        #expect(progress.statusKey == "today.running")
        #expect(progress.steps.map(\.state) == [.unreported, .current, .unreported, .unreported])
        #expect(progress.attemptDate == reading.createdAt)
        #expect(today.latestReport == nil)
    }

    @Test func pendingAndUnknownStageDoNotDefaultToDiscovery() throws {
        for state: JobState in [.pending, .running] {
            let progress = projection(jobs: [try job(state: state)]).researchProgress
            #expect(progress.isActive)
            #expect(progress.steps.allSatisfy { $0.state == .unreported })
            #expect(progress.detailKey == (state == .pending ? "progress.queued" : "progress.waiting_stage"))
        }
    }

    @Test(arguments: [JobState.failed, .cancelled, .interrupted, .cancelling])
    func stoppedAndCancellingShowOnlyObservedStage(state: JobState) throws {
        let job = try job(state: state, stage: .verifier, code: "model_transport_failed")
        let progress = projection(jobs: [job]).researchProgress
        #expect(progress.steps.map(\.state) == [.unreported, .unreported,
            state == .cancelling ? .stopping : .stopped, .unreported])
        #expect(progress.isActive == (state == .cancelling))
        #expect(progress.statusKey != "today.running")
    }

    @Test func legacyErrorWithUnreliableStageIsNotHighlighted() throws {
        let progress = projection(jobs: [try job(state: .failed, stage: .discovery, code: "engine_crashed")]).researchProgress
        #expect(progress.steps.allSatisfy { $0.state == .unreported })
        #expect(progress.statusKey == "today.failed")
    }

    @Test func deliveryAttentionDoesNotMakeResearchProgressFail() throws {
        var report = task3Report(topic: "one", run: URL(fileURLWithPath: "/tmp/unused"), date: 1)
        report.deliveries = [.init(channel: .email, state: .unknown)]
        let delivery = try JobRecordV1(kind: .delivery, topicID: "one", reportDate: report.reportDate,
            deliveryChannel: .email, trigger: .retry, state: .deliveryUnknown,
            jobDirectory: "/tmp/unused", createdAt: Date())
        let today = projection(jobs: [delivery], reports: [report])
        #expect(today.status == .partialSuccess)
        #expect(today.researchProgress.statusKey == "today.succeeded")
        #expect(!today.researchProgress.isActive)
        #expect(today.researchProgress.steps.allSatisfy { $0.state == .unreported })
    }

    @Test func previousReportRemainsExplicitDuringNewResearchAndFailure() throws {
        let report = task3Report(topic: "one", run: URL(fileURLWithPath: "/tmp/unused"), date: 1)
        for state: JobState in [.pending, .running, .failed] {
            let today = projection(jobs: [try job(state: state, stage: .sourceGist,
                code: state == .failed ? "model_transport_failed" : nil)], reports: [report])
            #expect(today.reportSectionKey == "today.last_successful_report")
            #expect(!today.prefersReportFirst)
            #expect(today.latestReport?.id == report.id)
            #expect(today.latestReport?.publishableClaimCount == 1)
        }
        #expect(projection(reports: [report]).reportSectionKey == "home.latest_report")
        #expect(projection(reports: [report]).prefersReportFirst)
    }

    @Test func otherTopicAndEmptyOutcomeNeverSupplyProgressOrFakeStats() throws {
        let other = try job(topic: "two", state: .running, stage: .verifier)
        let today = projection(jobs: [other])
        #expect(!today.researchProgress.hasAttempt)
        #expect(today.researchProgress.statusKey == "today.idle")
        #expect(today.researchProgress.steps.allSatisfy { $0.state == .unreported })
        let empty = ReportRecordV1(topicID: "one", reportDate: "2026-10-25", runDirectory: "/tmp/empty",
            articleDraftPath: "/tmp/empty/a", reportHTMLPath: "/tmp/empty/h", title: "Empty", summary: "",
            sourceCount: 0, deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: Date(),
            researchOutcome: .init(status: .incomplete, reasons: [.readingFailed]))
        let incomplete = projection(reports: [empty])
        #expect(incomplete.researchProgress.hasAttempt)
        #expect(incomplete.researchProgress.statusKey == "today.incomplete")
        #expect(incomplete.latestReport == nil)
    }

    private func job(topic: String = "one", state: JobState, stage: EngineStage? = nil,
                     code: String? = nil) throws -> JobRecordV1 {
        try JobRecordV1(kind: .research, topicID: topic, reportDate: "2026-10-25", trigger: .runNow,
            state: state, stage: stage, jobDirectory: "/tmp/unused", createdAt: Date(timeIntervalSince1970: 20),
            error: code.map { .init(code: $0, message: "not for progress", retryable: false) })
    }

    private func projection(jobs: [JobRecordV1] = [], reports: [ReportRecordV1] = []) -> TodayPresentation {
        TodayPresentation(topic: .init(id: "one", displayName: "One", researchFocus: "One",
            queries: ["one"], paperQueries: ["one"], reportLanguage: .english),
            jobs: jobs, reports: reports, schedules: [], schedulesPaused: false,
            now: Date(), calendar: .current)
    }
}
