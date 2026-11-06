import Foundation

/// Validates the wire projection, not the semantic truth of AI organization.
enum KnowledgeGraphValidation {
    static func validate(_ data: Data, summary: KnowledgeSummaryV1) throws {
        let object = try JSONSerialization.jsonObject(with: data)
        guard let dictionary = object as? [String: Any] else { throw EngineProtocolError.invalidValue }
        let base: Set<String> = ["snapshot_id", "research_question", "facets", "groups", "papers", "references"]
        let graph = try exact(object, dictionary.keys.contains("relations") ? base.union(["relations"]) : base)
        if dictionary.keys.contains("relations") {
            for relation in try array(graph["relations"]) {
                _ = try exact(relation, ["id", "source", "target", "kind", "basis", "reason", "ref_ids"])
            }
        }
        for facet in try array(graph["facets"]) { _ = try exact(facet, ["id", "label", "description"]) }
        for group in try array(graph["groups"]) {
            let g = try exact(group, ["id", "facet_id", "label", "members"])
            for member in try array(g["members"]) { _ = try exact(member, ["paper_key", "reason", "ref_ids"]) }
        }
        for paper in try array(graph["papers"]) {
            let p = try exact(paper, ["paper_key", "paper_id", "version", "title", "keywords", "features"])
            for keyword in try array(p["keywords"]) { _ = try exact(keyword, ["label", "ref_ids"]) }
            for feature in try array(p["features"]) {
                _ = try exact(feature, ["name", "value", "basis", "ref_ids", "missing_reason"])
            }
        }
        for ref in try array(graph["references"]) {
            let r = try exact(ref, ["ref_id", "paper_key", "report_id", "report_date", "report_sha256", "json_pointer", "text", "evidence"])
            for evidence in try array(r["evidence"]) { _ = try exact(evidence, ["source_url", "quote", "location"]) }
        }
        let value: KnowledgeGraphV1
        do { value = try JSONDecoder().decode(KnowledgeGraphV1.self, from: data) }
        catch { throw EngineProtocolError.invalidValue }
        try validate(value, summary: summary)
    }

    private static func validate(_ graph: KnowledgeGraphV1, summary: KnowledgeSummaryV1) throws {
        guard graph.snapshotID == summary.snapshotID, text(graph.researchQuestion),
              graph.papers.count == summary.paperCount, graph.groups.count == summary.groupCount,
              graph.papers.reduce(0, { $0 + $1.features.count }) == summary.featureCount,
              graph.relations.count == summary.relationCount, unique(graph.relations.map(\.id)),
              unique(graph.facets.map(\.id)), unique(graph.groups.map(\.id)),
              unique(graph.papers.map(\.paperKey)), unique(graph.references.map(\.refID))
        else { throw EngineProtocolError.invalidValue }
        let paperKeys = Set(graph.papers.map(\.paperKey)), facets = Set(graph.facets.map(\.id))
        let refs = Dictionary(uniqueKeysWithValues: graph.references.map { ($0.refID, $0) })
        for facet in graph.facets {
            guard facet.id.range(of: "^[a-z][a-z0-9_-]{0,79}$", options: .regularExpression) != nil,
                  text(facet.label), text(facet.description) else { throw EngineProtocolError.invalidValue }
        }
        for ref in graph.references {
            guard digest(ref.refID), paperKeys.contains(ref.paperKey), summary.reportIDs.contains(ref.reportID),
                  digest(ref.reportSHA256), sourceText(ref.text), date(ref.reportDate), !ref.evidence.isEmpty,
                  ref.jsonPointer.range(of: "^/sections/[0-9]+/metadata/deep_reads/[0-9]+/claims/[0-9]+$",
                                        options: .regularExpression) != nil
            else { throw EngineProtocolError.invalidValue }
            for evidence in ref.evidence {
                guard safeURL(evidence.sourceURL), sourceText(evidence.quote), sourceText(evidence.location)
                else { throw EngineProtocolError.invalidValue }
            }
        }
        for paper in graph.papers {
            guard digest(paper.paperKey), digest(paper.paperID), sourceText(paper.title),
                  paper.version.map(sourceText) ?? true else { throw EngineProtocolError.invalidValue }
            for keyword in paper.keywords {
                guard text(keyword.label) else { throw EngineProtocolError.invalidValue }
                try references(keyword.refIDs, owner: paper.paperKey, in: refs)
            }
            for feature in paper.features {
                guard text(feature.name) else { throw EngineProtocolError.invalidValue }
                if feature.basis == .unknown {
                    guard feature.value == nil, feature.refIDs.isEmpty, feature.missingReason.map(text) == true
                    else { throw EngineProtocolError.invalidValue }
                } else {
                    guard feature.value.map(text) == true, feature.missingReason == nil else { throw EngineProtocolError.invalidValue }
                    try references(feature.refIDs, owner: paper.paperKey, in: refs)
                }
            }
        }
        for group in graph.groups {
            guard digest(group.id), facets.contains(group.facetID), text(group.label), !group.members.isEmpty,
                  unique(group.members.map(\.paperKey)) else { throw EngineProtocolError.invalidValue }
            for member in group.members {
                guard paperKeys.contains(member.paperKey), text(member.reason) else { throw EngineProtocolError.invalidValue }
                try references(member.refIDs, owner: member.paperKey, in: refs)
            }
        }
        var pairs = Set<[String]>()
        for relation in graph.relations {
            let endpoints: Set<String> = [relation.source, relation.target]
            let pair = endpoints.sorted() + [relation.kind.rawValue]
            guard digest(relation.id), endpoints.count == 2, endpoints.isSubset(of: paperKeys),
                  text(relation.reason), unique(relation.refIDs),
                  relation.refIDs.allSatisfy({ refs[$0] != nil }),
                  Set(relation.refIDs.compactMap { refs[$0]?.paperKey }) == endpoints,
                  pairs.insert(pair).inserted
            else { throw EngineProtocolError.invalidValue }
        }
    }

    private static func references(_ ids: [String], owner: String, in refs: [String: KnowledgeReferenceV1]) throws {
        guard !ids.isEmpty, unique(ids), ids.allSatisfy({ refs[$0]?.paperKey == owner })
        else { throw EngineProtocolError.invalidValue }
    }
    private static func exact(_ value: Any?, _ keys: Set<String>) throws -> [String: Any] {
        guard let object = value as? [String: Any], Set(object.keys) == keys else { throw EngineProtocolError.unexpectedFields }
        return object
    }
    private static func array(_ value: Any?) throws -> [Any] {
        guard let value = value as? [Any] else { throw EngineProtocolError.invalidValue }; return value
    }
    private static func unique(_ values: [String]) -> Bool { Set(values).count == values.count }
    private static func sourceText(_ value: String) -> Bool { !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    private static func text(_ value: String) -> Bool { sourceText(value) && value.count <= 10_000 }
    private static func digest(_ value: String) -> Bool {
        value.count == 64 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    private static func safeURL(_ value: String) -> Bool {
        guard let url = URLComponents(string: value) else { return false }
        return ["http", "https"].contains(url.scheme?.lowercased() ?? "") && url.host?.isEmpty == false && url.user == nil && url.password == nil
    }
    private static func date(_ value: String) -> Bool {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        return value.count == 10 && formatter.date(from: value).map { formatter.string(from: $0) == value } == true
    }
}
