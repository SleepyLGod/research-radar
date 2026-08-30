import Foundation

public enum JobRecordError: Error, Equatable, Sendable {
    case invalidSchemaVersion
    case deliveryChannelRequired
    case deliveryChannelNotAllowed
    case unknownDeliveryRequiresAcknowledgement
    case invalidTransition(JobState, JobState)
}

public struct JobRecordV1: Codable, Equatable, Identifiable, Sendable {
    public let schemaVersion: Int
    public let id: UUID
    public let kind: JobKind
    public let topicID: String
    public let reportDate: String
    public let deliveryChannel: DeliveryChannel?
    public let requestedDeliveryChannels: [DeliveryChannel]
    public let trigger: JobTrigger
    public let allowResend: Bool
    public let acknowledgeUnknownOutcome: Bool
    public var state: JobState
    public var stage: EngineStage?
    public var attemptCount: Int
    public var jobDirectory: String
    public var runDirectory: String?
    public var createdAt: Date
    public var startedAt: Date?
    public var completedAt: Date?
    public var error: RedactedEngineErrorV1?

    public init(
        schemaVersion: Int = 1,
        id: UUID = UUID(),
        kind: JobKind,
        topicID: String,
        reportDate: String,
        deliveryChannel: DeliveryChannel? = nil,
        requestedDeliveryChannels: [DeliveryChannel] = [],
        trigger: JobTrigger,
        allowResend: Bool = false,
        acknowledgeUnknownOutcome: Bool = false,
        state: JobState = .pending,
        stage: EngineStage? = nil,
        attemptCount: Int = 1,
        jobDirectory: String,
        runDirectory: String? = nil,
        createdAt: Date,
        startedAt: Date? = nil,
        completedAt: Date? = nil,
        error: RedactedEngineErrorV1? = nil
    ) throws {
        guard schemaVersion == 1 else { throw JobRecordError.invalidSchemaVersion }
        guard kind == .delivery || deliveryChannel == nil else {
            throw JobRecordError.deliveryChannelNotAllowed
        }
        guard kind == .research || deliveryChannel != nil else {
            throw JobRecordError.deliveryChannelRequired
        }
        guard kind == .research || requestedDeliveryChannels.isEmpty else {
            throw JobRecordError.deliveryChannelNotAllowed
        }
        self.schemaVersion = schemaVersion
        self.id = id
        self.kind = kind
        self.topicID = topicID
        self.reportDate = reportDate
        self.deliveryChannel = deliveryChannel
        self.requestedDeliveryChannels = requestedDeliveryChannels
        self.trigger = trigger
        self.allowResend = allowResend
        self.acknowledgeUnknownOutcome = acknowledgeUnknownOutcome
        self.state = state
        self.stage = stage
        self.attemptCount = attemptCount
        self.jobDirectory = jobDirectory
        self.runDirectory = runDirectory
        self.createdAt = createdAt
        self.startedAt = startedAt
        self.completedAt = completedAt
        self.error = error
    }

    public mutating func transition(
        to newState: JobState,
        stage newStage: EngineStage? = nil,
        error newError: RedactedEngineErrorV1? = nil,
        at date: Date
    ) throws {
        guard Self.allowedTransitions[state, default: []].contains(newState) else {
            throw JobRecordError.invalidTransition(state, newState)
        }
        state = newState
        if let newStage { stage = newStage }
        if let newError { error = newError }
        if newState == .running { startedAt = date }
        if Self.terminalStates.contains(newState) { completedAt = date }
    }

    public static let terminalStates: Set<JobState> = [
        .succeeded, .partialSuccess, .failed, .cancelled, .interrupted, .deliveryUnknown,
    ]

    private static let allowedTransitions: [JobState: Set<JobState>] = [
        .pending: [.running, .cancelled],
        .running: [.cancelling, .succeeded, .partialSuccess, .failed, .cancelled, .interrupted, .deliveryUnknown],
        .cancelling: [.cancelled, .failed, .interrupted, .deliveryUnknown],
    ]
}

public struct JobQueueSnapshotV1: Codable, Equatable, Sendable, ValidatableDurableState {
    public let schemaVersion: Int
    public var jobs: [JobRecordV1]

    public init(schemaVersion: Int = 1, jobs: [JobRecordV1] = []) {
        self.schemaVersion = schemaVersion
        self.jobs = jobs
    }

    public func validate() throws {
        guard Set(jobs.map(\.id)).count == jobs.count else {
            throw DurableStateValidationError.duplicateIdentifier
        }
        for job in jobs {
            guard job.schemaVersion == 1,
                  !job.topicID.isEmpty,
                  !job.reportDate.isEmpty,
                  !job.jobDirectory.isEmpty,
                  job.attemptCount > 0
            else { throw DurableStateValidationError.invalidValue }
            guard job.kind == .delivery ? job.deliveryChannel != nil : job.deliveryChannel == nil else {
                throw DurableStateValidationError.invalidValue
            }
            guard job.kind == .research || job.requestedDeliveryChannels.isEmpty,
                  Set(job.requestedDeliveryChannels).count == job.requestedDeliveryChannels.count
            else { throw DurableStateValidationError.invalidValue }
            guard job.kind == .delivery ? job.runDirectory?.isEmpty == false : job.runDirectory == nil else {
                throw DurableStateValidationError.invalidValue
            }
        }
    }
}

public enum EnqueueResult: Equatable, Sendable {
    case enqueued(UUID)
    case coalesced(UUID)
}
