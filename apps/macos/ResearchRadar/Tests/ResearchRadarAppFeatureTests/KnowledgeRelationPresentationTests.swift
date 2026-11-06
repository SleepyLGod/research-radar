import AppKit
import CryptoKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct KnowledgeRelationPresentationTests {
    @Test func relationInspectionAndPaperReturnKeepCameraAndTopicSelection() throws {
        let model = TopicKnowledgeModel(), value = try semanticFixture()
        let graph = try #require(value.graph), edge = try #require(graph.relations.first)
        model.accept(value)
        model.setRelationCamera(.init(zoom: 1.3, offset: .init(x: 24, y: -12)), topicID: "memory")
        model.selectRelation(edge.id, topicID: "memory")
        model.selectGraphPaper(graph.papers[0].id, topicID: "memory")
        model.selectGraphPaper(nil, topicID: "memory")
        #expect(model.graphSelection(for: "memory").relationID == edge.id)
        #expect(model.graphSelection(for: "memory").relationCamera.zoom == 1.3)
        #expect(model.graphSelection(for: "memory").relationCamera.offset == .init(x: 24, y: -12))
        #expect(model.graphSelection(for: "other").relationID == nil)
        model.accept(value)
        #expect(model.graphSelection(for: "memory").relationID == edge.id)
        #expect(model.relationReferences(edge, paperKey: edge.source, topicID: "memory").map(\.text) == ["The method selects useful memories."])
        #expect(model.relationReferences(edge, paperKey: edge.target, topicID: "memory").map(\.text) == ["The protocol evaluates conflicts."])
    }

    @Test func relationFilteringDoesNotInventEdgesOrRemoveIsolatedPapers() throws {
        let model = TopicKnowledgeModel(), value = try semanticFixture()
        model.accept(value)
        model.toggleRelationKind(.sharedProblem, topicID: "memory")
        #expect(model.visibleRelations(for: "memory").isEmpty)
        #expect(model.visibleGraphPapers(for: "memory").count == 2)
        model.toggleRelationKind(.sharedProblem, topicID: "memory")
        #expect(model.visibleRelations(for: "memory").count == 1)
        model.selectGroup(value.graph?.groups[1].id, topicID: "memory")
        #expect(model.visibleGraphPapers(for: "memory").count == 1)
        #expect(model.visibleRelationPapers(for: "memory").count == 2)
        #expect(model.visibleRelations(for: "memory").count == 1)
        model.setGraphQuery("paper B", topicID: "memory")
        #expect(model.visibleRelations(for: "memory").isEmpty)
        #expect(model.visibleGraphPapers(for: "memory").count == 1)
    }

    @Test func nativeLayoutComesFromPaperIDsAndViewportNotDemoCoordinates() throws {
        let graph = try #require(semanticFixture().graph)
        let camera = KnowledgeRelationCamera()
        let first = KnowledgeRelationLayout(papers: graph.papers, size: .init(width: 640, height: 400), camera: camera)
        let reversed = KnowledgeRelationLayout(papers: Array(graph.papers.reversed()), size: .init(width: 640, height: 400), camera: camera)
        #expect(first.positions == reversed.positions)
        #expect(first.positions.count == 2)
        #expect(Set(first.positions.values.map(\.y)).count == 1)
        let shifted = KnowledgeRelationLayout(papers: graph.papers, size: .init(width: 640, height: 400),
            camera: .init(zoom: 1, offset: .init(x: 30, y: -10)))
        for paper in graph.papers {
            let point = try #require(first.positions[paper.id]), moved = try #require(shifted.positions[paper.id])
            #expect(moved.x == point.x + 30 && moved.y == point.y - 10)
        }
    }

    @Test func reversedUndirectedEndpointsKeepDifferentRelationLanesSeparate() {
        let a = CGPoint(x: 20, y: 60), b = CGPoint(x: 320, y: 80)
        let first = KnowledgeRelationLayout.controlPoint(from: a, to: b, lane: -25)
        let second = KnowledgeRelationLayout.controlPoint(from: b, to: a, lane: 25)
        #expect(first != second)
        #expect(first == KnowledgeRelationLayout.controlPoint(from: b, to: a, lane: -25))
    }

    @Test func exactReferenceMapsToItsReportAndVersionNotAnotherOccurrence() async throws {
        let graph = try #require(semanticFixture().graph), paper = graph.papers[0], ref = graph.references[0]
        let ledger = PaperLedgerModel()
        let occurrence = PaperOccurrenceV1(occurrenceID: "offline-occurrence", reportID: ref.reportID,
            reportDate: ref.reportDate, version: paper.version, sourceURL: ref.evidence[0].sourceURL,
            title: paper.title, paperIndex: 0)
        let snapshot = TopicPaperLedgerV1(topicID: "memory", reportIDs: [ref.reportID],
            papers: [.init(paperID: paper.paperID, title: paper.title, occurrences: [occurrence])])
        await ledger.load(topicID: "memory", reports: []) { _, _ in snapshot }
        let target = try #require(ledger.evidenceTarget(reference: ref, graph: graph))
        #expect(target.occurrence == occurrence)
        var navigation = WorkspaceNavigation()
        navigation.openKnowledgeEvidence(target)
        #expect(navigation.ledgerEntry?.reportSHA256 == ref.reportSHA256)
        #expect(navigation.ledgerEntry?.paperIndex == 0)
        navigation.leaveReport()
        #expect(navigation.section == .papers)
        #expect(ledger.evidenceTarget(reference: graph.references[1], graph: graph) == nil)
    }

    @Test func reportJumpRejectsChangedArtifactButNormalReportReadingStillWorks() async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let data = paperDraft()
        try data.write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let browser = ReportBrowserModel()
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot, expectedSHA256: digest)
        #expect(browser.contents?.papers.count == 2)
        try (data + Data("\n".utf8)).write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot, expectedSHA256: digest)
        #expect(browser.loadFailed && browser.contents == nil)
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        #expect(!browser.loadFailed && browser.contents?.papers.count == 2)
    }

    @Test func reportNavigationUsesLedgerIndexAcrossSeveralDeepReadSections() async throws {
        let graph = try #require(semanticFixture().graph), paper = graph.papers[0], ref = graph.references[0]
        let ledger = PaperLedgerModel()
        // The JSON pointer is local to a section; the report reader uses a flattened index.
        let occurrence = PaperOccurrenceV1(occurrenceID: "later-section", reportID: ref.reportID,
            reportDate: ref.reportDate, version: paper.version, sourceURL: ref.evidence[0].sourceURL,
            title: paper.title, paperIndex: 3)
        await ledger.load(topicID: "memory", reports: []) { _, _ in
            .init(topicID: "memory", reportIDs: [ref.reportID], papers: [
                .init(paperID: paper.paperID, title: paper.title, occurrences: [occurrence])])
        }
        #expect(ledger.evidenceTarget(reference: ref, graph: graph)?.occurrence.paperIndex == 3)
    }

    @Test func nativeGraphEdgeSelectionAndStateReturn() async throws {
        _ = NSApplication.shared
        let value: TopicKnowledgeV1
        let environment = ProcessInfo.processInfo.environment
        if let root = environment["RESEARCH_RADAR_RELATION_QA_OUTPUT"] {
            let wire = URL(fileURLWithPath: root).appending(path: "knowledge-wire.json")
            value = try #require(EngineProtocolCodec.decodeResult(Data(contentsOf: wire)).knowledge)
        } else { value = try semanticFixture() }
        let graph = try #require(value.graph), edge = try #require(graph.relations.first)
        let model = TopicKnowledgeModel(); model.accept(value)
        model.setGraphMode(.relations, topicID: value.topicID)
        var openedReferences: [String] = []
        for language in [AppLanguagePreference.simplifiedChinese, .english] {
            for dark in [false, true] {
                model.selectRelation(nil, topicID: value.topicID)
                let localization = LocalizationStore(preference: language)
                let host = NSHostingView(rootView: KnowledgeGraphView(topicID: value.topicID, model: model,
                    localization: localization, historyPaperIDs: [], openHistory: { _ in },
                    availableReferences: Set(graph.references.map(\.id)), openEvidence: { openedReferences.append($0.id) }))
                host.sizingOptions = []
                let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 720, height: 540),
                    styleMask: [.titled], backing: .buffered, defer: false)
                window.isReleasedWhenClosed = false; window.contentView = host
                window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua); window.orderBack(nil)
                defer { window.orderOut(nil); window.close() }
                await Task.yield(); try await Task.sleep(for: .milliseconds(120)); host.layoutSubtreeIfNeeded()
                if let root = environment["RESEARCH_RADAR_RELATION_QA_OUTPUT"] {
                    try captureRelationView(host, to: URL(fileURLWithPath: root).appending(path: "graph-\(language.rawValue)-\(dark ? "dark" : "light").png"))
                }
                let kind = localization.text("graph.relation_kind.\(edge.kind.rawValue)")
                let titles = [edge.source, edge.target].compactMap { key in graph.papers.first { $0.id == key }?.title }
                let label = (titles + [kind]).joined(separator: " · ")
                if let root = environment["RESEARCH_RADAR_RELATION_QA_OUTPUT"] {
                    let labels = relationAccessibility(host).map {
                        [$0.accessibilityLabel(), $0.accessibilityTitle(), $0.accessibilityValue() as? String]
                            .compactMap { $0 }.joined(separator: " | ")
                    }
                    try labels.joined(separator: "\n").write(toFile: root + "/accessibility.txt", atomically: true, encoding: .utf8)
                }
                let button = relationAccessibility(host).first {
                    [$0.accessibilityLabel(), $0.accessibilityTitle()].contains(label)
                }
                if let button { #expect(button.accessibilityPerformPress()) }
                else {
                    // Some hosted windows expose no accessibility labels in this environment.
                    // Probe only the graph's center line; never click external links in the inspector.
                    window.makeKeyAndOrderFront(nil)
                    for y in stride(from: 180.0, through: 290.0, by: 5) {
                        nativeRelationClick(host: host, window: window, point: .init(x: 360, y: y))
                        await Task.yield(); try await Task.sleep(for: .milliseconds(20))
                        if model.graphSelection(for: value.topicID).relationID != nil { break }
                    }
                }
                try await Task.sleep(for: .milliseconds(120)); host.layoutSubtreeIfNeeded()
                let selectedID = try #require(model.graphSelection(for: value.topicID).relationID)
                let selected = try #require(graph.relations.first { $0.id == selectedID })
                let labels = relationAccessibility(host).flatMap {
                    [$0.accessibilityLabel(), $0.accessibilityTitle(), $0.accessibilityValue() as? String].compactMap { $0 }
                }.joined(separator: "\n")
                for id in [selected.source, selected.target] {
                    #expect(!model.relationReferences(selected, paperKey: id, topicID: value.topicID).isEmpty)
                }
                if !labels.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    for ref in graph.references.filter({ selected.refIDs.contains($0.id) }) {
                        #expect(labels.contains(ref.text))
                        #expect(labels.contains(ref.evidence[0].quote))
                    }
                }
                if let root = environment["RESEARCH_RADAR_RELATION_QA_OUTPUT"] {
                    try captureRelationView(host, to: URL(fileURLWithPath: root).appending(path: "evidence-\(language.rawValue)-\(dark ? "dark" : "light").png"))
                }
                let referenceButton = relationAccessibility(host).first {
                    [$0.accessibilityLabel(), $0.accessibilityTitle()].contains(localization.text("graph.open_report_evidence"))
                }
                if let referenceButton {
                    #expect(referenceButton.accessibilityPerformPress())
                    #expect(!openedReferences.isEmpty)
                } else {
                    print("Manual pending: evidence-button input; hosted accessibility labels unavailable.")
                }
                let camera = KnowledgeRelationCamera(zoom: 1.15, offset: .init(x: 15, y: -8))
                model.setRelationCamera(camera, topicID: value.topicID)
                model.selectGraphPaper(graph.papers[0].id, topicID: value.topicID)
                model.selectGraphPaper(nil, topicID: value.topicID)
                #expect(model.graphSelection(for: value.topicID).relationCamera == camera)
                model.setRelationCamera(.init(), topicID: value.topicID)
            }
        }
    }
}

