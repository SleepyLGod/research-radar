import AppKit
import ResearchRadarCore
import SwiftUI

struct PaperDetailView: View {
    let paper: ReportContents.Paper
    let report: ReportRecordV1
    let workspace: URL
    let localization: LocalizationStore
    let visible: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(paper.title).font(.system(size: 22, weight: .semibold)).lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            if let url = paper.sourceURL {
                Link(destination: url) { Label(localization.text("paper.original"), systemImage: "arrow.up.right") }
                    .font(.system(size: 13))
            }
        }.padding(.bottom, 4)
        ForEach(paper.paragraphs, id: \.key) { paragraph in
            VStack(alignment: .leading, spacing: 10) {
                Text(localization.text("paper.\(paragraph.key)")).font(.system(size: 16, weight: .semibold))
                Text(paragraph.text).font(.system(size: 15)).lineSpacing(6).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }.id(PaperReadingSection.ID.paragraph(paragraph.key))
        }
        if !paper.figures.isEmpty {
            Text(localization.text("paper.figures")).font(.system(size: 16, weight: .semibold))
                .id(PaperReadingSection.ID.figures)
            ForEach(paper.figures.indices, id: \.self) { index in
                if visible {
                    PaperFigureView(figure: paper.figures[index], report: report, workspace: workspace)
                }
            }
        }
        if !paper.claims.isEmpty {
            Divider()
            VStack(alignment: .leading, spacing: 20) {
                Text(localization.text("paper.claims")).font(.system(size: 16, weight: .semibold))
                ForEach(paper.claims.indices, id: \.self) { index in
                    PaperEvidenceView(claim: paper.claims[index], localization: localization)
                }
            }.id(PaperReadingSection.ID.evidence)
        }
    }
}

private struct PaperFigureView: View {
    let figure: ReportContents.Figure
    let report: ReportRecordV1
    let workspace: URL
    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                VStack(alignment: .leading, spacing: 8) {
                    Image(nsImage: image).resizable().scaledToFit().accessibilityLabel(figure.displayCaption)
                    Text(figure.displayCaption).font(.system(size: 13))
                    if let attribution = figure.attribution {
                        Text(attribution).font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .task(id: figure.relativePath) {
            let task = Task.detached(priority: .userInitiated) {
                try ReportFigureLoader.thumbnailData(path: figure.relativePath, report: report, workspace: workspace)
            }
            // Optional figures fail closed; captions never float without their image.
            guard let data = try? await task.value, !Task.isCancelled else { return }
            image = NSImage(data: data)
        }
    }
}
