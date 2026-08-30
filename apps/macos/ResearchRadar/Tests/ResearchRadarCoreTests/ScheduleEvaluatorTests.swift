import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct ScheduleEvaluatorTests {
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
