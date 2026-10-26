import AppKit
import Observation
import ResearchRadarCore
import SwiftUI
import Testing
import WebKit
@testable import ResearchRadarAppFeature

@MainActor @Observable private final class ReaderLayoutState {
    var expanded = false
}

private struct ReaderReturnProbe: NSViewRepresentable {
    let view: NSView
    func makeNSView(context: Context) -> NSView { view }
    func updateNSView(_ view: NSView, context: Context) {}
}

@MainActor @Suite struct ReaderLayoutTests {
    @Test(arguments: [540.0, 700.0], [AppLanguagePreference.english, .simplifiedChinese])
    func longNativePaperWrapsAndScrollsInsideItsPane(width: Double, language: AppLanguagePreference) async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        let fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        let report = fixture.report
        let data = paperDraft(overrides: [
            "title": String(repeating: "Memory Retrieval 与证据条件 ", count: 7),
            "reader_explanation": ["problem_walkthrough": String(repeating:
                "Research evidence retains context and numbers 42%. 中文解释保留原始条件与边界。\n\n", count: 24)]
        ])
        try data.write(to: URL(fileURLWithPath: report.articleDraftPath))
        let browser = ReportBrowserModel()
        await browser.load(report: report, workspaceRoot: fixture.workspaceRoot)
        browser.openPaper(0)
        let config = AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot, codexExecutable: nil)
        let store = AppStore(configuration: config, runtime: .init(onboardingStep: .complete, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let host = NSHostingView(rootView: ReportBrowserView(store: store, report: report,
            localization: LocalizationStore(preference: language), presentation: WindowPresentationState(),
            back: {}, configure: {}, browser: browser))
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: 508),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        try await Task.sleep(for: .milliseconds(250))
        host.layoutSubtreeIfNeeded()
        let scroll = try #require(reportViewDescendants(host).compactMap { $0 as? NSScrollView }.first)
        let document = try #require(scroll.documentView)
        let frame = scroll.convert(scroll.bounds, to: host)
        #expect(frame.minY >= -1 && frame.maxY <= host.bounds.maxY + 1)
        #expect(scroll.bounds.height < host.bounds.height - 70)
        #expect(document.bounds.width <= scroll.contentView.bounds.width + 1)
        #expect(document.bounds.height > scroll.contentView.bounds.height)
        scroll.contentView.scroll(to: NSPoint(x: 0, y: 400))
        scroll.reflectScrolledClipView(scroll.contentView)
        #expect(scroll.contentView.bounds.origin.y > 0)
        scroll.contentView.scroll(to: NSPoint.zero)
        scroll.reflectScrolledClipView(scroll.contentView)
        #expect(scroll.contentView.bounds.origin.y == 0)
        #expect(browser.page == .paper(0))
        #expect(!reportViewDescendants(host).contains { $0 is WKWebView })
        #expect(try Data(contentsOf: URL(fileURLWithPath: report.articleDraftPath)) == data)
    }

    @Test(arguments: [false, true], [AppLanguagePreference.english, .simplifiedChinese])
    func readingKeepsNavigationVisibleWithoutReservingDeliverySpace(
        retained: Bool, language: AppLanguagePreference
    ) async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        defer { task3Trash(root) }
        let fixture = try ReaderFixture()
        var report = fixture.report
        report.deliveries = [.init(channel: .email, state: .unknown)]
        var config = AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot, codexExecutable: nil)
        config.topics = [.init(id: "reader", displayName: "Reader", researchFocus: "Offline",
            queries: ["offline"], paperQueries: ["offline"], reportLanguage: .english)]
        let store = AppStore(configuration: config, reportSnapshot: .init(reports: [report]),
            runtime: .init(onboardingStep: .complete, windowMode: .full,
                selectedTopicID: "reader", updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        store.selectReport(report.id)
        let localization = LocalizationStore(preference: language)
        let browser = ReportBrowserModel()
        browser.page = .fullReport
        let readerContent = NavigationSplitView { Text("Reports") } detail: {
            ReportBrowserView(store: store, report: report, localization: localization,
                presentation: WindowPresentationState(), back: {}, configure: {}, browser: browser)
        }
        let inner = NSHostingView(rootView: readerContent)
        inner.sizingOptions = []
        inner.autoresizingMask = [.width, .height]
        let content = retained ? AnyView(ReaderReturnProbe(view: inner)) : AnyView(readerContent)
        let host = NSHostingView(rootView: content)
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 660),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        func descendants(_ view: NSView) -> [NSView] {
            [view] + view.subviews.flatMap { descendants($0) }
        }
        for _ in 0..<100 {
            if descendants(host).compactMap({ $0 as? WKWebView }).first?.isLoading == false { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        let reader = try #require(descendants(host).compactMap { $0 as? ReportReaderHost }.first)
        for _ in 0..<8 {
            try await Task.sleep(for: .milliseconds(50))
            host.layoutSubtreeIfNeeded()
            let frame = reader.convert(reader.bounds, to: host)
            #expect(frame.minY >= -1 && frame.maxY <= host.bounds.maxY + 1)
            #expect(reader.bounds.height < host.bounds.height - 40)
            #expect(reader.bounds.height > host.bounds.height - 110)
            for split in descendants(host).compactMap({ $0 as? NSSplitView }) {
                #expect(split.bounds.height <= host.bounds.height)
            }
        }
        window.setContentSize(NSSize(width: 696, height: 508))
        try await Task.sleep(for: .milliseconds(200))
        host.layoutSubtreeIfNeeded()
        let compactFrame = reader.convert(reader.bounds, to: host)
        #expect(compactFrame.minY >= -1 && compactFrame.maxY <= host.bounds.maxY + 1)
        for split in descendants(host).compactMap({ $0 as? NSSplitView }) {
            #expect(split.bounds.height <= host.bounds.height)
        }
        let web = try #require(reader.webView)
        let originalHTML = try Data(contentsOf: fixture.root.appending(path: "wechat.html"))
        for delta: Int32 in [-240, 240] {
            let event = try #require(CGEvent(scrollWheelEvent2Source: nil, units: .pixel,
                wheelCount: 1, wheel1: delta, wheel2: 0, wheel3: 0))
            web.scrollWheel(with: try #require(NSEvent(cgEvent: event)))
            var offset = -1.0
            for _ in 0..<40 {
                try await Task.sleep(for: .milliseconds(50))
                offset = try await web.evaluateJavaScript("window.scrollY") as? Double ?? -1
                if delta < 0 && offset > 0 || delta > 0 && offset == 0 { break }
            }
            #expect(delta < 0 ? offset > 0 : offset == 0)
        }
        #expect(try Data(contentsOf: fixture.root.appending(path: "wechat.html")) == originalHTML)
        #expect(!web.configuration.defaultWebpagePreferences.allowsContentJavaScript)
    }

    @Test func deliveryExpansionCannotGrowReaderOverReturnControls() async throws {
        _ = NSApplication.shared
        let fixture = try ReaderFixture()
        let state = ReaderLayoutState()
        let controls = NSView()
        let host = NSHostingView(rootView: VStack(spacing: 0) {
            Text("Toolbar").frame(height: 44)
            NavigationSplitView { Text("Reports") } detail: {
                VStack(spacing: 0) {
                    ReaderReturnProbe(view: controls).frame(height: 50)
                    DisclosureGroup(isExpanded: Bindable(state).expanded) {
                        Text("Delivery controls").frame(height: 260)
                    } label: { Text("Delivery") }
                    ReportReaderView(report: fixture.report, workspaceRoot: fixture.workspaceRoot,
                        localization: LocalizationStore(preference: .english))
                }
            }
        })
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 480),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        func descendants(_ view: NSView) -> [NSView] {
            [view] + view.subviews.flatMap { descendants($0) }
        }
        for _ in 0..<100 {
            if descendants(host).compactMap({ $0 as? WKWebView }).first?.isLoading == false { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        let reader = try #require(descendants(host).compactMap { $0 as? ReportReaderHost }.first)
        let originalHeight = reader.bounds.height
        try #require(originalHeight > 200)
        for expanded in [true, false, true] {
            withAnimation(.default) { state.expanded = expanded }
            for _ in 0..<12 {
                try await Task.sleep(for: .milliseconds(50))
                host.layoutSubtreeIfNeeded()
                let frame = reader.convert(reader.bounds, to: host)
                let header = controls.convert(controls.bounds, to: host)
                #expect(frame.intersection(header).isEmpty)
                #expect(reader.bounds.height <= originalHeight + 1)
                #expect(frame.minY >= -1 && frame.maxY <= host.bounds.maxY + 1)
                #expect(header.minY >= -1 && header.maxY <= host.bounds.maxY + 1)
                let point = host.convert(NSPoint(x: header.midX, y: header.midY), to: host.superview)
                let hit = host.hitTest(point)
                #expect(hit?.isDescendant(of: reader) != true)
            }
        }
    }
}
