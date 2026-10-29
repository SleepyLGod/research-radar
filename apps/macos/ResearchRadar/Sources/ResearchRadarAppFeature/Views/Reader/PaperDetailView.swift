import AppKit
import ResearchRadarCore
import SwiftUI

struct PaperDetailView: View {
    let paper: ReportContents.Paper
    let figures: [PaperFiguresModel.Figure]
    let localization: LocalizationStore

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
        if !figures.isEmpty {
            Text(localization.text("paper.figures")).font(.system(size: 16, weight: .semibold))
                .id(PaperReadingSection.ID.figures)
            ForEach(figures) { figure in
                PaperFigureView(figure: figure, localization: localization)
            }
        }
        if !paper.claims.isEmpty {
            Divider()
            VStack(alignment: .leading, spacing: 20) {
                Text(localization.text("paper.claims")).font(.system(size: 16, weight: .semibold))
                ForEach(paper.claims.indices, id: \.self) { index in
                    PaperEvidenceView(claim: paper.claims[index], localization: localization)
                        .id(PaperReadingSection.ID.claim(index))
                }
            }.id(PaperReadingSection.ID.evidence)
        }
    }
}

private struct PaperFigureView: View {
    let figure: PaperFiguresModel.Figure
    let localization: LocalizationStore

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(nsImage: figure.image).resizable().scaledToFit().accessibilityLabel(figure.content.displayCaption)
            Text(figure.content.displayCaption).font(.system(size: 13)).textSelection(.enabled)
            if let explanation = figure.content.explanation, !explanation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(explanation).font(.system(size: 14)).lineSpacing(5).textSelection(.enabled)
            }
            if let original = figure.content.originalCaption {
                DisclosureGroup(localization.text("paper.original_caption")) {
                    Text(original).font(.system(size: 13)).textSelection(.enabled)
                }
            }
            if let attribution = figure.content.attribution {
                Text(attribution).font(.system(size: 12)).foregroundStyle(.secondary)
            }
        }
    }
}