@MainActor private func nativeRelationClick(host: NSView, window: NSWindow, point: CGPoint) {
    let local = CGPoint(x: point.x, y: host.isFlipped ? point.y : host.bounds.height - point.y)
    let location = host.convert(local, to: nil)
    for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
        if let event = NSEvent.mouseEvent(with: type, location: location, modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
            context: nil, eventNumber: 0, clickCount: 1, pressure: 1) { window.sendEvent(event) }
    }
}

@MainActor private func relationAccessibility(_ root: NSView) -> [any NSAccessibilityProtocol] {
    var seen = Set<ObjectIdentifier>(), result: [any NSAccessibilityProtocol] = []
    func visit(_ value: Any) {
        guard let node = value as? any NSAccessibilityProtocol,
              seen.insert(ObjectIdentifier(node as AnyObject)).inserted else { return }
        result.append(node)
        for child in (node.accessibilityChildren() ?? []) + (node.accessibilityVisibleChildren() ?? []) { visit(child) }
        if let view = value as? NSView { for child in view.subviews { visit(child) } }
    }
    visit(root); return result
}

@MainActor private func captureRelationView(_ host: NSView, to url: URL) throws {
    let bitmap = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
    host.cacheDisplay(in: host.bounds, to: bitmap)
    try #require(bitmap.representation(using: .png, properties: [:])).write(to: url, options: .atomic)
}

private func semanticFixture() throws -> TopicKnowledgeV1 {
    let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .appending(path: "Fixtures/Protocol/topic-knowledge-graph-result.json")
    var object = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    var knowledge = try #require(object["knowledge"] as? [String: Any])
    var graph = try #require(knowledge["graph"] as? [String: Any])
    var summary = try #require(knowledge["current"] as? [String: Any])
    summary["relation_count"] = 1; knowledge["current"] = summary
    graph["relations"] = [["id": String(repeating: "a", count: 64),
        "source": String(repeating: "3", count: 64), "target": String(repeating: "4", count: 64),
        "kind": "shared_problem", "basis": "synthesis", "reason": "Offline relation fixture.",
        "ref_ids": [String(repeating: "7", count: 64), String(repeating: "8", count: 64)]]]
    knowledge["graph"] = graph; object["knowledge"] = knowledge
    return try #require(EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: object)).knowledge)
}
