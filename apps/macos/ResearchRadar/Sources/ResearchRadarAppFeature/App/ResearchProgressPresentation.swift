import Foundation
import ResearchRadarCore

/// A snapshot of the observed phase, not an execution history or percentage.
struct ResearchProgressPresentation: Equatable {
    enum StepState { case unreported, current, stopping, stopped }

    struct Step: Equatable, Identifiable {
        let stage: ResearchStage
        let state: StepState
        var id: ResearchStage { stage }
        var symbol: String {
            if state == .stopped { return "exclamationmark.circle" }
            switch stage {
            case .discovery: return "sparkle.magnifyingglass"
            case .reading: return "book"
            case .verification: return "checkmark.shield"
            case .composition: return "doc.text"
            }
        }
        var statusKey: String? {
            switch state {
            case .unreported: nil
            case .current: "timeline.current"
            case .stopping: "today.cancelling"
            case .stopped: "timeline.stopped"
            }
        }
    }

    let isActive: Bool
    let hasAttempt: Bool
    let statusKey: String
    let detailKey: String?
    let attemptDate: Date?
    let steps: [Step]

    init(today: TodayPresentation) {
        let job = today.job.flatMap { $0.kind == .research ? $0 : nil }
        isActive = job.map { [.pending, .running, .cancelling].contains($0.state) } ?? false
        hasAttempt = job != nil || today.latestAttemptReport != nil
        // Channel attention belongs to the report, not the research phase strip.
        statusKey = today.status == .partialSuccess ? "today.succeeded"
            : job == nil && today.latestAttemptReport == nil ? "today.idle" : today.statusKey
        attemptDate = today.latestResearchJob.flatMap {
            $0.id == job?.id ? ($0.completedAt ?? $0.startedAt ?? $0.createdAt) : nil
        } ?? (job == nil ? today.latestAttemptReport?.createdAt : nil)
        if job?.state == .pending { detailKey = "progress.queued" }
        else if job?.state == .cancelling { detailKey = "progress.stopping" }
        else if job?.state == .running {
            detailKey = job?.stage.map { "progress.\($0.rawValue)" } ?? "progress.waiting_stage"
        } else { detailKey = nil }
        steps = ResearchStage.allCases.map { stage in
            let state: StepState
            if job?.stage != stage { state = .unreported }
            else {
                switch job?.state {
                case .running: state = .current
                case .cancelling: state = .stopping
                case .failed, .cancelled, .interrupted: state = .stopped
                default: state = .unreported
                }
            }
            return Step(stage: stage, state: state)
        }
    }
}

extension TodayPresentation {
    var researchProgress: ResearchProgressPresentation { .init(today: self) }

    var prefersReportFirst: Bool {
        latestReport != nil && !researchProgress.isActive && failureCode == nil && !showsRetainedReport
    }

    var reportSectionKey: String {
        researchProgress.isActive || failureCode != nil || showsRetainedReport
            ? "today.last_successful_report" : "home.latest_report"
    }
}
