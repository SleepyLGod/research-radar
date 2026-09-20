import Foundation
import ResearchRadarCore

public protocol OneShotTimerDriving: Sendable {
    func replace(fireAt: Date?, action: @escaping @Sendable () async -> Void) async
    func cancel() async
}

/// A task-backed one-shot timer. It has no polling loop and retains no helper process.
public actor OneShotTimerDriver: OneShotTimerDriving {
    private var task: Task<Void, Never>?
    private let now: @Sendable () -> Date

    public init(now: @escaping @Sendable () -> Date = Date.init) { self.now = now }

    public func replace(fireAt: Date?, action: @escaping @Sendable () async -> Void) {
        task?.cancel(); task = nil
        guard let fireAt else { return }
        let delay = max(0, fireAt.timeIntervalSince(now()))
        task = Task {
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            await action()
        }
    }

    public func cancel() { task?.cancel(); task = nil }
}

public struct ScheduleInputs: Sendable {
    public let schedules: [DailyScheduleV1]
    public let topics: [TopicRecordV1]
    public let reports: [ReportRecordV1]
    public let paused: Bool

    public init(
        schedules: [DailyScheduleV1], topics: [TopicRecordV1],
        reports: [ReportRecordV1], paused: Bool
    ) {
        self.schedules = schedules; self.topics = topics
        self.reports = reports; self.paused = paused
    }
}

public actor ScheduleStateSource {
    private var value: ScheduleInputs
    public init(_ value: ScheduleInputs) { self.value = value }
    public func update(_ value: ScheduleInputs) { self.value = value }
    public func current() -> ScheduleInputs { value }
}

/// Evaluates due work once and arms exactly one timer for the next enabled schedule.
public actor ScheduleCoordinator {
    private let queue: JobQueue
    private let timer: any OneShotTimerDriving
    private let inputs: @Sendable () async throws -> ScheduleInputs
    private let onJobsEnqueued: @Sendable () async -> Void
    private let onFailure: @Sendable () async -> Void
    private let onAdmissionChange: @Sendable (Bool) async -> Void
    private let now: @Sendable () -> Date
    private let calendar: @Sendable () -> Calendar
    private let evaluator = ScheduleEvaluator()
    private enum Lifecycle { case active, blocked, stopped }
    private var lifecycle = Lifecycle.active
    private var timerGeneration = 0

    public init(
        queue: JobQueue,
        timer: any OneShotTimerDriving,
        inputs: @escaping @Sendable () async throws -> ScheduleInputs,
        onJobsEnqueued: @escaping @Sendable () async -> Void = {},
        onFailure: @escaping @Sendable () async -> Void = {},
        onAdmissionChange: @escaping @Sendable (Bool) async -> Void = { _ in },
        now: @escaping @Sendable () -> Date = Date.init,
        calendar: @escaping @Sendable () -> Calendar = { Calendar.autoupdatingCurrent }
    ) {
        self.queue = queue; self.timer = timer; self.inputs = inputs
        self.onJobsEnqueued = onJobsEnqueued
        self.onFailure = onFailure
        self.onAdmissionChange = onAdmissionChange
        self.now = now; self.calendar = calendar
    }

    public func refresh() async throws {
        await onAdmissionChange(true)
        do {
            try await refreshAdmitted()
        } catch {
            await block()
            await onAdmissionChange(false)
            throw error
        }
        await onAdmissionChange(false)
    }

    private func refreshAdmitted() async throws {
        guard lifecycle == .active else { return }
        timerGeneration += 1
        let generation = timerGeneration
        let snapshot = try await inputs()
        guard lifecycle == .active, generation == timerGeneration else { return }
        let current = now(); let activeCalendar = calendar()
        let jobs = await queue.jobs()
        guard lifecycle == .active, generation == timerGeneration else { return }
        var enqueuedJob = false
        if !snapshot.paused {
            for due in evaluator.dueResearchJobs(
                schedules: snapshot.schedules, topics: snapshot.topics,
                reports: snapshot.reports, queuedJobs: jobs,
                now: current, calendar: activeCalendar
            ) {
                guard lifecycle == .active, generation == timerGeneration else { return }
                let result = try await queue.enqueueResearch(
                    topicID: due.topicID,
                    reportDate: due.reportDate,
                    trigger: due.trigger,
                    deliveryChannels: due.deliveryChannels
                )
                if case .enqueued = result { enqueuedJob = true }
            }
        }
        guard lifecycle == .active, generation == timerGeneration else { return }
        if enqueuedJob { await onJobsEnqueued() }
        let next = snapshot.paused ? nil : evaluator.nextFireDate(
            schedules: snapshot.schedules, topics: snapshot.topics,
            after: current, calendar: activeCalendar
        )
        guard lifecycle == .active, generation == timerGeneration else { return }
        await armTimer(at: next)
    }

    public func stop() async {
        lifecycle = .stopped
        timerGeneration += 1
        // Wait behind any queue operation already admitted by this coordinator.
        _ = await queue.jobs()
        await timer.cancel()
    }

    /// A fault is recoverable only by an explicit, validated user action.
    public func block() async {
        guard lifecycle != .stopped else { return }
        lifecycle = .blocked
        timerGeneration += 1
        _ = await queue.jobs()
        await timer.cancel()
    }

    public func recover() async throws {
        guard lifecycle != .stopped else { return }
        lifecycle = .active
        try await refresh()
    }

    private func armTimer(at date: Date?) async {
        await timer.replace(fireAt: date) { [weak self] in
            await self?.handleTimerFire()
        }
    }

    private func handleTimerFire() async {
        do {
            try await refresh()
        } catch {
            await onFailure()
        }
    }
}
