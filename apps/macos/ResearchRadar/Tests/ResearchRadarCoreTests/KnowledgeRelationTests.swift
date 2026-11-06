import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct KnowledgeRelationTests {
    @Test func savedRelationsRoundTripWithoutRewritingEitherEndpointEvidence() throws {
        let data = try relationFixtureData()
        let decoded = try EngineProtocolCodec.decodeResult(data)
        let encoded = try EngineProtocolCodec.encode(decoded)
        let object = try #require(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        let knowledge = try #require(object["knowledge"] as? [String: Any])
        let graph = try #require(knowledge["graph"] as? [String: Any])
        let relations = try #require(graph["relations"] as? [[String: Any]])
        #expect(relations.count == 1)
        #expect(relations[0]["reason"] as? String == "Offline relation fixture; not a research conclusion.")
        #expect(decoded.knowledge?.graph?.references.map { $0.evidence[0].quote } == [
            "Original source quote A.", "Original source quote B."])
    }

    @Test(arguments: ["unknown_kind", "unknown_basis", "self", "unknown_endpoint", "unknown_ref", "one_sided", "duplicate", "count", "unknown_field"])
    func rejectsInvalidSavedRelations(change: String) throws {
        var object = try #require(JSONSerialization.jsonObject(with: relationFixtureData()) as? [String: Any])
        var knowledge = try #require(object["knowledge"] as? [String: Any])
        var graph = try #require(knowledge["graph"] as? [String: Any])
        var relations = try #require(graph["relations"] as? [[String: Any]])
        switch change {
        case "unknown_kind": relations[0]["kind"] = "proves"
        case "unknown_basis": relations[0]["basis"] = "unknown"
        case "self": relations[0]["target"] = relations[0]["source"]
        case "unknown_endpoint": relations[0]["target"] = String(repeating: "0", count: 64)
        case "unknown_ref": relations[0]["ref_ids"] = [String(repeating: "0", count: 64)]
        case "one_sided": relations[0]["ref_ids"] = [String(repeating: "7", count: 64)]
        case "duplicate":
            var second = relations[0]
            second["id"] = String(repeating: "c", count: 64)
            second["source"] = relations[0]["target"]; second["target"] = relations[0]["source"]
            relations.append(second)
            var summary = try #require(knowledge["current"] as? [String: Any])
            summary["relation_count"] = 2; knowledge["current"] = summary
        case "count": relations = []
        case "unknown_field": relations[0]["api_key"] = "not-a-key"
        default: Issue.record("Unknown test mutation")
        }
        graph["relations"] = relations; knowledge["graph"] = graph; object["knowledge"] = knowledge
        #expect(throws: EngineProtocolError.self) {
            _ = try EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: object))
        }
    }

    @Test func oldProjectionWithoutRelationsIsOnlyValidWhenCountIsZero() throws {
        let old = try Data(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appending(path: "Fixtures/Protocol/topic-knowledge-graph-result.json"))
        #expect(throws: Never.self) { _ = try EngineProtocolCodec.decodeResult(old) }
        var object = try #require(JSONSerialization.jsonObject(with: relationFixtureData()) as? [String: Any])
        var knowledge = try #require(object["knowledge"] as? [String: Any])
        var graph = try #require(knowledge["graph"] as? [String: Any])
        graph.removeValue(forKey: "relations"); knowledge["graph"] = graph; object["knowledge"] = knowledge
        #expect(throws: EngineProtocolError.self) {
            _ = try EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: object))
        }
    }
}

func relationFixtureData() throws -> Data {
    let data = try Data(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .deletingLastPathComponent().appending(path: "Fixtures/Protocol/topic-knowledge-graph-result.json"))
    var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    var knowledge = try #require(object["knowledge"] as? [String: Any])
    var graph = try #require(knowledge["graph"] as? [String: Any])
    var summary = try #require(knowledge["current"] as? [String: Any])
    summary["relation_count"] = 1; knowledge["current"] = summary
    graph["relations"] = [[
        "id": String(repeating: "a", count: 64),
        "source": String(repeating: "3", count: 64), "target": String(repeating: "4", count: 64),
        "kind": "shared_problem", "basis": "synthesis",
        "reason": "Offline relation fixture; not a research conclusion.",
        "ref_ids": [String(repeating: "7", count: 64), String(repeating: "8", count: 64)]
    ]]
    knowledge["graph"] = graph; object["knowledge"] = knowledge
    return try JSONSerialization.data(withJSONObject: object)
}
