import ResearchRadarCore

/// Display-only partitions; overlapping cards retain the same underlying paper identity.
enum KnowledgeClassificationLayout {
    struct Section: Identifiable {
        let group: KnowledgeGroupV1?
        let papers: [KnowledgePaperV1]
        var id: String { group.map { "group:" + $0.id } ?? "unclassified" }
    }
    struct Position: Hashable {
        let sectionID: String
        let paperKey: String
    }

    static func sections(groups: [KnowledgeGroupV1], papers: [KnowledgePaperV1]) -> [Section] {
        var sections = groups.compactMap { group -> Section? in
            let keys = Set(group.members.map(\.paperKey))
            let members = papers.filter { keys.contains($0.id) }
            return members.isEmpty ? nil : Section(group: group, papers: members)
        }
        let grouped = Set(groups.flatMap { $0.members.map(\.paperKey) })
        let unclassified = papers.filter { !grouped.contains($0.id) }
        if !unclassified.isEmpty { sections.append(.init(group: nil, papers: unclassified)) }
        return sections
    }

}
