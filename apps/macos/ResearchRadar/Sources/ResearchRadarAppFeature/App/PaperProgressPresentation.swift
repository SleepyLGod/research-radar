import Foundation
import ResearchRadarCore

/// Advisory, bounded to the latest observed research attempt per topic. Not a paper ledger.
struct PaperProgressSnapshot: Equatable, Sendable {
    let requestID: UUID
    private(set) var papers: [EnginePaperProgressV1] = []
    private var lastSequence = 0

    init(requestID: UUID) { self.requestID = requestID }

    mutating func receive(_ event: EngineEventV1) {
        guard event.requestID == requestID, event.sequence > lastSequence,
              event.type == .progress, event.status == .running,
              let paper = event.paper, event.stage == paper.status.stage else { return }
        lastSequence = event.sequence
        if let index = papers.firstIndex(where: { $0.sourceID == paper.sourceID }) {
            papers[index] = paper
        } else { papers.append(paper) }
    }

    func rows(jobState: JobState) -> [PaperProgressRow] {
        papers.map { PaperProgressRow(paper: $0, jobState: jobState) }
    }
}

struct PaperProgressRow: Equatable, Identifiable, Sendable {
    let id: String
    let title: String
    let statusKey: String
    let symbol: String
    let isActive: Bool
    let isWarning: Bool

    init(paper: EnginePaperProgressV1, jobState: JobState) {
        id = paper.sourceID; title = paper.title
        let inFlight = [.acquiring, .acquired, .reading].contains(paper.status)
        isActive = inFlight && jobState == .running
        isWarning = [.acquisitionFailed, .readingFailed, .skipped].contains(paper.status)
        if inFlight && jobState != .running {
            statusKey = jobState == .cancelling ? "paper_progress.stopping"
                : jobState == .cancelled ? "paper_progress.stopped" : "paper_progress.unconfirmed"
            symbol = jobState == .cancelled ? "stop.circle" : "pause.circle"
        } else {
            statusKey = "paper_progress.\(paper.status.rawValue)"
            switch paper.status {
            case .acquiring: symbol = "arrow.down.doc"
            case .acquired: symbol = "doc.text"
            case .reading: symbol = "book"
            case .read: symbol = "checkmark.circle"
            case .acquisitionFailed, .readingFailed: symbol = "exclamationmark.circle"
            case .skipped: symbol = "forward.end"
            }
        }
    }
}

extension AppStore {
    var selectedTopicPaperProgress: [PaperProgressRow] {
        guard let topicID = selectedTopic?.id, let job = todayPresentation.job, job.kind == .research,
              let snapshot = paperProgressByTopic[topicID], snapshot.requestID == job.id else { return [] }
        let state: JobState = cancellationRequested && job.state == .running ? .cancelling : job.state
        return snapshot.rows(jobState: state)
    }

    func receivePaperProgress(_ event: EngineEventV1) {
        guard event.paper != nil,
              let job = jobs.first(where: { $0.id == event.requestID && $0.kind == .research }),
              [.running, .cancelling].contains(job.state) else { return }
        var snapshot = paperProgressByTopic[job.topicID].flatMap {
            $0.requestID == job.id ? $0 : nil
        } ?? PaperProgressSnapshot(requestID: job.id)
        snapshot.receive(event)
        if paperProgressByTopic[job.topicID] != snapshot { paperProgressByTopic[job.topicID] = snapshot }
    }
}
