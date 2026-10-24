import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@Suite struct ResearchOutcomePresentationTests {
    @Test(arguments: ResearchOutcomeV1.Status.allCases, [false, true])
    func explicitOutcomeKeepsReasonsSeparateFromRetainedReport(status: ResearchOutcomeV1.Status, priorUseful: Bool) {
        let useful = record(topic: "one", date: "2026-09-18", deep: 2, claims: 3)
        let latest = record(topic: "one", date: "2026-09-19", deep: status == .ready ? 1 : 0,
            claims: status == .ready ? 1 : 0, outcome: .init(status: status, reasons: [.fullTextUnavailable]))
        let today = presentation(reports: priorUseful ? [useful, latest] : [latest])
        #expect(today.latestAttemptReport?.id == latest.id)
        #expect(today.outcomeReasonKeys == ["research_reason.full_text_unavailable"])
        #expect(today.statusKey == (status == .ready ? "today.succeeded" : status == .noNewContent ? "today.noNewContent" : "today.incomplete"))
        #expect(today.latestReport?.id == (status == .ready ? latest.id : priorUseful ? useful.id : nil))
        #expect(today.showsRetainedReport == (status != .ready && priorUseful))
        #expect(today.automaticDeliveryExplanationKey == (status == .ready ? nil : "today.no_automatic_delivery"))
    }

    @Test func latestEmptyAttemptRetainsUsefulReportWithoutMixingTopicOrCounts() {
        let useful = record(topic: "one", date: "2026-09-18", deep: 2, claims: 3)
        let empty = record(topic: "one", date: "2026-09-19", deep: 0, claims: 0)
        let other = record(topic: "two", date: "2026-09-20", deep: 5, claims: 8)
        let today = presentation(reports: [other, empty, useful])
        #expect(today.latestReport?.id == useful.id)
        #expect(today.latestReport?.deepReadCount == 2)
        #expect(today.latestReport?.publishableClaimCount == 3)
        #expect(today.statusKey == "today.outcomeUnknown")
        #expect(today.latestAttemptReport?.id == empty.id)
        #expect(today.outcomeReasonKeys.isEmpty)
        #expect(today.automaticDeliveryExplanationKey == "today.automatic_delivery_ineligible")
    }

    @Test func retainedDeliveryIsExplicitlyHistoricalAndNotAttributedToEmptyAttempt() {
        let useful = record(topic: "one", date: "2026-09-18", deep: 1, claims: 2,
            deliveries: [.init(channel: .email, state: .sent)])
        let empty = record(topic: "one", date: "2026-09-19", deep: 0, claims: 0,
            outcome: .init(status: .noNewContent, reasons: [.noEligiblePapers]))
        let today = presentation(reports: [useful, empty])
        #expect(today.automaticDeliveryExplanationKey == "today.no_automatic_delivery")
        #expect(today.deliveryHistoryKey == "today.historical_delivery")
        #expect(today.latestReport?.deliveries.first?.state == .sent)
        #expect(presentation(reports: [useful]).deliveryHistoryKey == nil)
    }

    @Test func existingDeliveryHistoryCannotClaimNoTasksWereCreated() throws {
        let empty = record(topic: "one", date: "2026-09-19", deep: 0, claims: 0,
            outcome: .init(status: .incomplete, reasons: [.readingFailed]),
            deliveries: [.init(channel: .email, state: .pending)])
        #expect(presentation(reports: [empty]).automaticDeliveryExplanationKey == "today.automatic_delivery_ineligible")
        let noRecords = record(topic: "one", date: "2026-09-19", deep: 0, claims: 0,
            outcome: .init(status: .incomplete, reasons: [.readingFailed]))
        let job = try JobRecordV1(kind: .delivery, topicID: "one", reportDate: noRecords.reportDate,
            deliveryChannel: .email, trigger: .schedule, state: .pending, jobDirectory: "/job",
            runDirectory: noRecords.runDirectory, createdAt: Date())
        #expect(presentation(reports: [noRecords], jobs: [job]).automaticDeliveryExplanationKey == "today.automatic_delivery_ineligible")
    }

    @Test(arguments: [JobState.pending, .running, .failed])
    func newerAttemptDoesNotShowOldEmptyAttemptAsCurrentNonDelivery(state: JobState) throws {
        let empty = record(topic: "one", date: "2026-09-19", deep: 0, claims: 0,
            outcome: .init(status: .incomplete, reasons: [.readingFailed]))
        let job = try JobRecordV1(kind: .research, topicID: "one", reportDate: empty.reportDate,
            trigger: .runNow, state: state, jobDirectory: "/job", createdAt: Date())
        #expect(presentation(reports: [empty], jobs: [job]).automaticDeliveryExplanationKey == nil)
    }

    private func presentation(reports: [ReportRecordV1], jobs: [JobRecordV1] = []) -> TodayPresentation {
        TodayPresentation(topic: .init(id: "one", displayName: "One", researchFocus: "One",
            queries: ["one"], paperQueries: ["one"], reportLanguage: .english),
            jobs: jobs, reports: reports, schedules: [], schedulesPaused: false,
            now: Date(), calendar: .current)
    }

    private func record(topic: String, date: String, deep: Int, claims: Int,
                        outcome: ResearchOutcomeV1? = nil, deliveries: [DeliveryRecordV1] = []) -> ReportRecordV1 {
        ReportRecordV1(topicID: topic, reportDate: date, runDirectory: "/\(UUID())",
            articleDraftPath: "/a", reportHTMLPath: "/h", title: "Report", summary: "",
            sourceCount: 9, deepReadCount: deep, publishableClaimCount: claims,
            deliveries: deliveries, createdAt: Date(), researchOutcome: outcome)
    }
}
