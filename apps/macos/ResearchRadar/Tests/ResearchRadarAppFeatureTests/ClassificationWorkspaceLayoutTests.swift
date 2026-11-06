import AppKit
import Foundation
import SwiftUI
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@Suite struct ClassificationWorkspaceLayoutTests {
    @Test func partitionsRetainOverlappingIdentityAndUnclassifiedPapers() throws {
        let value = try classificationLayoutFixture()
        let graph = try #require(value.graph)
        let groups = Array(graph.groups.prefix(3))
        let sections = KnowledgeClassificationLayout.sections(groups: groups, papers: graph.papers)
        #expect(sections.map { $0.papers.map(\.id) } == [
            [graph.papers[0].id, graph.papers[1].id],
            [graph.papers[1].id, graph.papers[2].id],
            [graph.papers[3].id, graph.papers[4].id], [graph.papers[5].id]])
        #expect(sections.last?.group == nil)
        #expect(sections[0].papers[1] == sections[1].papers[0])
        #expect(Set(sections.flatMap(\.papers).map(\.id)).count == 6)
        let filtered = KnowledgeClassificationLayout.sections(groups: groups, papers: [graph.papers[1]])
        #expect(filtered.count == 2 && filtered.allSatisfy { $0.papers.map(\.id) == [graph.papers[1].id] })
        #expect(KnowledgeClassificationLayout.sections(groups: groups, papers: []).isEmpty)
        #expect(KnowledgeClassificationLayout.sections(groups: [], papers: graph.papers).first?.papers == graph.papers)
    }
}

@MainActor @Suite struct ClassificationWorkspaceFixtureTests {
    @Test func repeatedPaperRetainsItsSectionWhenReturningFromEvidence() throws {
        let model = TopicKnowledgeModel(), value = try classificationLayoutFixture()
        let graph = try #require(value.graph)
        model.accept(value)
        let sectionID = "group:" + graph.groups[1].id
        model.setGraphScrollPosition(graph.papers[1].id, sectionID: sectionID, topicID: "memory")
        model.selectGraphPaper(graph.papers[1].id, topicID: "memory")
        model.selectGraphPaper(nil, topicID: "memory")
        model.accept(value)
        #expect(model.graphSelection(for: "memory").scrollPaperKey == graph.papers[1].id)
        #expect(model.graphSelection(for: "memory").scrollSectionID == sectionID)
        #expect(model.graphSelection(for: "other").scrollSectionID == nil)
    }

