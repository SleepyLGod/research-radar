import Foundation
import ResearchRadarCore

/// Shared, read-only schedule status for the home screen and settings.
public struct SchedulePresentation: Equatable, Sendable {
    public enum Status: String, Sendable { case absent, disabled, paused, configurationBlocked, faulted, scheduled }
    public let status: Status
    public let nextRun: Date?
    public var localizationKey: String { "schedule.\(status.rawValue)" }

    public init(topic: TopicRecordV1?, schedule: DailyScheduleV1?, paused: Bool,
                faulted: Bool, configurationError: String?, now: Date, calendar: Calendar) {
        if faulted { status = .faulted }
        else if topic == nil || schedule == nil { status = .absent }
        else if topic?.isPaused == true || schedule?.isEnabled != true { status = .disabled }
        else if paused { status = .paused }
        else if configurationError != nil { status = .configurationBlocked }
        else { status = .scheduled }
        nextRun = status == .scheduled ? ScheduleEvaluator().nextFireDate(
            schedules: schedule.map { [$0] } ?? [], topics: topic.map { [$0] } ?? [],
            after: now, calendar: calendar
        ) : nil
    }
}
