import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct PaperLedgerTests {
    @Test(arguments: [(false, false), (false, true), (true, false), (true, true)],
        [AppLanguagePreference.english, .simplifiedChinese])
    func evidenceEntryScrollsToTheExistingEvidenceSection(
        setup: (Bool, Bool), language: AppLanguagePreference
    ) async throws {
        let (preloaded, withFigure) = setup
        _ = NSApplication.shared
        let root = try task3Root(), fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        let report = fixture.report
        let caption = "Loaded offline figure / 离线图片"
        let data = paperDraft(overrides: ["reader_explanation": ["problem_walkthrough":
            String(repeating: "Existing public explanation. 已有公开正文。\n\n", count: 80)],
            "figures": withFigure ? [["relative_path": "figures/pixel.png", "caption": caption]] : []])
        try data.write(to: URL(fileURLWithPath: report.articleDraftPath))
        let store = AppStore(configuration: AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot,
            codexExecutable: nil), runtime: .init(windowMode: .full, updatedAt: Date()),
            appSupportRoot: root, secretStore: LedgerNoSecrets())
        let browser = ReportBrowserModel()
        let entry = PaperLedgerEntry(reportID: report.id, paperIndex: 0,
            sourceURL: "https://example.org/paper", evidence: true)
        if preloaded { await browser.load(report: report, workspaceRoot: fixture.workspaceRoot) }
        let host = NSHostingView(rootView: ReportBrowserView(store: store, report: report,
            localization: LocalizationStore(preference: language), presentation: WindowPresentationState(),
            back: {}, configure: {}, browser: browser, ledgerEntry: entry))
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 620, height: 520),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        var offset: CGFloat = 0
        for _ in 0..<100 {
            await Task.yield(); host.layoutSubtreeIfNeeded()
            offset = reportViewDescendants(host).compactMap { $0 as? NSScrollView }
                .map { $0.contentView.bounds.origin.y }.max() ?? 0
            if offset > 0 && (!withFigure || ledgerAccessibilityContains(host, text: caption)) { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(browser.contents != nil)
        #expect(browser.selectedPaper?.id == 0)
        #expect(offset > 0)
        if withFigure { #expect(ledgerAccessibilityContains(host, text: caption)) }
        let scroll = try #require(reportViewDescendants(host).compactMap { $0 as? NSScrollView }.first)
        let document = try #require(scroll.documentView)
        // This fixture ends in a short evidence section; the viewport must reach it, not just move.
        #expect(abs(offset + scroll.contentView.bounds.height - document.bounds.height) <= 1)
        #expect(browser.initialEvidenceTarget == nil)

        let wheel = try #require(CGEvent(scrollWheelEvent2Source: nil, units: .pixel,
            wheelCount: 1, wheel1: 10000, wheel2: 0, wheel3: 0))
        scroll.scrollWheel(with: try #require(NSEvent(cgEvent: wheel)))
        for _ in 0..<50 {
            await Task.yield(); host.layoutSubtreeIfNeeded()
            if scroll.contentView.bounds.origin.y == 0 { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(scroll.contentView.bounds.origin.y == 0)
        window.setContentSize(NSSize(width: 540, height: 520))
        for _ in 0..<20 {
            await Task.yield(); host.layoutSubtreeIfNeeded()
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(scroll.contentView.bounds.origin.y == 0)
        browser.openPaper(1)
        for _ in 0..<50 {
            await Task.yield(); host.layoutSubtreeIfNeeded()
            if reportViewDescendants(host).compactMap({ $0 as? NSScrollView }).first !== scroll { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        let switched = try #require(reportViewDescendants(host).compactMap { $0 as? NSScrollView }.first)
        #expect(switched !== scroll)
        #expect(switched.contentView.bounds.origin.y == 0)
        #expect(browser.selectedPaper?.id == 1)
        #expect(try Data(contentsOf: URL(fileURLWithPath: report.articleDraftPath)) == data)
        #expect(try Data(contentsOf: fixture.root.appending(path: "wechat.html")) == Data(fixture.html.utf8))
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["RESEARCH_RADAR_LEDGER_ENGINE"] != nil))
    func frozenEngineBuildsTwoReportLedgerAndOriginalEvidenceSurvivesRestart() async throws {
        let engine = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["RESEARCH_RADAR_LEDGER_ENGINE"]))
        let root = try task3Root()
        defer { task3Trash(root) }
        let workspace = root.appending(path: "workspace")
        let fixtureURL = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appending(path: "Fixtures/Protocol/paper-ledger-result.json")
        let canonical = try EngineProtocolCodec.decodeResult(Data(contentsOf: fixtureURL))
        let expected = try #require(canonical.paperLedger)
        var reports: [ReportRecordV1] = []
        for index in 0..<2 {
            let id = expected.reportIDs[index]
            let date = "2026-10-\(26 + index)", version = "v\(index + 1)"
            let run = workspace.appending(path: "runs/\(id.uuidString.lowercased())")
            try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
            let source: [String: Any] = ["title": "Memory evidence", "url": "https://arxiv.org/abs/2601.01234\(version)",
                "version": version, "source_type": "paper"]
            let entry: [String: Any] = ["title": "Memory evidence", "source": source,
                "claims": [["text": "已核验的公开结论", "evidence": [["quote": "Existing evidence", "location": "p. 2",
                    "source_url": source["url"]!]]]]]
            let section: [String: Any] = index == 0
                ? ["metadata": ["kind": "deep_reads", "deep_reads": [entry]]]
                : ["metadata": ["kind": "new_updated_sources", "sources": [source]]]
            try JSONSerialization.data(withJSONObject: ["topic_id": "memory", "sections": [section]])
                .write(to: run.appending(path: "article_draft.json"))
            try Data("<meta charset=\"utf-8\"><p>中文离线报告</p>".utf8).write(to: run.appending(path: "wechat.html"))
            reports.append(.init(id: id, topicID: "memory", reportDate: date, runDirectory: run.path,
                articleDraftPath: run.appending(path: "article_draft.json").path,
                reportHTMLPath: run.appending(path: "wechat.html").path, title: "Offline report", summary: "",
                sourceCount: 1, deepReadCount: index == 0 ? 1 : 0, publishableClaimCount: index == 0 ? 1 : 0,
                deliveries: [], createdAt: Date()))
        }
        var config = AppConfigurationDefaults.make(workspaceRoot: workspace, codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        config.topics = [.init(id: "memory", displayName: "Agent memory", researchFocus: "Offline ledger",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese)]
        let persistence = AtomicJSONStore(root: root)
        let runtime = AppRuntimeStateV1(selectedTopicID: "memory", updatedAt: Date())
        try persistence.write(config, to: "config/app-config.json")
        try persistence.write(runtime, to: "state/app-state.json")
        try persistence.write(ReportIndexV1(reports: reports), to: "state/report-index.json")
        let before = try reports.map { (try Data(contentsOf: URL(fileURLWithPath: $0.articleDraftPath)),
                                       try Data(contentsOf: URL(fileURLWithPath: $0.reportHTMLPath))) }
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: reports), runtime: runtime,
            appSupportRoot: root, engineURL: engine, secretStore: LedgerNoSecrets())
        let references = reports.map { LedgerReportReferenceV1(reportID: $0.id, reportDate: $0.reportDate, runDirectory: $0.runDirectory) }
        #expect(try await store.readPaperLedger(topicID: "memory", reports: references) == expected)
        let restarted = try AppBootstrapService(appSupportRoot: root).load(engineURL: engine, pdfHelperURL: nil)
        #expect(try await restarted.readPaperLedger(topicID: "memory", reports: references) == expected)
        let browser = ReportBrowserModel()
        let occurrence = expected.papers[0].occurrences[1]
        await browser.load(report: reports[0], workspaceRoot: workspace)
        browser.openLedgerEntry(.init(reportID: occurrence.reportID, paperIndex: occurrence.paperIndex,
            sourceURL: occurrence.sourceURL, evidence: true))
        #expect(browser.selectedPaper?.claims.first?.evidence.first?.quote == "Existing evidence")
        for (index, report) in reports.enumerated() {
            #expect(try Data(contentsOf: URL(fileURLWithPath: report.articleDraftPath)) == before[index].0)
            #expect(try Data(contentsOf: URL(fileURLWithPath: report.reportHTMLPath)) == before[index].1)
        }
        #expect(store.jobs.isEmpty && restarted.jobs.isEmpty)
        await store.shutdown(); await restarted.shutdown()
    }
    @Test func filtersAndSelectionsAreTopicScopedAndCacheUsesReportReferences() async throws {
        let model = PaperLedgerModel()
        let report = UUID()
        let reference = LedgerReportReferenceV1(reportID: report, reportDate: "2026-10-27", runDirectory: "/offline")
        let first = ledgerFixture(topic: "memory", report: report)
        var calls = 0
        await model.load(topicID: "memory", reports: [reference]) { _, _ in calls += 1; return first }
        #expect(model.papers.count == 2)
        model.select(first.papers[0].id); model.setQuery("Memory")
        model.setFilter(.publicReading)
        #expect(model.papers.count == 1 && model.selectedPaper?.hasPublicReading == true)
        await model.load(topicID: "memory", reports: [reference]) { _, _ in calls += 1; return first }
        #expect(calls == 1)
        await model.load(topicID: "inference", reports: []) { _, _ in ledgerFixture(topic: "inference", report: report) }
        #expect(model.query.isEmpty && model.selectedPaper == nil)
        await model.load(topicID: "memory", reports: [reference]) { _, _ in calls += 1; return first }
        #expect(model.selectedPaper?.id == first.papers[0].id && model.query == "Memory")
        #expect(calls == 1)
        await model.load(topicID: "memory", reports: [reference], force: true) { _, _ in throw AppStoreError.busy }
        #expect(model.papers.count == 1 && model.errorKey == "ledger.busy")
    }

    @Test func newerTopicResponseCannotBeReplacedByOlderRequest() async {
        let model = PaperLedgerModel()
        var continuation: CheckedContinuation<TopicPaperLedgerV1, Never>?
        let first = Task { await model.load(topicID: "a", reports: []) { _, _ in
            await withCheckedContinuation { continuation = $0 }
        } }
        while continuation == nil { await Task.yield() }
        await model.load(topicID: "b", reports: []) { _, _ in ledgerFixture(topic: "b", report: UUID()) }
        continuation?.resume(returning: ledgerFixture(topic: "a", report: UUID()))
        await first.value
        #expect(model.topicID == "b" && model.snapshot?.topicID == "b")
        var rebuilds = 0
        await model.load(topicID: "a", reports: []) { _, _ in rebuilds += 1; return ledgerFixture(topic: "a", report: UUID()) }
        #expect(rebuilds == 0 && model.snapshot?.topicID == "a")
    }

    @Test func leavingAViewStillCachesItsSuccessfullyCompletedRead() async {
        let model = PaperLedgerModel()
        var continuation: CheckedContinuation<TopicPaperLedgerV1, Never>?
        let pending = Task { await model.load(topicID: "memory", reports: []) { _, _ in
            await withCheckedContinuation { continuation = $0 }
        } }
        while continuation == nil { await Task.yield() }
        pending.cancel()
        var duplicateReads = 0
        await model.load(topicID: "memory", reports: []) { _, _ in
            duplicateReads += 1; return ledgerFixture(topic: "memory", report: UUID())
        }
        #expect(model.loading && duplicateReads == 0)
        continuation?.resume(returning: ledgerFixture(topic: "memory", report: UUID()))
        await pending.value
        var calls = 0
        await model.load(topicID: "memory", reports: []) { _, _ in calls += 1; return ledgerFixture(topic: "memory", report: UUID()) }
        #expect(calls == 0 && model.snapshot != nil)
    }

    @Test func cachedReentryDoesNotDiscardAnActiveForcedRefresh() async {
        let model = PaperLedgerModel(), report = UUID()
        await model.load(topicID: "memory", reports: []) { _, _ in
            .init(topicID: "memory", reportIDs: [report], papers: [], unavailableReports: [report])
        }
        var continuation: CheckedContinuation<TopicPaperLedgerV1, Never>?
        let refresh = Task { await model.load(topicID: "memory", reports: [], force: true) { _, _ in
            await withCheckedContinuation { continuation = $0 }
        } }
        while continuation == nil { await Task.yield() }
        refresh.cancel()
        await model.load(topicID: "memory", reports: []) { _, _ in
            Issue.record("A matching active refresh must be reused")
            return ledgerFixture(topic: "memory", report: report)
        }
        continuation?.resume(returning: ledgerFixture(topic: "memory", report: report))
        await refresh.value
        #expect(model.snapshot?.unavailableReports.isEmpty == true)
        #expect(model.papers.count == 2 && !model.loading)
    }

    @Test func ledgerNavigationReturnsToLedgerAndNormalReportsKeepTheirRoute() {
        let occurrence = ledgerFixture(topic: "memory", report: UUID()).papers[0].occurrences[0]
        var navigation = WorkspaceNavigation()
        navigation.openOccurrence(occurrence, evidence: true)
        #expect(navigation.isReading && navigation.ledgerEntry?.evidence == true)
        navigation.leaveReport()
        #expect(navigation.section == .papers && !navigation.isReading)
        navigation.openReport(UUID()); navigation.leaveReport()
        #expect(navigation.section == .reports && !navigation.isReading)
    }

    @Test(arguments: ["https://example.org/paper", "https://example.org/café.pdf",
        "https://example.org/paper one.pdf", "https://example.org/中文.pdf"])
    func occurrenceOpensOnlyItsOriginalPaperAndEvidence(sourceURL: String) async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        try paperDraft(link: sourceURL).write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        let browser = ReportBrowserModel()
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        let paper = try #require(browser.contents?.papers.first)
        let entry = PaperLedgerEntry(reportID: fixture.report.id, paperIndex: paper.id,
            sourceURL: sourceURL, evidence: true)
        browser.openLedgerEntry(entry)
        #expect(browser.selectedPaper?.id == paper.id)
        #expect(browser.initialEvidenceTarget == paper.id)
        browser.back()
        browser.openLedgerEntry(.init(reportID: fixture.report.id, paperIndex: paper.id,
            sourceURL: "https://example.org/different-paper", evidence: true))
        #expect(browser.page == .overview && browser.initialEvidenceTarget == nil)
    }
}

