import Foundation
import ResearchRadarCore

// Earlier terminal errors used the command's initial stage, not observed progress.
private let observedFailureStageCodes: Set<String> = [
    "model_transport_failed", "model_response_interrupted", "model_response_retry_exhausted"
]

public enum PublicResearchStage: String, CaseIterable, Equatable, Sendable {
    case discovery = "discover"
    case reading
    case verification = "verifying"
    case composition = "composing"

    public var localizationKey: String { "stage.\(rawValue)" }
    public static var discover: Self { .discovery }
    public static var verifying: Self { .verification }
    public static var composing: Self { .composition }

    public init?(engineStage: EngineStage) {
        switch engineStage {
        case .discovery, .sourceGist: self = .discover
        case .acquisition, .deepReading, .anchorRepair: self = .reading
        case .verifier: self = .verifying
        case .localization, .compose: self = .composing
        default: return nil
        }
    }
}

public typealias ResearchStage = PublicResearchStage

public enum TodayStatus: String, Equatable, Sendable {
    case noTopic, idle, pending, running, cancelling, succeeded, partialSuccess
    case failed, cancelled, interrupted, deliveryUnknown
    case noNewContent, incomplete, outcomeUnknown

    init(state: JobState) {
        switch state {
        case .pending: self = .pending
        case .running: self = .running
        case .cancelling: self = .cancelling
        case .succeeded: self = .succeeded
        case .partialSuccess: self = .partialSuccess
        case .failed: self = .failed
        case .cancelled: self = .cancelled
        case .interrupted: self = .interrupted
        case .deliveryUnknown: self = .deliveryUnknown
        }
    }
}

/// Deliberately excludes event messages, error payloads and diagnostic paths.
public struct JobPresentation: Equatable, Identifiable, Sendable {
    public let id: UUID
    public let kind: JobKind
    public let state: JobState
    public let stage: ResearchStage?

    public init(job: JobRecordV1) {
        id = job.id; kind = job.kind; state = job.state
        let reliableStage = job.error.map { observedFailureStageCodes.contains($0.code) } ?? true
        stage = job.kind == .research && reliableStage
            && [.running, .cancelling, .failed, .interrupted, .cancelled].contains(job.state)
            ? job.stage.flatMap(ResearchStage.init(engineStage:)) : nil
    }
}

public struct EngineStatusPresentation: Equatable, Sendable {
    public let topicID: String
    public let topic: TopicRecordV1?
    public let job: JobPresentation

    public init(job: JobRecordV1, topics: [TopicRecordV1]) {
        topicID = job.topicID
        topic = topics.first { $0.id == job.topicID }
        self.job = JobPresentation(job: job)
    }
}

/// A pure selected-topic projection. No synthetic completion percentage is inferred.
public struct TodayPresentation: Equatable, Sendable {
    public let topic: TopicRecordV1?
    public let topicID: String?
    public let otherActiveTopicID: String?
    public let status: TodayStatus
    public var statusKey: String { "today.\(status.rawValue)" }
    public let stage: ResearchStage?
    public let activeJob: JobRecordV1?
    public let latestResearchJob: JobRecordV1?
    public let job: JobPresentation?
    public let jobs: [JobPresentation]
    public let latestReport: ReportRecordV1?
    public let latestAttemptReport: ReportRecordV1?
    public var outcomeReasonKeys: [String] {
        latestAttemptReport?.researchOutcome?.reasons.map(\.localizationKey) ?? []
    }
    public var showsRetainedReport: Bool {
        latestReport != nil && latestReport?.id != latestAttemptReport?.id
    }
    private let latestAttemptHasDeliveryJobs: Bool
    public var automaticDeliveryExplanationKey: String? {
        guard [.noNewContent, .incomplete, .outcomeUnknown].contains(status),
              let attempt = latestAttemptReport, !attempt.isEffectiveDeepReport else { return nil }
        // Legacy records and historical jobs cannot prove that no task was ever created.
        return attempt.researchOutcome != nil && attempt.deliveries.isEmpty && !latestAttemptHasDeliveryJobs
            ? "today.no_automatic_delivery" : "today.automatic_delivery_ineligible"
    }
    public var deliveryHistoryKey: String? {
        guard let report = latestReport, !report.deliveries.isEmpty else { return nil }
        let newerAttemptActive = latestResearchJob.map {
            [.pending, .running, .cancelling].contains($0.state)
        } == true
        return showsRetainedReport || failureCode != nil || newerAttemptActive
            ? "today.historical_delivery" : nil
    }
    public let schedule: DailyScheduleV1?
    public let nextRun: Date?
    public let schedulesPaused: Bool
    public let failureCode: String?
    public var canQueueResearch: Bool { otherActiveTopicID != nil && failureCode == nil }
    public var researchFailureTime: Date? {
        guard failureCode != nil, let latestResearchJob else { return nil }
        return latestResearchJob.completedAt ?? latestResearchJob.startedAt ?? latestResearchJob.createdAt
    }
    public var researchFailureStageKey: String? {
        guard let failureCode, observedFailureStageCodes.contains(failureCode),
              let stage = latestResearchJob?.stage else { return nil }
        switch stage {
        case .wechatDraft, .email, .complete: return nil
        default: return "failure_stage.\(stage.rawValue)"
        }
    }

