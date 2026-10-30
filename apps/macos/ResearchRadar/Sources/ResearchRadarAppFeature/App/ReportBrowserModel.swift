import Foundation
import Observation
import ResearchRadarCore

@MainActor @Observable final class ReportBrowserModel {
    enum Page: Hashable { case overview, paper(Int), fullReport }
    var page: Page = .overview
    private(set) var contents: ReportContents?
    private(set) var loadFailed = false
    var evidenceExpanded = false
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
        evidenceExpanded = false
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
        if entry.evidence { revealEvidence(claimIndex: entry.evidenceClaimIndex) }
    }

    func revealEvidence(claimIndex: Int? = nil) {
        guard let paper = selectedPaper, !paper.claims.isEmpty else { return }
        if let claimIndex, !paper.claims.indices.contains(claimIndex) { return }
        evidenceExpanded = true
        initialEvidenceTarget = paper.id
        initialEvidenceClaimIndex = claimIndex
    }

    /// Return nil when expansion must settle before scrolling.
    func prepareSectionJump(to section: PaperReadingSection.ID) -> PaperReadingSection.ID? {
        if section == .evidence && !evidenceExpanded {
            revealEvidence()
            return nil
        }
        finishInitialEvidenceNavigation()
        return section
    }

    func finishInitialEvidenceNavigation() {
        initialEvidenceTarget = nil
        initialEvidenceClaimIndex = nil
    }

    func back() { page = .overview; finishInitialEvidenceNavigation() }
}
