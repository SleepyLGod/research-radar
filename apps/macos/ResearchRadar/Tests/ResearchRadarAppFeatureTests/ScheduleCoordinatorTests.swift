import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

private actor FakeTimerDriver: OneShotTimerDriving {
    private(set) var fireAt: Date?
    private(set) var replacementCount = 0
    private var action: (@Sendable () async -> Void)?
    func replace(fireAt: Date?, action: @escaping @Sendable () async -> Void) {
        self.fireAt = fireAt
        self.action = fireAt == nil ? nil : action
        replacementCount += 1
    }
    func cancel() { fireAt = nil; action = nil }
    func fire() async { await action?() }
}

private actor DueJobRecorder {
    private(set) var count = 0
    func record() { count += 1 }
}

private enum ScheduleTestError: Error { case unavailable }

private final class ScheduleFailureSwitch: @unchecked Sendable {
    var shouldFail = false
}

@Suite struct ScheduleCoordinatorTests {
    @Test func enqueuesOnlyTodaysDueJobAndArmsOneNextTimer() async throws {
        let root = try scheduleRoot(); defer { try? trashScheduleRoot(root) }
        let queue = JobQueue(store: AtomicJSONStore(root: root), jobsRoot: root.appending(path: "jobs"))
        let timer = FakeTimerDriver()
        var configuredCalendar = Calendar(identifier: .gregorian)
        configuredCalendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let calendar = configuredCalendar
        let now = try #require(calendar.date(from: DateComponents(year: 2026, month: 8, day: 30, hour: 10)))
        let topic = TopicRecordV1(
            id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["agent memory"], reportLanguage: .chinese
        )
        let schedule = DailyScheduleV1(
            id: UUID(), topicID: topic.id, hour: 9, minute: 0,
            isEnabled: true, deliveryChannels: [.wechat]
        )
        let coordinator = ScheduleCoordinator(
            queue: queue, timer: timer,
            inputs: { ScheduleInputs(schedules: [schedule], topics: [topic], reports: [], paused: false) },
            now: { now }, calendar: { calendar }
        )

        try await coordinator.refresh()

        #expect(await queue.jobs().count == 1)
        #expect(await timer.replacementCount == 1)
        #expect(await timer.fireAt != nil)
    }

    @Test func pausedSchedulingCreatesNoJobAndNoTimer() async throws {
        let root = try scheduleRoot(); defer { try? trashScheduleRoot(root) }
        let queue = JobQueue(store: AtomicJSONStore(root: root), jobsRoot: root.appending(path: "jobs"))
        let timer = FakeTimerDriver()
        let coordinator = ScheduleCoordinator(
            queue: queue, timer: timer,
            inputs: { ScheduleInputs(schedules: [], topics: [], reports: [], paused: true) }
        )

        try await coordinator.refresh()

        #expect(await queue.jobs().isEmpty)
        #expect(await timer.fireAt == nil)
    }

    @Test func timerRefreshNotifiesTheQueueConsumerWhenAJobBecomesDue() async throws {
        let root = try scheduleRoot(); defer { try? trashScheduleRoot(root) }
        let queue = JobQueue(store: AtomicJSONStore(root: root), jobsRoot: root.appending(path: "jobs"))
        let timer = FakeTimerDriver()
        let recorder = DueJobRecorder()
        var mutableCalendar = Calendar(identifier: .gregorian)
        mutableCalendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let calendar = mutableCalendar
        let before = try #require(calendar.date(
            from: DateComponents(year: 2026, month: 8, day: 30, hour: 8, minute: 59)
        ))
        let after = try #require(calendar.date(
            from: DateComponents(year: 2026, month: 8, day: 30, hour: 9, minute: 0)
        ))
        let clock = MutableClock(before)
        let topic = TopicRecordV1(
            id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["agent memory"], reportLanguage: .chinese
        )
        let schedule = DailyScheduleV1(
            topicID: topic.id, hour: 9, minute: 0, isEnabled: true
        )
        let coordinator = ScheduleCoordinator(
            queue: queue,
            timer: timer,
            inputs: {
                ScheduleInputs(schedules: [schedule], topics: [topic], reports: [], paused: false)
            },
            onJobsEnqueued: { await recorder.record() },
            now: { clock.value },
            calendar: { calendar }
        )

        try await coordinator.refresh()
        clock.value = after
        await timer.fire()

        #expect(await queue.jobs().count == 1)
        #expect(await recorder.count == 1)
    }

    @Test func timerFailureArmsABoundedRetryInsteadOfSilentlyStopping() async throws {
        let root = try scheduleRoot(); defer { try? trashScheduleRoot(root) }
        let queue = JobQueue(store: AtomicJSONStore(root: root), jobsRoot: root.appending(path: "jobs"))
        let timer = FakeTimerDriver()
        let failure = ScheduleFailureSwitch()
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let topic = TopicRecordV1(
            id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["agent memory"], reportLanguage: .chinese
        )
        let schedule = DailyScheduleV1(
            topicID: topic.id, hour: 12, minute: 0, isEnabled: true
        )
        let coordinator = ScheduleCoordinator(
            queue: queue,
            timer: timer,
            inputs: {
                if failure.shouldFail { throw ScheduleTestError.unavailable }
                return ScheduleInputs(
                    schedules: [schedule], topics: [topic], reports: [], paused: false
                )
            },
            now: { now },
            calendar: {
                var calendar = Calendar(identifier: .gregorian)
                calendar.timeZone = TimeZone(secondsFromGMT: 0)!
                return calendar
            }
        )

        try await coordinator.refresh()
        failure.shouldFail = true
        await timer.fire()

        #expect(await timer.replacementCount == 2)
        #expect(await timer.fireAt == now.addingTimeInterval(60))
    }
}

private final class MutableClock: @unchecked Sendable {
    var value: Date
    init(_ value: Date) { self.value = value }
}

private func scheduleRoot() throws -> URL {
    let url = FileManager.default.temporaryDirectory.appending(path: "schedule-coordinator-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false); return url
}
private func trashScheduleRoot(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
