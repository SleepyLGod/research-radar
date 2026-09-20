import Foundation

public struct ScheduleEvaluator: Sendable {
    public init() {}

    public func dueResearchJobs(
        schedules: [DailyScheduleV1],
        topics: [TopicRecordV1],
        reports: [ReportRecordV1],
        queuedJobs: [JobRecordV1],
        now: Date,
        calendar: Calendar
    ) -> [DueResearchJob] {
        let topicByID = Dictionary(uniqueKeysWithValues: topics.map { ($0.id, $0) })
        let reportDate = Self.reportDate(now, calendar: calendar)
        return schedules.compactMap { schedule in
            guard schedule.isEnabled,
                  let topic = topicByID[schedule.topicID],
                  !topic.isPaused,
                  let due = calendar.date(
                    bySettingHour: schedule.hour,
                    minute: schedule.minute,
                    second: 0,
                    of: now
                  ),
                  now >= due,
                  !reports.contains(where: {
                    $0.topicID == schedule.topicID && $0.reportDate == reportDate
                  }),
                  !queuedJobs.contains(where: {
                    $0.kind == .research && $0.topicID == schedule.topicID
                        && $0.reportDate == reportDate
                  })
            else { return nil }
            return DueResearchJob(
                topicID: schedule.topicID,
                reportDate: reportDate,
                trigger: .schedule,
                deliveryChannels: schedule.deliveryChannels
            )
        }
    }

    public func nextFireDate(
        schedules: [DailyScheduleV1],
        topics: [TopicRecordV1],
        after now: Date,
        calendar: Calendar
    ) -> Date? {
        let activeTopics = Set(topics.filter { !$0.isPaused }.map(\.id))
        return schedules.compactMap { schedule in
            guard schedule.isEnabled, activeTopics.contains(schedule.topicID) else { return nil }
            let today = calendar.date(
                bySettingHour: schedule.hour,
                minute: schedule.minute,
                second: 0,
                of: now
            )
            if let today, today > now { return today }
            guard let tomorrow = calendar.date(byAdding: .day, value: 1, to: now) else {
                return nil
            }
            return calendar.date(
                bySettingHour: schedule.hour,
                minute: schedule.minute,
                second: 0,
                of: tomorrow
            )
        }.min()
    }

    private static func reportDate(_ date: Date, calendar: Calendar) -> String {
        let components = calendar.dateComponents([.year, .month, .day], from: date)
        return String(
            format: "%04d-%02d-%02d",
            components.year ?? 0,
            components.month ?? 0,
            components.day ?? 0
        )
    }
}
