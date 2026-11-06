import AppKit
import Foundation
import SwiftUI
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@MainActor @Suite struct KnowledgeGraphPresentationTests {
    @Test func multiLabelGroupsKeepOnePaperAndKeywordFiltersDoNotInventEdges() throws {
        let model = TopicKnowledgeModel()
        let value = try sample()
        model.accept(value)
        let graph = try #require(model.graph(for: "memory"))
        #expect(model.visibleGraphPapers(for: "memory").count == 2)
        #expect(model.visibleGraphGroups(for: "memory").count == 2)
        model.selectGroup(graph.groups[1].id, topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").map(\.id) == [graph.papers[1].id])
        model.selectGroup(nil, topicID: "memory")
        model.toggleKeyword("conflict", topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").map(\.id) == [graph.papers[1].id])
        model.toggleKeyword("retrieval", topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").count == 2)
        model.setKeywordMatchAll(true, topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").count == 1)
        model.setGraphQuery("no such method", topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").isEmpty)
    }

    @Test func topicAndSnapshotSelectionAreIsolatedAndReturnPreservesFilters() throws {
        let model = TopicKnowledgeModel(), value = try sample()
        model.accept(value)
        let graph = try #require(value.graph)
        model.setGraphScrollPosition(graph.papers[1].id, topicID: "memory")
        model.selectGraphPaper(graph.papers[0].id, topicID: "memory")
        model.setGraphQuery("utility", topicID: "memory")
        #expect(model.graphSelection(for: "memory").paperKey == graph.papers[0].id)
        model.selectGraphPaper(nil, topicID: "memory")
        #expect(model.graphSelection(for: "memory").query == "utility")
        model.accept(.init(topicID: "other", current: nil))
        #expect(model.graphSelection(for: "other").query.isEmpty)
        #expect(model.graphSelection(for: "memory").query == "utility")
        model.accept(value) // A local reread must not reset selection or filters.
        #expect(model.graphSelection(for: "memory").query == "utility")
        #expect(model.graphSelection(for: "memory").scrollPaperKey == graph.papers[1].id)
        model.accept(.init(topicID: "memory", current: nil))
        #expect(model.graphSelection(for: "memory").facetID == nil)
        #expect(model.visibleGraphPapers(for: "memory").isEmpty)
    }

    @Test func noFacetsDoesNotHideUngroupedPapers() throws {
        var object = try #require(JSONSerialization.jsonObject(with: sampleData()) as? [String: Any])
        var value = try #require(object["knowledge"] as? [String: Any])
        var graph = try #require(value["graph"] as? [String: Any])
        graph["facets"] = []; graph["groups"] = []
        var summary = try #require(value["current"] as? [String: Any]); summary["group_count"] = 0
        value["graph"] = graph; value["current"] = summary; object["knowledge"] = value
        let model = TopicKnowledgeModel()
        model.accept(try #require(EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: object)).knowledge))
        #expect(model.visibleGraphGroups(for: "memory").isEmpty)
        #expect(model.visibleGraphPapers(for: "memory").count == 2)
        #expect(model.unclassifiedPaperKeys(for: "memory").count == 2)
    }

    @Test func nativeClassificationAndPaperDetailFitTheWorkspace() async throws {
        _ = NSApplication.shared
        let model = TopicKnowledgeModel(), value = try sample()
        model.accept(value)
        let host = NSHostingView(rootView: KnowledgeGraphView(topicID: "memory", model: model,
            localization: LocalizationStore(preference: .simplifiedChinese), historyPaperIDs: [], openHistory: { _ in }))
        host.sizingOptions = []
        let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 640, height: 480),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        try await Task.sleep(for: .milliseconds(100)); host.layoutSubtreeIfNeeded()
        #expect(host.bounds.width == 640 && host.bounds.height == 480)
        model.selectGraphPaper(value.graph?.papers.first?.id, topicID: "memory")
        try await Task.sleep(for: .milliseconds(100)); host.layoutSubtreeIfNeeded()
        #expect(host.fittingSize.width.isFinite && host.fittingSize.height.isFinite)
        model.selectGraphPaper(nil, topicID: "memory")
        #expect(model.graphSelection(for: "memory").facetID == "mechanism")
    }

    @Test func keywordOnlyPaperRetainsSourceReferencesWithoutFeatures() throws {
        let graph = try #require(sample().graph)
        let source = try #require(graph.papers.first)
        let paper = try JSONDecoder().decode(KnowledgePaperV1.self, from: JSONSerialization.data(withJSONObject: [
            "paper_key": source.paperKey, "paper_id": source.paperID, "version": "v2", "title": source.title,
            "keywords": [["label": "retrieval", "ref_ids": source.keywords[0].refIDs]], "features": []]))
        let decoded = try JSONDecoder().decode(KnowledgePaperV1.self, from: JSONEncoder().encode(paper))
        #expect(decoded.features.isEmpty)
        let ids = Set(decoded.keywords.flatMap(\.refIDs))
        #expect(graph.references.filter { ids.contains($0.id) }.first?.evidence.first?.quote == "Original source quote A.")
    }
}

private func sampleData() throws -> Data {
    try Data(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .deletingLastPathComponent().appending(path: "Fixtures/Protocol/topic-knowledge-graph-result.json"))
}
private func sample() throws -> TopicKnowledgeV1 {
    try #require(EngineProtocolCodec.decodeResult(sampleData()).knowledge)
}
