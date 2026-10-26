import Foundation
import ResearchRadarCore

/// A read-only projection of the already-filtered public draft, not raw reader output.
struct ReportContents: Sendable {
    struct Source: Decodable, Sendable {
        let title: String?
        let gist: String?
        let version: String?
        private let url: String?
        var sourceURL: URL? { ReportContents.safeURL(url) }
    }

    struct Evidence: Decodable, Sendable {
        let quote: String
        let location: String?
        private let sourceUrl: String?
        var url: URL? { ReportContents.safeURL(sourceUrl) }
    }

    struct Claim: Decodable, Sendable {
        let text: String
        let evidence: [Evidence]
    }

    struct Figure: Decodable, Sendable {
        let relativePath: String
        let caption: String
        let localizedCaption: String?
        let attribution: String?
        let renderable: Bool?
        private let originalPath: String?

        var displayCaption: String { ReportContents.nonempty(localizedCaption) ?? caption }
        var isPublicFigure: Bool {
            // Match the existing public renderers' exclusion of legacy page screenshots.
            renderable != false &&
                (originalPath ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    .range(of: #"^page\s+\d+$"#, options: [.regularExpression, .caseInsensitive]) == nil &&
                relativePath.range(of: #"(?:^|/)\d{2}-page-\d+\.png$"#, options: .regularExpression) == nil
        }
    }

    struct Paragraph: Sendable {
        let key: String
        let text: String
    }

    struct Paper: Identifiable, Sendable {
        let id: Int
        let title: String
        let summary: String
        let sourceURL: URL?
        let version: String?
        let paragraphs: [Paragraph]
        let claims: [Claim]
        let figures: [Figure]
    }

    let papers: [Paper]
    let sources: [Source]

    static func load(report: ReportRecordV1, workspaceRoot: URL) throws -> Self {
        let policy = try ReportReaderPolicy(report: report, workspaceRoot: workspaceRoot)
        return try decode(policy.articleDraftData(), topicID: report.topicID)
    }

    static func decode(_ data: Data, topicID: String) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let draft = try decoder.decode(Draft.self, from: data)
        guard draft.topicId == topicID else { throw ReportReaderPolicy.Failure.invalidReport }
        let entries = draft.sections.filter { $0.metadata?.kind == "deep_reads" }
            .flatMap { $0.metadata?.deepReads ?? [] }
        let papers = entries.enumerated().compactMap { index, entry -> Paper? in
            guard !entry.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  !entry.claims.isEmpty, entry.claims.allSatisfy({ !$0.text.isEmpty }) else { return nil }
            let explanation = (entry.readerExplanation ?? [:]).compactMapValues(nonempty)
            let values: [(String, String?)] = [
                ("context", explanation["opening_context"]),
                ("thesis", explanation["core_thesis"] ?? nonempty(entry.essence)),
                ("problem", explanation["problem_walkthrough"] ?? entry.problem?.core),
                ("method", explanation["solution_walkthrough"] ?? entry.solution?.core),
                ("experiments", explanation["experiment_interpretation"] ?? entry.experiments?.summary),
                ("related", explanation["related_work_context"] ?? entry.relatedWork?.novelty),
                ("limitations", explanation["limitations_discussion"] ?? entry.limitations?.explicitLimitations?.joined(separator: "\n\n")),
                ("example", explanation["plain_language_story"]),
                ("takeaway", explanation["reader_takeaway"] ?? entry.criticalAssessment?.bottomLine)
            ]
            var seen = Set<String>()
            let paragraphs = values.compactMap { key, text -> Paragraph? in
                guard let text = text?.trimmingCharacters(in: .whitespacesAndNewlines),
                      !text.isEmpty, seen.insert(text).inserted else { return nil }
                return Paragraph(key: key, text: text)
            }
            return Paper(id: index, title: entry.title,
                summary: explanation["core_thesis"] ?? nonempty(entry.essence) ?? entry.claims[0].text,
                sourceURL: entry.source?.sourceURL, version: entry.source?.version,
                paragraphs: paragraphs, claims: entry.claims,
                figures: (entry.figures ?? []).filter(\.isPublicFigure))
        }
        let sources = draft.sections.filter { $0.metadata?.kind == "new_updated_sources" }
            .flatMap { $0.metadata?.sources ?? [] }.filter { !($0.title ?? "").isEmpty }
        return Self(papers: papers, sources: sources)
    }

    private static func safeURL(_ text: String?) -> URL? {
        guard let text, let url = URL(string: text), ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              let host = url.host, !host.isEmpty, url.user == nil, url.password == nil else { return nil }
        return url
    }

    private static func nonempty(_ text: String?) -> String? {
        guard let text = text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return text
    }

    private struct Draft: Decodable {
        let topicId: String
        let sections: [Section]
    }
    private struct Section: Decodable { let metadata: Metadata? }
    private struct Metadata: Decodable {
        let kind: String?
        let deepReads: [Entry]?
        let sources: [Source]?
    }
    private struct Fields: Decodable {
        let core: String?
        let summary: String?
        let novelty: String?
        let explicitLimitations: [String]?
        let bottomLine: String?
    }
    private struct Entry: Decodable {
        let title: String
        let source: Source?
        let essence: String?
        let readerExplanation: [String: String]?
        let problem: Fields?
        let solution: Fields?
        let experiments: Fields?
        let relatedWork: Fields?
        let limitations: Fields?
        let criticalAssessment: Fields?
        let claims: [Claim]
        let figures: [Figure]?
    }
}
