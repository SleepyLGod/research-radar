import Foundation
import ResearchRadarCore

/// Display labels never replace immutable report or delivery metadata.
enum ReportHeading {
    static func title(report: ReportRecordV1, topic: TopicRecordV1?) -> String {
        guard let topic, topic.id == report.topicID else { return report.title }
        let name = topic.displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? report.title : name
    }
}

struct PaperReadingSection: Identifiable {
    enum ID: Hashable { case paragraph(String), figures, evidence }
    let id: ID

    var titleKey: String {
        switch id {
        case .paragraph(let key): "paper.\(key)"
        case .figures: "paper.figures"
        case .evidence: "paper.claims"
        }
    }
}

struct PaperPreviewSummary {
    let titleKey: String
    let text: String
}

extension ReportContents.Paper {
    var preview: PaperPreviewSummary {
        for key in ["problem", "thesis"] {
            if let paragraph = paragraphs.first(where: { $0.key == key && !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
                return .init(titleKey: "paper.\(key)", text: paragraph.text)
            }
        }
        return .init(titleKey: "paper.preview_summary", text: summary)
    }

    func readingSections(hasAvailableFigures: Bool = false) -> [PaperReadingSection] {
        var sections = paragraphs.map { PaperReadingSection(id: .paragraph($0.key)) }
        if hasAvailableFigures && !figures.isEmpty { sections.append(.init(id: .figures)) }
        if !claims.isEmpty { sections.append(.init(id: .evidence)) }
        return sections
    }
}