    public init(topic: TopicRecordV1?, jobs: [JobRecordV1], reports: [ReportRecordV1],
                schedules: [DailyScheduleV1], schedulesPaused: Bool, now: Date, calendar: Calendar) {
        self.topic = topic
        topicID = topic?.id
        otherActiveTopicID = jobs.first {
            [.running, .cancelling].contains($0.state) && $0.topicID != topic?.id
        }?.topicID
        self.schedulesPaused = schedulesPaused
        let scopedJobs = jobs.filter { $0.topicID == topic?.id }.sorted {
            if $0.createdAt != $1.createdAt { return $0.createdAt > $1.createdAt }
            return $0.id.uuidString > $1.id.uuidString
        }
        self.jobs = scopedJobs.map(JobPresentation.init(job:))
        activeJob = scopedJobs.first { [.running, .cancelling].contains($0.state) }.map(Self.displayJob)
        latestResearchJob = scopedJobs.first { $0.kind == .research }.map(Self.displayJob)
        // Research outcome and retained report are independent of subsequent channel jobs.
        let researchJobs = scopedJobs.filter { $0.kind == .research }
        let current = researchJobs.first { [.running, .cancelling].contains($0.state) }
            ?? researchJobs.first { $0.state == .pending }
            ?? researchJobs.first
            ?? scopedJobs.first
        job = current.map(JobPresentation.init(job:))
        failureCode = current.flatMap { job in
            guard job.kind == .research,
                  [.failed, .cancelled, .interrupted].contains(job.state) else { return nil }
            guard let code = job.error?.code, UserFacingErrorCatalog.knownCodes.contains(code) else {
                return "engine_failed"
            }
            return code
        }
        stage = job?.stage
        let scopedReports = reports.filter { $0.topicID == topic?.id }.sorted {
            if $0.reportDate != $1.reportDate { return $0.reportDate > $1.reportDate }
            if $0.createdAt != $1.createdAt { return $0.createdAt > $1.createdAt }
            return $0.id.uuidString > $1.id.uuidString
        }
        let attempt = scopedReports.first.map(Self.displayReport)
        latestAttemptReport = attempt
        latestAttemptHasDeliveryJobs = jobs.contains {
            $0.kind == .delivery && $0.topicID == topic?.id
                && $0.runDirectory == attempt?.runDirectory
        }
        let report = scopedReports.first(where: \.isEffectiveDeepReport).map(Self.displayReport)
        latestReport = report
        if topic == nil {
            status = .noTopic
        } else if let attempt = latestAttemptReport,
                  current == nil || current?.kind == .delivery
                    || current.map({ [.succeeded, .partialSuccess].contains($0.state) }) == true {
            switch attempt.researchOutcome?.status {
            case .noNewContent: status = .noNewContent
            case .incomplete: status = .incomplete
            case .ready, nil:
                if !attempt.isEffectiveDeepReport {
                    status = attempt.researchOutcome == nil ? .outcomeUnknown : .incomplete
                } else {
                    let deliveryAttention = report?.deliveries.contains { [.failed, .unknown].contains($0.state) } == true
                        || (current?.kind == .delivery && current.map { [.failed, .cancelled, .interrupted, .deliveryUnknown].contains($0.state) } == true)
                    status = deliveryAttention || current?.state == .partialSuccess ? .partialSuccess : .succeeded
                }
            }
        } else {
            status = current.map { TodayStatus(state: $0.state) } ?? (report == nil ? .idle : .succeeded)
        }
        schedule = schedules.first { $0.topicID == topic?.id }
        nextRun = schedulesPaused ? nil : ScheduleEvaluator().nextFireDate(
            schedules: schedule.map { [$0] } ?? [], topics: topic.map { [$0] } ?? [],
            after: now, calendar: calendar
        )
    }

    private static func displayJob(_ job: JobRecordV1) -> JobRecordV1 {
        var safe = job
        safe.error = nil; safe.jobDirectory = ""; safe.runDirectory = nil
        return safe
    }

    private static func displayReport(_ report: ReportRecordV1) -> ReportRecordV1 {
        var safe = report
        safe.deliveries = report.deliveries.map { record in
            var delivery = record; delivery.error = nil; return delivery
        }
        return safe
    }
}
