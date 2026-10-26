import Foundation
import Observation
import ResearchRadarCore

@MainActor @Observable final class ReportBrowserModel {
    enum Page: Hashable { case overview, paper(Int), fullReport }
    var page: Page = .overview
    private(set) var contents: ReportContents?
    private(set) var loadFailed = false
    var showsDelivery: Bool { page == .overview }

    var selectedPaper: ReportContents.Paper? {
        guard case .paper(let id) = page else { return nil }
        return contents?.papers.first { $0.id == id }
    }

    func load(report: ReportRecordV1, workspaceRoot: URL) async {
        let task = Task.detached(priority: .userInitiated) {
            try ReportContents.load(report: report, workspaceRoot: workspaceRoot)
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
    }

    func back() { page = .overview }
}
