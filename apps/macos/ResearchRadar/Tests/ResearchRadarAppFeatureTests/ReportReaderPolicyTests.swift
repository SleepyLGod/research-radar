import AppKit
import Foundation
import ResearchRadarCore
import Testing
import WebKit
@testable import ResearchRadarAppFeature

struct ReportReaderPolicyTests {
    @Test func rejectsRunRootSymlinkOutsideWorkspace() throws {
        let fixture = try ReaderFixture()
        let outside = try ReaderFixture()
        let link = fixture.workspaceRoot.appending(path: "escape")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: outside.root)
        let report = fixture.record(path: link.appending(path: "wechat.html").path, runDirectory: link.path)
        #expect(throws: (any Error).self) { try ReportReaderPolicy(report: report, workspaceRoot: fixture.workspaceRoot) }
    }

    @Test func rejectsAncestorSymlinkOutsideWorkspace() throws {
        let fixture = try ReaderFixture()
        let outside = try ReaderFixture()
        let link = fixture.workspaceRoot.appending(path: "escape")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: outside.workspaceRoot)
        let run = link.appending(path: "runs/report")
        let report = fixture.record(path: run.appending(path: "wechat.html").path, runDirectory: run.path)
        #expect(throws: (any Error).self) { try ReportReaderPolicy(report: report, workspaceRoot: fixture.workspaceRoot) }
    }

    @Test func reportCannotAuthorizeAnUnrelatedRoot() throws {
        let fixture = try ReaderFixture()
        let outside = try ReaderFixture()
        #expect(throws: (any Error).self) {
            try ReportReaderPolicy(report: outside.report, workspaceRoot: fixture.workspaceRoot)
        }
    }

    @Test(arguments: [false, true]) func rejectsRunOrAncestorReplacementAfterValidation(ancestor: Bool) throws {
        let fixture = try ReaderFixture()
        let outside = try ReaderFixture()
        let policy = try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        let replaced = ancestor ? fixture.root.deletingLastPathComponent() : fixture.root
        let target = ancestor ? outside.root.deletingLastPathComponent() : outside.root
        try FileManager.default.moveItem(at: replaced, to: fixture.workspaceRoot.appending(path: "retired"))
        try FileManager.default.createSymbolicLink(at: replaced, withDestinationURL: target)
        #expect(throws: (any Error).self) { try policy.resource(at: policy.entryURL) }
        #expect(throws: (any Error).self) {
            try policy.resource(at: URL(string: "radar-report://run/figures/pixel.png")!)
        }
    }

    @Test func pinsTrustedWorkspaceAgainstPathReplacement() throws {
        let fixture = try ReaderFixture()
        let outside = try ReaderFixture()
        let policy = try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        try Data("outside secret".utf8).write(to: outside.root.appending(path: "wechat.html"))
        let moved = fixture.workspaceRoot.deletingLastPathComponent().appending(path: "retired-\(UUID())")
        try FileManager.default.moveItem(at: fixture.workspaceRoot, to: moved)
        try FileManager.default.createSymbolicLink(at: fixture.workspaceRoot, withDestinationURL: outside.workspaceRoot)
        #expect(try policy.resource(at: policy.entryURL).data == Data(fixture.html.utf8))
    }

    @Test func acceptsMixedMacOSTemporaryPathAliases() throws {
        let fixture = try ReaderFixture()
        let short = fixture.workspaceRoot.path.replacingOccurrences(of: "/private/var/", with: "/var/")
        #expect(short.hasPrefix("/var/"))
        let canonical = "/private" + short
        for (workspace, run) in [(short, canonical + "/runs/report"), (canonical, short + "/runs/report")] {
            let report = fixture.record(path: run + "/wechat.html", runDirectory: run)
            let policy = try ReportReaderPolicy(report: report, workspaceRoot: URL(fileURLWithPath: workspace))
            #expect(try policy.resource(at: policy.entryURL).data == Data(fixture.html.utf8))
        }
    }

    @Test func readsUnchangedEntryAndRelativeAssets() throws {
        let fixture = try ReaderFixture()
        let policy = try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        #expect(try policy.resource(at: policy.entryURL).data == Data(fixture.html.utf8))
        let asset = URL(string: "figures/image.svg", relativeTo: policy.entryURL)!.absoluteURL
        #expect(try policy.resource(at: asset).mimeType == "image/svg+xml")
        #expect(try policy.resource(at: asset).data == Data(fixture.svg.utf8))
    }

    @Test func rejectsEscapesMissingFilesAndUnsafeResourceSchemes() throws {
        let fixture = try ReaderFixture()
        let policy = try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        for address in ["https://example.invalid/image.png", "file:///etc/passwd", "data:text/html,test",
                        "radar-report://other/wechat.html", "radar-report://run/%2e%2e/secret.txt",
                        "radar-report://run/figures/missing.png", "radar-report://run/figures/"] {
            #expect(throws: (any Error).self) { try policy.resource(at: URL(string: address)!) }
        }
        #expect(throws: (any Error).self) {
            try ReportReaderPolicy(report: fixture.record(path: fixture.root.path + "-sibling/wechat.html"), workspaceRoot: fixture.workspaceRoot)
        }
        #expect(throws: (any Error).self) {
            try ReportReaderPolicy(report: fixture.record(path: fixture.root.appending(path: "missing.html").path), workspaceRoot: fixture.workspaceRoot)
        }
    }

    @Test func rejectsEntryAndAssetSymlinksIncludingReplacementAfterValidation() throws {
        let fixture = try ReaderFixture()
        let outside = fixture.root.deletingLastPathComponent().appending(path: "outside-\(UUID()).svg")
        try Data("secret".utf8).write(to: outside)
        let link = fixture.root.appending(path: "escape.html")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: outside)
        #expect(throws: (any Error).self) { try ReportReaderPolicy(report: fixture.record(path: link.path), workspaceRoot: fixture.workspaceRoot) }
        let policy = try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        try FileManager.default.createSymbolicLink(at: fixture.root.appending(path: "linked"),
                                                  withDestinationURL: outside.deletingLastPathComponent())
        #expect(throws: (any Error).self) {
            try policy.resource(at: URL(string: "radar-report://run/linked/\(outside.lastPathComponent)")!)
        }
        let asset = fixture.root.appending(path: "figures/image.svg")
        try FileManager.default.moveItem(at: asset, to: fixture.root.appending(path: "original.svg"))
        try FileManager.default.createSymbolicLink(at: asset, withDestinationURL: outside)
        #expect(throws: (any Error).self) {
            try policy.resource(at: URL(string: "radar-report://run/figures/image.svg")!)
        }
    }

    @Test func onlyExplicitUserWebLinksLeaveReaderAndOnlyEntryAnchorsNavigate() throws {
        let fixture = try ReaderFixture()
        let policy = try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        #expect(policy.navigation(to: policy.entryURL, userActivated: false, mainFrame: true) == .allow)
        let anchor = URL(string: "#formula", relativeTo: policy.entryURL)!.absoluteURL
        #expect(policy.navigation(to: anchor, userActivated: true, mainFrame: true) == .allow)
        for address in ["https://example.invalid/paper", "http://example.invalid/paper"] {
            let url = URL(string: address)!
            #expect(policy.navigation(to: url, userActivated: true, mainFrame: true) == .external)
            #expect(policy.navigation(to: url, userActivated: false, mainFrame: true) == .cancel)
            #expect(policy.navigation(to: url, userActivated: true, mainFrame: false) == .cancel)
        }
        for address in ["javascript:alert(1)", "data:text/html,test", "ftp://example.invalid/a",
                        "file:///etc/passwd", "radar-report://run/other.html"] {
            #expect(policy.navigation(to: URL(string: address)!, userActivated: true, mainFrame: true) == .cancel)
        }
    }
}