@MainActor private func ledgerAccessibilityContains(_ root: NSView, text: String) -> Bool {
    var visited = Set<ObjectIdentifier>()
    func contains(_ value: Any) -> Bool {
        guard let node = value as? any NSAccessibilityProtocol,
              visited.insert(ObjectIdentifier(node as AnyObject)).inserted else { return false }
        if [node.accessibilityLabel(), node.accessibilityTitle(), node.accessibilityValue() as? String].contains(text) {
            return true
        }
        let children = (node.accessibilityChildren() ?? []) + (node.accessibilityVisibleChildren() ?? [])
        return children.contains(where: contains)
            || (value as? NSView)?.subviews.contains(where: contains) == true
    }
    return contains(root)
}

private struct LedgerNoSecrets: SecretStoring {
    func set(_ value: Data, account: String) throws { throw AppStoreError.confirmationRequired }
    func read(account: String) throws -> Data? { throw AppStoreError.confirmationRequired }
    func contains(account: String) throws -> Bool { false }
    func remove(account: String) throws { throw AppStoreError.confirmationRequired }
}

func ledgerFixture(topic: String, report: UUID) -> TopicPaperLedgerV1 {
    .init(topicID: topic, reportIDs: [report], papers: [
        .init(paperID: String(repeating: "a", count: 64), title: "Memory evidence / 记忆评估", occurrences: [
            .init(occurrenceID: String(repeating: "c", count: 64), reportID: report,
                reportDate: "2026-10-27", version: "v1", sourceURL: "https://arxiv.org/abs/2601.01234v1",
                title: "Memory evidence / 记忆评估", paperIndex: 0)]),
        .init(paperID: String(repeating: "b", count: 64), title: "Source only", occurrences: [
            .init(occurrenceID: String(repeating: "d", count: 64), reportID: report,
                reportDate: "2026-10-27", version: "v2", sourceURL: "https://arxiv.org/abs/2602.01234v2",
                title: "Source only", paperIndex: nil)])])
}
