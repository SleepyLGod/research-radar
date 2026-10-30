import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor struct PaperEvidenceDisclosureTests {
    @Test(arguments: [AppLanguagePreference.english, .simplifiedChinese])
    func claimsStartCollapsedAndRemainAvailableWithoutChangingTheReport(language: AppLanguagePreference) async throws {
        _ = NSApplication.shared
        let root = try task3Root(), fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        let claims = (0..<36).map { index in
            ["text": "Saved claim \(index)", "evidence": [["source_url": "https://example.org/paper",
                "quote": "Original quote \(index)", "location": "Page \(index + 1)"]]] as [String: Any]
        }
        let data = paperDraft(overrides: ["claims": claims])
        let path = URL(fileURLWithPath: fixture.report.articleDraftPath)
        try data.write(to: path)
        let browser = ReportBrowserModel()
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        browser.openPaper(0)
        let store = AppStore(configuration: AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot,
            codexExecutable: nil), runtime: .init(windowMode: .full, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let host = NSHostingView(rootView: ReportBrowserView(store: store, report: fixture.report,
            localization: LocalizationStore(preference: language), presentation: WindowPresentationState(),
            back: {}, configure: {}, browser: browser))
        host.sizingOptions = []
        let window = NSWindow(contentRect: .init(x: 0, y: 0, width: 700, height: 620),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        for _ in 0..<50 {
            await Task.yield(); host.layoutSubtreeIfNeeded()
            if documentHeight(host) != nil { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(!browser.evidenceExpanded)
        let closedHeight = try #require(documentHeight(host))
        browser.evidenceExpanded = true
        try await Task.sleep(for: .milliseconds(80)); host.layoutSubtreeIfNeeded()
        #expect(try #require(documentHeight(host)) > closedHeight + 1000)
        browser.evidenceExpanded = false
        try await Task.sleep(for: .milliseconds(80)); host.layoutSubtreeIfNeeded()
        #expect(abs(try #require(documentHeight(host)) - closedHeight) < 1)
        #expect(browser.selectedPaper?.id == 0)
        #expect(browser.selectedPaper?.claims.count == 36)
        #expect(browser.selectedPaper?.claims[0].evidence[0].quote == "Original quote 0")
        #expect(try Data(contentsOf: path) == data)
    }
}

@MainActor private func documentHeight(_ host: NSView) -> CGFloat? {
    reportViewDescendants(host).compactMap { $0 as? NSScrollView }.first?.documentView?.bounds.height
}