@MainActor @Suite struct ReportReaderLifecycleTests {
    @Test func backToBackRequestsForSameReportRenderDespiteCancelledPreparation() async throws {
        _ = NSApplication.shared
        let fixture = try ReaderFixture()
        let report = fixture.report
        let host = ReportReaderHost()
        host.frame = NSRect(x: 0, y: 0, width: 640, height: 480)
        defer { host.releaseReader() }
        // Neither preparation can start until this actor yields. The second
        // request cancels the first before it has reserved the report identity.
        host.requestDisplay(report, workspaceRoot: fixture.workspaceRoot)
        host.requestDisplay(report, workspaceRoot: fixture.workspaceRoot)
        for _ in 0..<100 {
            if host.webView?.title == "Reader fixture", host.webView?.isLoading == false { break }
            if host.errorKey != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        #expect(host.errorKey == nil)
        let web = try #require(host.webView)
        #expect(web.title == "Reader fixture")
        #expect(try await web.evaluateJavaScript("document.images[1].naturalWidth") as? Int == 1)
        host.requestDisplay(report, workspaceRoot: fixture.workspaceRoot)
        #expect(host.webView === web)
    }

    @Test func demandLoadedReusedAndReleasedOnDismantleAndPressure() async throws {
        _ = NSApplication.shared
        let host = ReportReaderHost()
        #expect(host.webView == nil)
        let fixture = try ReaderFixture()
        let report = fixture.report
        await host.display(report, workspaceRoot: fixture.workspaceRoot)
        let first = try #require(host.webView)
        #expect(!first.configuration.websiteDataStore.isPersistent)
        #expect(!first.configuration.defaultWebpagePreferences.allowsContentJavaScript)
        await host.display(report, workspaceRoot: fixture.workspaceRoot)
        #expect(host.webView === first)
        host.releaseReader()
        #expect(host.webView == nil)
        #expect(first.navigationDelegate == nil)
        #expect(first.uiDelegate == nil)
        #expect(first.superview == nil)
        await host.display(report, workspaceRoot: fixture.workspaceRoot)
        #expect(host.webView != nil)
        host.handleMemoryPressure()
        #expect(host.webView == nil)
        #expect(host.errorKey == "reader.memoryPressure")
        await host.display(report, workspaceRoot: fixture.workspaceRoot)
        #expect(host.webView == nil)
    }

    @Test func dismantleDuringPreparationCannotResurrectWebView() async throws {
        let host = ReportReaderHost()
        let fixture = try ReaderFixture()
        let work = Task { await host.display(fixture.report, workspaceRoot: fixture.workspaceRoot) }
        await Task.yield()
        host.releaseReader()
        await work.value
        #expect(host.webView == nil)
    }

    @Test func dismantleBeforePreparationStartsDoesNotCreateWebView() async throws {
        let host = ReportReaderHost()
        let fixture = try ReaderFixture()
        host.requestDisplay(fixture.report, workspaceRoot: fixture.workspaceRoot)
        ReportReaderRepresentable.dismantleNSView(host, coordinator: ())
        try await Task.sleep(for: .milliseconds(300))
        #expect(host.webView == nil)
    }

    @Test func releaseDropsLastAppReference() async throws {
        let host = ReportReaderHost()
        let fixture = try ReaderFixture()
        await host.display(fixture.report, workspaceRoot: fixture.workspaceRoot)
        weak let web = host.webView
        #expect(web != nil)
        ReportReaderRepresentable.dismantleNSView(host, coordinator: ())
        for _ in 0..<20 {
            if web == nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        #expect(web == nil)
    }

    @Test func representableRequestRendersLocalImageFormulaAndAnchorWithoutPageScripts() async throws {
        _ = NSApplication.shared
        let fixture = try ReaderFixture()
        let mixedHTML = fixture.html.replacingOccurrences(
            of: "<body>",
            with: "<body><p id='mixed'>相关工作：SimpleMem；局限与未来工作；Mem-α</p>"
        )
        try Data(mixedHTML.utf8).write(to: fixture.root.appending(path: "wechat.html"))
        let original = try Data(contentsOf: fixture.root.appending(path: "wechat.html"))
        var opened: [URL] = []
        let host = ReportReaderHost(openExternal: { opened.append($0) })
        host.frame = NSRect(x: 0, y: 0, width: 640, height: 480)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer {
            ReportReaderRepresentable.dismantleNSView(host, coordinator: ())
            window.orderOut(nil)
            window.close()
        }
        host.requestDisplay(fixture.report, workspaceRoot: fixture.workspaceRoot)
        for _ in 0..<100 {
            if host.webView?.title == "Reader fixture", host.webView?.isLoading == false { break }
            if host.errorKey != nil { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        #expect(host.errorKey == nil)
        let web = try #require(host.webView)
        #expect(web.title == "Reader fixture")
        // App-side inspection does not enable page JavaScript.
        let encoding = try await web.evaluateJavaScript("document.characterSet") as? String
        #expect(encoding == "UTF-8")
        let mixedText = try await web.evaluateJavaScript("document.getElementById('mixed').textContent") as? String
        #expect(mixedText == "相关工作：SimpleMem；局限与未来工作；Mem-α")
        let snapshot = try await web.takeSnapshot(configuration: nil)
        let bitmap = try #require(snapshot.tiffRepresentation.flatMap(NSBitmapImageRep.init(data:)))
        let snapshotURL = fixture.workspaceRoot.appending(path: "reader-utf8.png")
        try #require(bitmap.representation(using: .png, properties: [:])).write(to: snapshotURL)
        print("UTF-8 reader screenshot: \(snapshotURL.path)")
        let width = try await web.evaluateJavaScript("document.images[0].naturalWidth") as? Int
        #expect(width == 40)
        let pngWidth = try await web.evaluateJavaScript("document.images[1].naturalWidth") as? Int
        #expect(pngWidth == 1)
        let forbiddenWidth = try await web.evaluateJavaScript("document.images[2].naturalWidth") as? Int
        #expect(forbiddenWidth == 0)
        let formula = try await web.evaluateJavaScript("document.getElementById('formula').textContent") as? String
        #expect(formula == "E = mc2")
        let before = try await web.evaluateJavaScript("window.scrollY") as? Double
        let anchor = URL(string: "#formula", relativeTo: try ReportReaderPolicy(report: fixture.report, workspaceRoot: fixture.workspaceRoot).entryURL)!.absoluteURL
        web.load(URLRequest(url: anchor))
        for _ in 0..<30 {
            if web.url?.fragment == "formula", !web.isLoading { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        let after = try await web.evaluateJavaScript("window.scrollY") as? Double
        #expect(web.url?.fragment == "formula")
        #expect((after ?? 0) > (before ?? 0))
        #expect(!web.configuration.defaultWebpagePreferences.allowsContentJavaScript)
        web.load(URLRequest(url: URL(string: "data:text/html,<title>Unsafe</title>")!))
        try await Task.sleep(for: .milliseconds(100))
        #expect(web.title == "Reader fixture")
        #expect(web.url?.scheme == "radar-report")
        _ = try await web.evaluateJavaScript("document.getElementById('paper').click()")
        for _ in 0..<20 {
            if !opened.isEmpty { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        #expect(opened.map(\.absoluteString) == ["https://example.invalid/paper"])
        #expect(web.url?.scheme == "radar-report")
        #expect(try Data(contentsOf: fixture.root.appending(path: "wechat.html")) == original)
        let image = try await web.takeSnapshot(configuration: nil)
        #expect(image.size.width > 0 && image.size.height > 0)
    }
}

struct ReaderFixture {
    let workspaceRoot: URL
    let root: URL
    let html = "<html><head><title>Reader fixture</title><script>document.title='Script ran';</script></head><body><a href='#formula'>Formula</a><img src='figures/image.svg'><img src='figures/pixel.png'><img src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2210%22 height=%2210%22%3E%3C/svg%3E'><div style='height:1000px'></div><p id='formula' class='rr-formula'>E = mc<sup>2</sup></p><a id='paper' target='_blank' href='https://example.invalid/paper'>Paper</a></body></html>"
    let svg = "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'><rect width='40' height='40' fill='red'/></svg>"

    init() throws {
        workspaceRoot = FileManager.default.temporaryDirectory.appending(path: "reader-test-\(UUID())")
        root = workspaceRoot.appending(path: "runs/report")
        try FileManager.default.createDirectory(at: root.appending(path: "figures"), withIntermediateDirectories: true)
        try Data(html.utf8).write(to: root.appending(path: "wechat.html"))
        try Data(svg.utf8).write(to: root.appending(path: "figures/image.svg"))
        let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")!
        try png.write(to: root.appending(path: "figures/pixel.png"))
    }

    var report: ReportRecordV1 { record(path: root.appending(path: "wechat.html").path) }

    func record(path: String, runDirectory: String? = nil) -> ReportRecordV1 {
        ReportRecordV1(topicID: "reader", reportDate: "2026-09-19", runDirectory: runDirectory ?? root.path,
                       articleDraftPath: root.appending(path: "article_draft.json").path,
                       reportHTMLPath: path, title: "Reader fixture", summary: "", sourceCount: 0,
                       deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: Date())
    }
}
