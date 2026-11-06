import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct KnowledgeGraphTests {
    @Test func graphFixtureRoundTripsWithoutChangingEvidence() throws {
        let data = try graphFixture()
        let result = try EngineProtocolCodec.decodeResult(data)
        #expect(try EngineProtocolCodec.decodeResult(EngineProtocolCodec.encode(result)) == result)
        #expect(result.knowledge?.current?.paperCount == 2)
    }

    @Test(arguments: ["snapshot", "unknown_ref", "cross_paper", "duplicate_paper", "unsafe_url", "unknown_field", "count", "pointer"])
    func rejectsInvalidClassificationProjection(change: String) throws {
        var result = try #require(JSONSerialization.jsonObject(with: graphFixture()) as? [String: Any])
        var knowledge = try #require(result["knowledge"] as? [String: Any])
        var graph = try #require(knowledge["graph"] as? [String: Any])
        var papers = try #require(graph["papers"] as? [[String: Any]])
        var refs = try #require(graph["references"] as? [[String: Any]])
        switch change {
        case "snapshot": graph["snapshot_id"] = String(repeating: "c", count: 32)
        case "unknown_ref", "cross_paper":
            var groups = try #require(graph["groups"] as? [[String: Any]])
            var members = try #require(groups[0]["members"] as? [[String: Any]])
            members[0]["ref_ids"] = [change == "unknown_ref" ? String(repeating: "0", count: 64) : refs[1]["ref_id"]!]
            groups[0]["members"] = members; graph["groups"] = groups
        case "duplicate_paper": papers[1] = papers[0]; graph["papers"] = papers
        case "unsafe_url":
            var evidence = try #require(refs[0]["evidence"] as? [[String: Any]])
            evidence[0]["source_url"] = "file:///private/report"
            refs[0]["evidence"] = evidence; graph["references"] = refs
        case "unknown_field": graph["api_key"] = "not-a-key"
        case "count": graph["papers"] = []
        case "pointer": refs[0]["json_pointer"] = "/secrets/0"; graph["references"] = refs
        default: Issue.record("Unknown mutation")
        }
        knowledge["graph"] = graph; result["knowledge"] = knowledge
        #expect(throws: EngineProtocolError.self) {
            _ = try EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: result))
        }
    }

    @Test func longSavedQuoteIsNotRejectedOrTruncatedAsOrganizationText() throws {
        var result = try #require(JSONSerialization.jsonObject(with: graphFixture()) as? [String: Any])
        var knowledge = try #require(result["knowledge"] as? [String: Any])
        var graph = try #require(knowledge["graph"] as? [String: Any])
        var refs = try #require(graph["references"] as? [[String: Any]])
        var evidence = try #require(refs[0]["evidence"] as? [[String: Any]])
        let quote = String(repeating: "原文证据", count: 3_000)
        evidence[0]["quote"] = quote; refs[0]["evidence"] = evidence
        graph["references"] = refs; knowledge["graph"] = graph; result["knowledge"] = knowledge
        let decoded = try EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: result))
        #expect(decoded.knowledge?.graph?.references.first?.evidence.first?.quote == quote)
    }
}

private func graphFixture() throws -> Data {
    try Data(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .deletingLastPathComponent().appending(path: "Fixtures/Protocol/topic-knowledge-graph-result.json"))
}
