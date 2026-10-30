import AppKit
import Observation
import ResearchRadarCore

/// Visible-paper thumbnails only; headings and chapter navigation use the same loaded images.
@MainActor @Observable final class PaperFiguresModel {
    struct Figure: Identifiable {
        let id: Int
        let content: ReportContents.Figure
        let image: NSImage
    }

    private struct Thumbnail: Sendable {
        let id: Int
        let content: ReportContents.Figure
        let data: Data
    }

    private var generation = UUID()
    private var paperID: Int?
    private var figures: [Figure] = []
    private(set) var settledPaperID: Int?

    func images(for paperID: Int) -> [Figure] { self.paperID == paperID ? figures : [] }

    func load(paper: ReportContents.Paper?, report: ReportRecordV1, workspace: URL) async {
        guard !Task.isCancelled else { return }
        let token = UUID()
        generation = token
        paperID = paper?.id
        figures = []
        settledPaperID = nil
        guard let paper else { return }
        let task = Task.detached(priority: .userInitiated) {
            var thumbnails: [Thumbnail] = []
            for (id, figure) in paper.figures.enumerated() {
                guard !Task.isCancelled else { break }
                // Missing, unsafe or undecodable optional figures are omitted as a whole.
                if let data = try? ReportFigureLoader.thumbnailData(path: figure.relativePath, report: report, workspace: workspace) {
                    thumbnails.append(Thumbnail(id: id, content: figure, data: data))
                }
            }
            return thumbnails
        }
        let thumbnails = await withTaskCancellationHandler {
            await task.value
        } onCancel: { task.cancel() }
        guard generation == token, !Task.isCancelled else { return }
        figures = thumbnails.compactMap { thumbnail in
            guard let image = NSImage(data: thumbnail.data) else { return nil }
            return Figure(id: thumbnail.id, content: thumbnail.content, image: image)
        }
        settledPaperID = paper.id
    }
}
