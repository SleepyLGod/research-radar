import AppKit
import CryptoKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct KnowledgeEvidenceNavigationTests {
    @Test(arguments: [0, 1])
    func exactClaimSurvivesPaperLocalPointerAndNavigationReset(claim: Int) async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let report = fixture.report
        let claims: [[String: Any]] = (0..<2).map { index in
            ["text": "Saved claim \(index)", "evidence": [["source_url": "https://example.org/paper",
                "quote": "Original quote \(index)", "location": "Page \(index + 1)"]]]
        }
        let data = paperDraft(overrides: ["claims": claims])
        try data.write(to: URL(fileURLWithPath: report.articleDraftPath))
        let browser = ReportBrowserModel()
        await browser.load(report: report, workspaceRoot: fixture.workspaceRoot)
        let reference = try evidenceReference(report: report, data: data, claim: claim)
        let occurrence = PaperOccurrenceV1(occurrenceID: "original", reportID: report.id,
            reportDate: report.reportDate, version: "v2", sourceURL: "https://example.org/paper",
            title: "第一篇 Paper A", paperIndex: 0)
        var navigation = WorkspaceNavigation()
        navigation.openKnowledgeEvidence(.init(occurrence: occurrence, reference: reference))
        browser.openLedgerEntry(try #require(navigation.ledgerEntry))
        #expect(browser.initialEvidenceAnchor == .claim(claim))
        browser.finishInitialEvidenceNavigation()
        #expect(browser.initialEvidenceTarget == nil && browser.initialEvidenceClaimIndex == nil)
        browser.openLedgerEntry(try #require(navigation.ledgerEntry))
        browser.openPaper(1)
        #expect(browser.initialEvidenceTarget == nil && browser.initialEvidenceClaimIndex == nil)
        browser.back()
        #expect(browser.page == .overview)
        browser.openLedgerEntry(.init(reportID: report.id, paperIndex: 0,
            sourceURL: occurrence.sourceURL, evidence: true))
        #expect(browser.initialEvidenceAnchor == .evidence)
    }

    @Test(arguments: [-1, 1, Int.max])
    func invalidClaimDoesNotFallBackToTheWrongEvidence(index: Int) async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let report = fixture.report
        try paperDraft().write(to: URL(fileURLWithPath: report.articleDraftPath))
        let browser = ReportBrowserModel()
        await browser.load(report: report, workspaceRoot: fixture.workspaceRoot)
        browser.openLedgerEntry(.init(reportID: report.id, paperIndex: 0,
            sourceURL: "https://example.org/paper", evidence: true, evidenceClaimIndex: index))
        #expect(browser.page == .overview && browser.initialEvidenceTarget == nil)
    }

    @Test(arguments: [false, true], [false, true])
    func lateReferenceLandsOnItsClaimNotTheEvidenceSection(preloaded: Bool, withFigure: Bool) async throws {
        _ = NSApplication.shared
        let root = try task3Root(), fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        let report = fixture.report
        let claims = (0..<36).map { index in
            ["text": "Saved claim \(index)", "evidence": [["source_url": "https://example.org/paper",
                "quote": "Original quote \(index)", "location": "Page \(index + 1)"]]] as [String: Any]
        }
        let data = paperDraft(overrides: ["claims": claims,
            "reader_explanation": ["problem_walkthrough": String(repeating: "Saved explanation. 已有正文。\n\n", count: 60)],
            "figures": withFigure ? [["relative_path": "figures/pixel.png", "caption": "Existing offline figure"]] : []])
        try data.write(to: URL(fileURLWithPath: report.articleDraftPath))
        let reference = try evidenceReference(report: report, data: data, claim: 35)
        let occurrence = PaperOccurrenceV1(occurrenceID: "saved-occurrence", reportID: report.id,
            reportDate: report.reportDate, version: "v2", sourceURL: "https://example.org/paper",
            title: "第一篇 Paper A", paperIndex: 0)
        var navigation = WorkspaceNavigation()
        navigation.openKnowledgeEvidence(.init(occurrence: occurrence, reference: reference))
        let entry = try #require(navigation.ledgerEntry)
        let store = AppStore(configuration: AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot,
            codexExecutable: nil), runtime: .init(windowMode: .full, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let browser = ReportBrowserModel()
        if preloaded { await browser.load(report: report, workspaceRoot: fixture.workspaceRoot) }
        let host = NSHostingView(rootView: ReportBrowserView(store: store, report: report,
            localization: LocalizationStore(preference: .simplifiedChinese), presentation: WindowPresentationState(),
            back: {}, configure: {}, browser: browser, ledgerEntry: entry))
        host.sizingOptions = []
        let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 620, height: 520),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        var reachedTarget = false
        for _ in 0..<100 {
            await Task.yield(); host.layoutSubtreeIfNeeded()
            if let scroll = reportViewDescendants(host).compactMap({ $0 as? NSScrollView }).first,
               let document = scroll.documentView {
                let visibleBottom = scroll.contentView.bounds.maxY
                reachedTarget = document.bounds.height > 1000 && abs(visibleBottom - document.bounds.height) <= 1
                if reachedTarget { break }
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        // The last claim is several viewports below the section header: moving is not enough.
        #expect(browser.selectedPaper?.id == 0)
        #expect(reachedTarget)
        #expect(browser.initialEvidenceTarget == nil)
        #expect(try Data(contentsOf: URL(fileURLWithPath: report.articleDraftPath)) == data)
    }
}

private func evidenceReference(report: ReportRecordV1, data: Data, claim: Int) throws -> KnowledgeReferenceV1 {
    let value: [String: Any] = [
        "ref_id": String(repeating: "a", count: 64), "paper_key": String(repeating: "b", count: 64),
        "report_id": report.id.uuidString.lowercased(), "report_date": report.reportDate,
        "report_sha256": SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
        "json_pointer": "/sections/0/metadata/deep_reads/0/claims/\(claim)", "text": "Saved claim \(claim)",
        "evidence": [["source_url": "https://example.org/paper", "quote": "Original quote \(claim)", "location": "Page \(claim + 1)"]]
    ]
    return try JSONDecoder().decode(KnowledgeReferenceV1.self, from: JSONSerialization.data(withJSONObject: value))
}
