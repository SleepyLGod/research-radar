import Foundation

public actor JobQueue {
    private var snapshot: JobQueueSnapshotV1
    private let store: AtomicJSONStore
    private let relativePath: String
    private let jobsRoot: URL
    private let clock: @Sendable () -> Date

    public init(
        snapshot: JobQueueSnapshotV1 = JobQueueSnapshotV1(),
        store: AtomicJSONStore,
        relativePath: String = "state/queue.json",
        jobsRoot: URL,
        clock: @escaping @Sendable () -> Date = Date.init
    ) {
        self.snapshot = snapshot
        self.store = store
        self.relativePath = relativePath
        self.jobsRoot = jobsRoot
        self.clock = clock
    }

    public func jobs() -> [JobRecordV1] { snapshot.jobs }

    public func enqueueResearch(
        topicID: String,
        reportDate: String,
        trigger: JobTrigger,
        deliveryChannels: [DeliveryChannel] = []
    ) throws -> EnqueueResult {
        if let existing = activeJob(
            kind: .research,
            topicID: topicID,
            reportDate: reportDate,
            channel: nil,
            runDirectory: nil
        ) {
            return .coalesced(existing.id)
        }
        let attempts = snapshot.jobs.filter {
            $0.kind == .research && $0.topicID == topicID && $0.reportDate == reportDate
        }.map(\.attemptCount)
        let id = UUID()
        let job = try JobRecordV1(
            id: id,
            kind: .research,
            topicID: topicID,
            reportDate: reportDate,
            requestedDeliveryChannels: deliveryChannels,
            trigger: trigger,
            attemptCount: (attempts.max() ?? 0) + 1,
            jobDirectory: jobsRoot.appending(path: id.uuidString.lowercased()).path,
            createdAt: clock()
        )
        var updated = snapshot
        updated.jobs.append(job)
        try persist(updated)
        snapshot = updated
        return .enqueued(id)
    }

    public func enqueueDelivery(
        runDirectory: URL,
        topicID: String,
        reportDate: String,
        channel: DeliveryChannel,
        trigger: JobTrigger = .retry,
        allowResend: Bool = false,
        acknowledgeUnknownOutcome: Bool = false
    ) throws -> EnqueueResult {
        if let existing = activeJob(
            kind: .delivery,
            topicID: topicID,
            reportDate: reportDate,
            channel: channel,
            runDirectory: runDirectory.path
        ) {
            return .coalesced(existing.id)
        }
        let prior = snapshot.jobs.filter {
            $0.kind == .delivery && $0.topicID == topicID
                && $0.reportDate == reportDate && $0.deliveryChannel == channel
                && $0.runDirectory == runDirectory.path
        }
        if prior.contains(where: { $0.state == .deliveryUnknown }), !acknowledgeUnknownOutcome {
            throw JobRecordError.unknownDeliveryRequiresAcknowledgement
        }
        let attempts = prior.map(\.attemptCount)
        let id = UUID()
        let job = try JobRecordV1(
            id: id,
            kind: .delivery,
            topicID: topicID,
            reportDate: reportDate,
            deliveryChannel: channel,
            trigger: trigger,
            allowResend: allowResend,
            acknowledgeUnknownOutcome: acknowledgeUnknownOutcome,
            attemptCount: (attempts.max() ?? 0) + 1,
            jobDirectory: jobsRoot.appending(path: id.uuidString.lowercased()).path,
            runDirectory: runDirectory.path,
            createdAt: clock()
        )
        var updated = snapshot
        updated.jobs.append(job)
        try persist(updated)
        snapshot = updated
        return .enqueued(id)
    }

    public func nextPending() throws -> JobRecordV1? {
        guard !snapshot.jobs.contains(where: { $0.state == .running || $0.state == .cancelling }),
              let index = snapshot.jobs.firstIndex(where: { $0.state == .pending })
        else { return nil }
        var updated = snapshot
        try updated.jobs[index].transition(to: .running, at: clock())
        try persist(updated)
        snapshot = updated
        return updated.jobs[index]
    }

    public func transition(
        jobID: UUID,
        to state: JobState,
        stage: EngineStage? = nil,
        error: RedactedEngineErrorV1? = nil
    ) throws {
        guard let index = snapshot.jobs.firstIndex(where: { $0.id == jobID }) else { return }
        var updated = snapshot
        try updated.jobs[index].transition(to: state, stage: stage, error: error, at: clock())
        try persist(updated)
        snapshot = updated
    }

    private func activeJob(
        kind: JobKind,
        topicID: String,
        reportDate: String,
        channel: DeliveryChannel?,
        runDirectory: String?
    ) -> JobRecordV1? {
        snapshot.jobs.first {
            $0.kind == kind && $0.topicID == topicID && $0.reportDate == reportDate
                && $0.deliveryChannel == channel && $0.runDirectory == runDirectory
                && [.pending, .running, .cancelling].contains($0.state)
        }
    }

    private func persist(_ candidate: JobQueueSnapshotV1) throws {
        try store.write(candidate, to: relativePath)
    }
}
