import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct ScheduleEvaluatorTests {
    @Test(arguments: [ResearchOutcomeV1.Status.noNewContent, .incomplete])
    func emptyOutcomeDoesNotTriggerImmediateScheduleRetry(status: ResearchOutcomeV1.Status) throws {
        let calendar = utcCalendar()
        let now = try #require(calendar.date(from: DateComponents(year: 2026, month: 8, day: 30, hour: 12)))
        let tomorrow = try #require(calendar.date(from: DateComponents(year: 2026, month: 8, day: 31, hour: 9)))
        let schedule = DailyScheduleV1(topicID: "llm-inference", hour: 9, minute: 0)
        let report = ReportRecordV1(topicID: "llm-inference", reportDate: "2026-08-30", runDirectory: "/run",
            articleDraftPath: "/a", reportHTMLPath: "/h", title: "Empty", summary: "",
            sourceCount: 0, deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: now,
            researchOutcome: .init(status: status, reasons: []))
        let evaluator = ScheduleEvaluator()
        #expect(evaluator.dueResearchJobs(schedules: [schedule], topics: [topicRecord()], reports: [report],
            queuedJobs: [], now: now, calendar: calendar).isEmpty)
        #expect(evaluator.nextFireDate(schedules: [schedule], topics: [topicRecord()], after: now, calendar: calendar) == tomorrow)
    }

    @Test func missedYesterdayWaitsForTodaysTime() throws {
        let calendar = utcCalendar()
        let now = try #require(calendar.date(from: DateComponents(year: 2026, month: 9, day: 20, hour: 8)))
        let expected = try #require(calendar.date(from: DateComponents(year: 2026, month: 9, day: 20, hour: 9)))
        let schedule = DailyScheduleV1(topicID: "llm-inference", hour: 9, minute: 0)
        let evaluator = ScheduleEvaluator()
        #expect(evaluator.dueResearchJobs(schedules: [schedule], topics: [topicRecord()], reports: [], queuedJobs: [], now: now, calendar: calendar).isEmpty)
        #expect(evaluator.nextFireDate(schedules: [schedule], topics: [topicRecord()], after: now, calendar: calendar) == expected)
    }
    @Test func onlyTodaysLatestDueJobIsReturned() throws {
        let calendar = utcCalendar()
        let now = try #require(calendar.date(from: DateComponents(
            year: 2026, month: 8, day: 30, hour: 12
        )))
        let schedule = DailyScheduleV1(
            id: UUID(),
            topicID: "llm-inference",
            hour: 9,
            minute: 0,
            isEnabled: true,
            deliveryChannels: [.wechat, .email]
        )

        let due = ScheduleEvaluator().dueResearchJobs(
            schedules: [schedule],
            topics: [topicRecord()],
            reports: [],
            queuedJobs: [],
            now: now,
            calendar: calendar
        )

        #expect(due == [DueResearchJob(
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            trigger: .schedule,
            deliveryChannels: [.wechat, .email]
        )])
    }

    @Test func disabledPausedReportedAndQueuedTopicsAreSkipped() throws {
        let calendar = utcCalendar()
        let now = try #require(calendar.date(from: DateComponents(
            year: 2026, month: 8, day: 30, hour: 12
        )))
        var topic = topicRecord()
        topic.isPaused = true
        let schedule = DailyScheduleV1(
            id: UUID(), topicID: topic.id, hour: 9, minute: 0,
            isEnabled: true, deliveryChannels: []
        )

        #expect(ScheduleEvaluator().dueResearchJobs(
            schedules: [schedule], topics: [topic], reports: [], queuedJobs: [],
            now: now, calendar: calendar
        ).isEmpty)
    }

    @Test func nextFireUsesOneNearestFutureDate() throws {
        let calendar = utcCalendar()
        let now = try #require(calendar.date(from: DateComponents(
            year: 2026, month: 8, day: 30, hour: 8, minute: 30
        )))
        let schedules = [
            DailyScheduleV1(
                id: UUID(), topicID: "llm-inference", hour: 10, minute: 0,
                isEnabled: true, deliveryChannels: []
            ),
            DailyScheduleV1(
                id: UUID(), topicID: "llm-inference", hour: 9, minute: 0,
                isEnabled: true, deliveryChannels: []
            ),
        ]
        let expected = try #require(calendar.date(from: DateComponents(
            year: 2026, month: 8, day: 30, hour: 9
        )))

        #expect(ScheduleEvaluator().nextFireDate(
            schedules: schedules,
            topics: [topicRecord()],
            after: now,
            calendar: calendar
        ) == expected)
    }

    @Test func failedAttemptIsNotAutomaticallyRepeatedOnTheSameDay() throws {
        let calendar = utcCalendar()
        let now = try #require(calendar.date(from: DateComponents(
            year: 2026, month: 8, day: 30, hour: 12
        )))
        let schedule = DailyScheduleV1(
            topicID: "llm-inference", hour: 9, minute: 0, isEnabled: true
        )
        let failed = try JobRecordV1(
            kind: .research,
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            trigger: .schedule,
            state: .failed,
            jobDirectory: "/jobs/failed",
            createdAt: now,
            completedAt: now
        )

        #expect(ScheduleEvaluator().dueResearchJobs(
            schedules: [schedule],
            topics: [topicRecord()],
            reports: [],
            queuedJobs: [failed],
            now: now,
            calendar: calendar
        ).isEmpty)
    }
}

private func utcCalendar() -> Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0)!
    return calendar
}
