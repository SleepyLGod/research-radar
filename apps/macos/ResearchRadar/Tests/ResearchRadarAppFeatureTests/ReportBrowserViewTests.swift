import AppKit
import ResearchRadarCore
import SwiftUI
import Testing
import WebKit
@testable import ResearchRadarAppFeature

@MainActor struct ReportBrowserViewTests {
    @Test func previewsAndSinglePaperNeverPreloadWebKit() async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        let fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        try paperDraft().write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        var config = AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot, codexExecutable: nil)
        config.topics = [.init(id: "reader", displayName: "Reader", researchFocus: "Offline",
            queries: ["offline"], paperQueries: ["offline"], reportLanguage: .english)]
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: [fixture.report]),
            runtime: .init(onboardingStep: .complete, windowMode: .full,
                selectedTopicID: "reader", updatedAt: Date()), appSupportRoot: root, secretStore: AdmissionSecrets())
        let browser = ReportBrowserModel()
        let presentation = WindowPresentationState()
        let host = NSHostingView(rootView: ReportBrowserView(store: store, report: fixture.report,
            localization: LocalizationStore(preference: .english), presentation: presentation,
            back: {}, configure: {}, browser: browser))
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 600),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        for _ in 0..<50 {
            if browser.contents != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        try #require(browser.contents?.papers.count == 2)
        #expect(!reportViewDescendants(host).contains { $0 is WKWebView })
        browser.openPaper(0)
        #expect(browser.selectedPaper?.title == "第一篇 Paper A")
        #expect(!reportViewDescendants(host).contains { $0 is WKWebView })
        presentation.isVisible = false
        try await Task.sleep(for: .milliseconds(50))
        presentation.isVisible = true
        #expect(browser.selectedPaper?.title == "第一篇 Paper A")
        browser.back()
        #expect(browser.page == .overview)
        browser.openPaper(1)
        #expect(browser.selectedPaper?.claims.first?.text == "第二篇的结论")
        browser.page = .fullReport
        for _ in 0..<50 {
            if reportViewDescendants(host).contains(where: { $0 is WKWebView }) { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        weak var reader = reportViewDescendants(host).compactMap { $0 as? WKWebView }.first
        try #require(reader != nil)
        presentation.isVisible = false
        for _ in 0..<50 {
            if reader == nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        #expect(reader == nil)
        #expect(browser.page == .fullReport)
        presentation.isVisible = true
        browser.back()
        #expect(browser.page == .overview)
    }
}

@MainActor func reportViewDescendants(_ view: NSView) -> [NSView] {
    [view] + view.subviews.flatMap { reportViewDescendants($0) }
}
