import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@MainActor @Suite struct KnowledgeCoveragePresentationTests {
    @Test func scopeInvalidationKeepsTheGraphAndCamera() throws {
        let model = TopicKnowledgeModel(), saved = try classificationLayoutFixture()
        model.accept(.init(topicID: saved.topicID, current: saved.current, graph: saved.graph,
            coverage: .init(status: .current, papers: [])))
        model.setRelationCamera(.init(zoom: 1.5, offset: .init(x: 24, y: -12)), topicID: saved.topicID)
        let camera = model.graphSelection(for: saved.topicID).relationCamera
        model.invalidateCoverage(topicID: saved.topicID)
        #expect(model.coverage(for: saved.topicID) == nil)
        #expect(model.graph(for: saved.topicID) == saved.graph)
        #expect(model.graphSelection(for: saved.topicID).relationCamera == camera)
    }

    @Test func coverageSurvivesNavigationButIsUnknownAfterFailedRead() async throws {
        let model = TopicKnowledgeModel()
        let row = KnowledgeCoverageV1.Paper(paperKey: String(repeating: "a", count: 64),
            paperID: String(repeating: "b", count: 64), version: "v2", title: "Memory selection",
            status: .newVersion, reportIDs: [UUID()])
        let value = TopicKnowledgeV1(topicID: "memory", current: nil,
            coverage: .init(status: .unorganized, papers: [.init(paperKey: row.paperKey,
                paperID: row.paperID, version: row.version, title: row.title,
                status: .newPaper, reportIDs: row.reportIDs)]))
        model.accept(value)
        #expect(model.coverage(for: "memory")?.status == .unorganized)
        #expect(model.paperCoverage(topicID: "memory", paperID: row.paperID, version: "v2")?.status == .newPaper)
        #expect(model.paperCoverage(topicID: "memory", paperID: row.paperID, version: "v1") == nil)
        #expect(model.coverage(for: "other") == nil)
        await model.load(topicID: "memory") { _ in throw EngineProtocolError.invalidJSON }
        #expect(model.coverage(for: "memory")?.status == .unknown)
        #expect(model.paperCoverage(topicID: "memory", paperID: row.paperID, version: "v2") == nil)
        model.accept(value)
        #expect(model.coverage(for: "memory")?.status == .unorganized)
    }
}
