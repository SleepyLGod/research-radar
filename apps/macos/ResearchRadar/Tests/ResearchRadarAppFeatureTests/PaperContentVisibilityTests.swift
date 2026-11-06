import AppKit
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor struct PaperContentVisibilityTests {
    @Test func missingMalformedAndUnsafeImagesCannotLeaveAChapterOrFigureNotes() async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        try Data("not an image".utf8).write(to: fixture.root.appending(path: "figures/broken.png"))
        try FileManager.default.createSymbolicLink(at: fixture.root.appending(path: "figures/link.png"),
            withDestinationURL: fixture.root.appending(path: "figures/pixel.png"))
        let invalid = ["figures/missing.png", "figures/broken.png", "figures/link.png", "../outside.png", "https://example.invalid/image.png"]
        let entries: [[String: Any]] = invalid.map { ["relative_path": $0, "caption": "Omit with image", "explanation": "Omit with image"] }
        let paper = try ReportContents.decode(paperDraft(overrides: ["figures": entries]), topicID: "reader").papers[0]
        let model = PaperFiguresModel()
        await model.load(paper: paper, report: fixture.report, workspace: fixture.workspaceRoot)
        #expect(model.images(for: paper.id).isEmpty)
        #expect(!paper.readingSections(hasAvailableFigures: !model.images(for: paper.id).isEmpty).map(\.id).contains(.figures))

        let mixed = try ReportContents.decode(paperDraft(overrides: ["figures": entries + [[
            "relative_path": "figures/pixel.png", "caption": "Safe image", "explanation": "Keep this note"
        ]]]), topicID: "reader").papers[0]
        await model.load(paper: mixed, report: fixture.report, workspace: fixture.workspaceRoot)
        #expect(model.images(for: mixed.id).map(\.content.relativePath) == ["figures/pixel.png"])
        #expect(model.images(for: mixed.id).first?.content.explanation == "Keep this note")
        #expect(mixed.readingSections(hasAvailableFigures: !model.images(for: mixed.id).isEmpty).map(\.id).contains(.figures))
    }

    @Test func hidingSwitchingAndCancellationReleasePaperImages() async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let papers = try ReportContents.decode(paperDraft(overrides: ["figures": [[
            "relative_path": "figures/pixel.png", "caption": "Only paper A"
        ]]]), topicID: "reader").papers
        let model = PaperFiguresModel()
        await model.load(paper: papers[0], report: fixture.report, workspace: fixture.workspaceRoot)
        weak var image: NSImage?
        image = try #require(model.images(for: 0).first?.image)
        #expect(model.images(for: 1).isEmpty)
        await model.load(paper: nil, report: fixture.report, workspace: fixture.workspaceRoot)
        #expect(model.images(for: 0).isEmpty)
        #expect(image == nil)
        await model.load(paper: papers[1], report: fixture.report, workspace: fixture.workspaceRoot)
        #expect(model.images(for: 0).isEmpty)
        let cancelled = Task { await model.load(paper: papers[0], report: fixture.report, workspace: fixture.workspaceRoot) }
        cancelled.cancel()
        await cancelled.value
        #expect(model.images(for: 0).isEmpty)
        await model.load(paper: papers[0], report: fixture.report, workspace: fixture.workspaceRoot)
        #expect(model.images(for: 0).count == 1)
        let staleHide = Task { await model.load(paper: nil, report: fixture.report, workspace: fixture.workspaceRoot) }
        staleHide.cancel()
        await staleHide.value
        #expect(model.images(for: 0).count == 1)
    }

    @Test func imageMetadataAloneDoesNotCreateAnAvailableChapter() throws {
        let paper = try ReportContents.decode(paperDraft(overrides: ["figures": [[
            "relative_path": "figures/missing.png", "caption": "Missing image", "renderable": true
        ]]]), topicID: "reader").papers[0]
        #expect(!paper.readingSections().map(\.id).contains(.figures))
    }

    @Test(arguments: [false, true])
    func figureNotesAppearOnlyWithTheirLoadedImage(available: Bool) async throws {
        _ = NSApplication.shared
        let root = try task3Root()
        let fixture = try ReaderFixture()
        defer { task3Trash(root); task3Trash(fixture.workspaceRoot) }
        let draft = paperDraft(overrides: ["figures": [[
            "relative_path": available ? "figures/pixel.png" : "figures/missing.png",
            "caption": "Visible caption", "explanation": "Existing public figure explanation 42%", "renderable": true
        ]]])
        try draft.write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        let browser = ReportBrowserModel()
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        browser.openPaper(0)
        let store = AppStore(configuration: AppConfigurationDefaults.make(workspaceRoot: fixture.workspaceRoot, codexExecutable: nil),
            runtime: .init(onboardingStep: .complete, windowMode: .full, updatedAt: Date()),
            appSupportRoot: root, secretStore: AdmissionSecrets())
        let host = NSHostingView(rootView: ReportBrowserView(store: store, report: fixture.report,
            localization: LocalizationStore(preference: .english), presentation: WindowPresentationState(),
            back: {}, configure: {}, browser: browser))
        host.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 900),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host; window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        for _ in 0..<40 {
            if available && paperAccessibilityText(host).contains("Existing public figure explanation 42%") { break }
            try await Task.sleep(for: .milliseconds(25))
        }
        let text = paperAccessibilityText(host)
        try #require(text.contains("方法解释。"))
        #expect(text.contains("Existing public figure explanation 42%") == available)
        #expect(try Data(contentsOf: URL(fileURLWithPath: fixture.report.articleDraftPath)) == draft)
        #expect(try Data(contentsOf: fixture.root.appending(path: "wechat.html")) == Data(fixture.html.utf8))
    }
}

@MainActor private func paperAccessibilityText(_ root: NSView) -> String {
    var visited = Set<ObjectIdentifier>()
    var labels: [String] = []
    func visit(_ value: Any, depth: Int) {
        guard depth < 40, let node = value as? any NSAccessibilityProtocol,
              visited.insert(ObjectIdentifier(node as AnyObject)).inserted else { return }
        labels += [node.accessibilityLabel(), node.accessibilityTitle(), node.accessibilityValue() as? String].compactMap { $0 }
        for child in (node.accessibilityChildren() ?? []) + (node.accessibilityVisibleChildren() ?? []) {
            visit(child, depth: depth + 1)
        }
        if let view = value as? NSView {
            for child in view.subviews { visit(child, depth: depth + 1) }
        }
    }
    visit(root, depth: 0)
    return labels.joined(separator: "\n")
}
