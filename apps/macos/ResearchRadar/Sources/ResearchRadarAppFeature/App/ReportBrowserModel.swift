import Foundation
import Observation
import ResearchRadarCore

@MainActor @Observable final class ReportBrowserModel {
    enum Page: Hashable { case overview, paper(Int), fullReport }
    var page: Page = .overview
    private(set) var contents: ReportContents?
    private(set) var loadFailed = false
    private(set) var initialEvidenceTarget: Int?
    private(set) var initialEvidenceClaimIndex: Int?
    var initialEvidenceAnchor: PaperReadingSection.ID {
        initialEvidenceClaimIndex.map { .claim($0) } ?? .evidence
    }
    var showsDelivery: Bool { page == .overview }

    var selectedPaper: ReportContents.Paper? {
        guard case .paper(let id) = page else { return nil }
        return contents?.papers.first { $0.id == id }
    }

    func load(report: ReportRecordV1, workspaceRoot: URL, expectedSHA256: String? = nil) async {
        let task = Task.detached(priority: .userInitiated) {
            try ReportContents.load(report: report, workspaceRoot: workspaceRoot, expectedSHA256: expectedSHA256)
        }
        do {
            let value = try await task.value
            guard !Task.isCancelled else { return }
            contents = value
            loadFailed = false
        } catch {
            guard !Task.isCancelled else { return }
            contents = nil
            loadFailed = true
        }
    }

    func openPaper(_ id: Int) {
        guard contents?.papers.contains(where: { $0.id == id }) == true else { return }
        page = .paper(id)
        finishInitialEvidenceNavigation()
    }

    func openLedgerEntry(_ entry: PaperLedgerEntry) {
        guard let index = entry.paperIndex,
              let paper = contents?.papers.first(where: { $0.id == index }),
              let sourceURL = paper.sourceURL,
              sourceURL == URL(string: entry.sourceURL) else { return }
        if let claimIndex = entry.evidenceClaimIndex {
            guard entry.evidence, paper.claims.indices.contains(claimIndex) else { return }
        }
        openPaper(index)
        initialEvidenceTarget = entry.evidence ? index : nil
        initialEvidenceClaimIndex = entry.evidenceClaimIndex
    }

    func finishInitialEvidenceNavigation() {
        initialEvidenceTarget = nil
        initialEvidenceClaimIndex = nil
    }

    func back() { page = .overview; finishInitialEvidenceNavigation() }
}