    @Test func clearingGraphFiltersKeepsFacetAndOtherTopicSelection() throws {
        let model = TopicKnowledgeModel(), value = try classificationLayoutFixture()
        model.accept(value)
        let graph = try #require(value.graph)
        model.selectFacet(graph.facets[1].id, topicID: "memory")
        model.selectGroup(graph.groups[3].id, topicID: "memory")
        model.toggleKeyword("Evaluation", topicID: "memory")
        model.setGraphQuery("no match", topicID: "memory")
        model.setGraphQuery("other filter", topicID: "other")
        #expect(model.visibleGraphPapers(for: "memory").isEmpty)
        model.clearGraphFilters(topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").count == 6)
        #expect(model.graphSelection(for: "memory").facetID == graph.facets[1].id)
        #expect(model.graphSelection(for: "other").query == "other filter")
    }

    @Test func historyKeepsActiveOrganizationControls() async throws {
        let root = try task3Root(); defer { task3Trash(root) }
        let id = UUID()
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "Offline layout",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese)]
        let payload = OrganizeTopicPayloadV1(topicID: "memory", reports: [.init(reportID: id, reportDate: "2026-10-29",
            runDirectory: root.appending(path: "workspace/runs/offline").path)], researchQuestion: "Offline", language: .chinese)
        let job = try JobRecordV1(kind: .organization, topicID: "memory", reportDate: "2026-10-29", trigger: .runNow,
            state: .running, jobDirectory: root.appending(path: "jobs/offline").path, createdAt: Date(), organization: payload)
        let store = AppStore(configuration: config, queueSnapshot: .init(jobs: [job]),
            runtime: .init(selectedTopicID: "memory", updatedAt: Date()), appSupportRoot: root, secretStore: LayoutNoSecrets())
        let ledger = PaperLedgerModel()
        let fixture = ledgerFixture(topic: "memory", report: id)
        await ledger.load(topicID: "memory", reports: []) { _, _ in fixture }
        ledger.select(fixture.papers[0].id)
        let view = PaperLedgerView(store: store, localization: LocalizationStore(preference: .english),
            presentation: WindowPresentationState(), model: ledger, open: { _, _, _ in })
        #expect(ledger.selectedPaper != nil)
        #expect(view.organizationControlsVisible)
    }

    @Test func captureClassificationLayoutsWhenRequested() async throws {
        guard let path = ProcessInfo.processInfo.environment["RESEARCH_RADAR_CLASSIFICATION_LAYOUT_IMAGES"],
              path.hasPrefix("/") else { return }
        _ = NSApplication.shared
        let output = URL(fileURLWithPath: path)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let root = try task3Root(); defer { task3Trash(root) }
        let value = try classificationLayoutFixture(), graph = try #require(value.graph)
        let id = try #require(value.current?.reportIDs.first)
        let report = ReportRecordV1(id: id, topicID: "memory", reportDate: "2026-10-29",
            runDirectory: root.appending(path: "workspace/runs/layout").path,
            articleDraftPath: root.appending(path: "workspace/runs/layout/article_draft.json").path,
            reportHTMLPath: root.appending(path: "workspace/runs/layout/wechat.html").path,
            title: "Offline layout", summary: "Synthetic layout only", sourceCount: 6,
            deepReadCount: 6, publishableClaimCount: 6, deliveries: [], createdAt: Date())
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [.init(id: "memory", displayName: "Memory research · 离线排版", researchFocus: "Offline layout only",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese)]
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: [report]),
            runtime: .init(windowMode: .full, selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: root, secretStore: LayoutNoSecrets())
        store.topicKnowledge.accept(value)
        let ledger = PaperLedgerModel()
        await ledger.load(topicID: "memory", reports: []) { _, _ in
            .init(topicID: "memory", reportIDs: [id], papers: graph.papers.map { paper in
                .init(paperID: paper.paperID, title: paper.title, occurrences: [
                    .init(occurrenceID: paper.id, reportID: id, reportDate: "2026-10-29", version: paper.version,
                        sourceURL: "https://example.org/layout", title: paper.title, paperIndex: 0)])
            })
        }
        for language in [AppLanguagePreference.simplifiedChinese, .english] {
            for dark in [false, true] {
                for width in [640.0, 720.0] {
                    let presentation = WindowPresentationState(); presentation.isVisible = false
                    let host = NSHostingView(rootView: PaperLedgerView(store: store,
                        localization: LocalizationStore(preference: language), presentation: presentation,
                        model: ledger, open: { _, _, _ in }))
                    host.sizingOptions = []
                    let window = NSWindow(contentRect: .init(x: 0, y: 0, width: width, height: 600),
                        styleMask: [.titled], backing: .buffered, defer: false)
                    window.isReleasedWhenClosed = false
                    window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                    window.contentView = host; window.orderBack(nil)
                    try await Task.sleep(for: .milliseconds(100)); host.layoutSubtreeIfNeeded()
                    let bitmap = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
                    host.cacheDisplay(in: host.bounds, to: bitmap)
                    let png = try #require(bitmap.representation(using: .png, properties: [:]))
                    try png.write(to: output.appending(path: "workspace-\(language.rawValue)-\(dark ? "dark" : "light")-\(Int(width)).png"), options: .atomic)
                    window.orderOut(nil); window.close()
                }
            }
        }
        #expect(store.jobs.isEmpty && !store.isEngineRunning)
    }

    @Test func exportLayoutFixtureWhenRequested() throws {
        guard let path = ProcessInfo.processInfo.environment["RESEARCH_RADAR_CLASSIFICATION_LAYOUT_FIXTURE"],
              path.hasPrefix("/") else { return }
        let result = EngineResultV1(requestID: UUID(), command: .readTopicKnowledge, status: .succeeded,
            completedAt: Date(timeIntervalSince1970: 0), knowledge: try classificationLayoutFixture())
        let url = URL(fileURLWithPath: path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try EngineProtocolCodec.encode(result).write(to: url, options: .atomic)
    }

    @Test func multipleFacetsKeepOverlapsAndUnclassifiedPaperAccessible() throws {
        let value = try classificationLayoutFixture()
        let model = TopicKnowledgeModel(); model.accept(value)
        let graph = try #require(value.graph)
        #expect(graph.papers.count == 6 && graph.facets.count == 2)
        #expect(model.visibleGraphGroups(for: "memory").count == 3)
        #expect(model.visibleGraphPapers(for: "memory").count == 6)
        #expect(model.unclassifiedPaperKeys(for: "memory") == [graph.papers[5].id])
        #expect(graph.groups.filter { $0.members.contains { $0.paperKey == graph.papers[1].id } }.count >= 2)
        model.selectGroup(graph.groups[1].id, topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").count == 2)
        model.selectFacet(graph.facets[1].id, topicID: "memory")
        #expect(model.graphSelection(for: "memory").groupID == nil)
        #expect(model.visibleGraphPapers(for: "memory").count == 6)
    }
}

private struct LayoutNoSecrets: SecretStoring {
    func contains(account: String) throws -> Bool { throw AppStoreError.invalidTopic }
    func read(account: String) throws -> Data? { throw AppStoreError.invalidTopic }
    func set(_ value: Data, account: String) throws { throw AppStoreError.invalidTopic }
    func remove(account: String) throws { throw AppStoreError.invalidTopic }
}

func classificationLayoutFixture() throws -> TopicKnowledgeV1 {
    let path = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .deletingLastPathComponent().appending(path: "Fixtures/Protocol/topic-knowledge-graph-result.json")
    var envelope = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: path)) as? [String: Any])
    var knowledge = try #require(envelope["knowledge"] as? [String: Any])
    var graph = try #require(knowledge["graph"] as? [String: Any])
    let templatePaper = try #require((graph["papers"] as? [[String: Any]])?.first)
    let templateRef = try #require((graph["references"] as? [[String: Any]])?.first)
    let titles = ["Intent-Aligned Memory Selection for Multi-Session Agents",
        "Memory Lifecycle: Retrieval, Consolidation, and Task Utility",
        "长期智能体记忆的更新与整理：区分写入、保留、遗忘和当前任务的适用条件",
        "Evaluating Memory Validity Under Changing Conditions and Conflicting Observations",
        "A Long English Paper Title for Checking Multi-Line Layout in Small Native Workspaces Without Losing Paper Identity",
        "尚未分类的论文：仅用于离线排版，不代表研究结论"]
    func key(_ i: Int) -> String { String(repeating: String(i, radix: 16), count: 64) }
    var papers: [[String: Any]] = [], references: [[String: Any]] = []
    for i in 0..<6 {
        var paper = templatePaper, ref = templateRef
        paper["paper_key"] = key(i + 1); paper["paper_id"] = key(i + 1)
        paper["title"] = titles[i]; paper["version"] = i == 1 ? "v2" : "v1"
        paper["keywords"] = [["label": i < 3 ? "Memory selection" : "Evaluation", "ref_ids": [key(i + 7)]]]
        paper["features"] = []
        ref["ref_id"] = key(i + 7); ref["paper_key"] = key(i + 1)
        ref["json_pointer"] = "/sections/0/metadata/deep_reads/\(i)/claims/0"
        ref["text"] = "Offline layout material, not a research conclusion."
        ref["evidence"] = [["source_url": "https://example.org/layout/paper-\(i)",
                            "quote": "Offline source excerpt for layout acceptance only.", "location": "Layout fixture"]]
        papers.append(paper); references.append(ref)
    }
    graph["papers"] = papers; graph["references"] = references
    graph["facets"] = [["id": "mechanism", "label": "Mechanism", "description": "离线排版：按机制查看；不代表真实分类。"],
                        ["id": "question", "label": "Research question", "description": "离线排版：同一论文可以属于多个组。"]]
    graph["groups"] = [("mechanism", "Selection", [0, 1]), ("mechanism", "Lifecycle", [1, 2]),
        ("mechanism", "Evaluation", [3, 4]), ("question", "Task utility", [0, 1, 2]),
        ("question", "Validity", [3, 4])].enumerated().map { offset, group in
            ["id": key(offset + 1), "facet_id": group.0, "label": group.1,
             "members": group.2.map { ["paper_key": key($0 + 1), "reason": "离线排版归属，不是模型研究判断。", "ref_ids": [key($0 + 7)]] }] as [String: Any]
        }
    var summary = try #require(knowledge["current"] as? [String: Any])
    summary["paper_count"] = 6; summary["feature_count"] = 0; summary["group_count"] = 5
    knowledge["current"] = summary; knowledge["graph"] = graph; envelope["knowledge"] = knowledge
    return try #require(EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: envelope)).knowledge)
}
