import Foundation
import ImageIO
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

struct ReportContentsTests {
    @Test func figureKeepsItsExplanationAndBothDistinctCaptions() throws {
        let paper = try ReportContents.decode(paperDraft(overrides: ["figures": [[
            "relative_path": "figures/pixel.png", "caption": "Architecture 42%",
            "localized_caption": "架构 42%", "explanation": "已有的公开读图说明 42%",
            "reuse_status": "PRIVATE AUDIT", "score": 42
        ]]]), topicID: "reader").papers[0]
        let figure = try #require(paper.figures.first)
        #expect(figure.displayCaption == "架构 42%")
        #expect(figure.originalCaption == "Architecture 42%")
        #expect(figure.explanation == "已有的公开读图说明 42%")
        #expect(!String(describing: figure).contains("PRIVATE AUDIT"))
    }

    @Test func blankLegacyDetailsDoNotCreateChaptersAndDuplicateTextIsShownOnce() throws {
        let paper = try ReportContents.decode(paperDraft(overrides: [
            "solution": ["core": "方法解释。", "mechanism": "方法解释。"],
            "problem": ["why_it_matters": "  ", "hidden_assumptions": ["", "\n"]],
            "limitations": ["future_work": []], "plain_language_example": " "
        ]), topicID: "reader").papers[0]
        #expect(paper.paragraphs.map(\.key) == ["thesis", "method"])
        #expect(paper.paragraphs.filter { $0.text == "方法解释。" }.count == 1)
    }

    @Test func takeawayDoesNotReplaceADistinctPublishedAssessment() throws {
        let paper = try ReportContents.decode(paperDraft(overrides: [
            "reader_explanation": ["reader_takeaway": "读者要点"],
            "critical_assessment": ["bottom_line": "不同的已有判断"]
        ]), topicID: "reader").papers[0]
        #expect(paper.paragraphs.first { $0.key == "assessment" }?.text == "不同的已有判断")
        #expect(paper.paragraphs.first { $0.key == "takeaway" }?.text == "读者要点")
    }

    @Test func preservesPublishedLegacyDetailsAlongsideNarrative() throws {
        let contents = try ReportContents.decode(paperDraft(overrides: [
            "problem": ["core": "研究问题", "why_it_matters": "为什么重要", "hidden_assumptions": ["假设 A", "假设 B"]],
            "solution": ["core": "方法摘要", "mechanism": "公开机制说明"],
            "related_work": ["novelty": "公开差异", "prior_work": ["先前方法 A"], "repackaging_risk": "复用边界"],
            "limitations": ["explicit_limitations": ["作者局限"], "inferred_weaknesses": ["推断局限"], "future_work": ["未来工作"]],
            "critical_assessment": ["bottom_line": "已有判断", "overclaiming_risk": "过度主张风险",
                "weak_evaluations": ["评估不足"], "missing_ablations": ["消融缺失"]],
            "plain_language_example": "已有通俗例子"
        ]), topicID: "reader")
        let texts = contents.papers[0].paragraphs.map(\.text).joined(separator: "\n")
        for expected in ["为什么重要", "假设 A", "假设 B", "公开机制说明", "先前方法 A", "复用边界",
                         "作者局限", "推断局限", "未来工作", "已有判断", "过度主张风险", "评估不足", "消融缺失", "已有通俗例子"] {
            #expect(texts.contains(expected), "Missing public detail: \(expected)")
        }
        #expect(!texts.contains("PRIVATE AUDIT"))
        #expect(contents.papers[0].claims[0].evidence[0].quote == "Original evidence 42%")
    }

    @Test func readsOnlyPublicPaperEntriesAndKeepsSourcesSeparate() throws {
        let contents = try ReportContents.decode(paperDraft(), topicID: "reader")
        #expect(contents.papers.map(\.title) == ["第一篇 Paper A", "Paper B"])
        #expect(contents.papers.map(\.id) == [0, 1])
        #expect(contents.papers[0].summary == "已经通过证据检查的说明。")
        #expect(contents.papers[0].paragraphs.map(\.text) == ["已经通过证据检查的说明。", "方法解释。"])
        #expect(contents.papers[1].paragraphs.map(\.text) == ["旧格式的公开方法。"])
        #expect(contents.papers[0].claims[0].evidence[0].quote == "Original evidence 42%")
        #expect(contents.papers[0].claims[0].evidence[0].url?.absoluteString == "https://example.org/paper")
        #expect(contents.sources.map(\.title) == ["只发现的来源"])
        #expect(!String(describing: contents).contains("PRIVATE AUDIT"))
    }

    @Test func rejectsTopicMismatchAndMalformedData() {
        #expect(throws: (any Error).self) { try ReportContents.decode(paperDraft(), topicID: "other") }
        #expect(throws: (any Error).self) { try ReportContents.decode(Data("not JSON".utf8), topicID: "reader") }
    }

    @Test func legacySectionsDoNotBecomePretendDeepReads() throws {
        let contents = try ReportContents.decode(Data(#"{"topic_id":"reader","sections":[{"body":"Unfiltered old prose"}]}"#.utf8), topicID: "reader")
        #expect(contents.papers.isEmpty)
        #expect(contents.sources.isEmpty)
    }

    @Test func emptyExplanationFieldsUseNonemptyPublicFallbacks() throws {
        let contents = try ReportContents.decode(paperDraft(overrides: [
            "reader_explanation": ["core_thesis": "", "solution_walkthrough": "  ", "reader_takeaway": ""],
            "essence": "", "solution": ["core": "可用的方法说明"],
            "critical_assessment": ["bottom_line": "可用的边界提醒"]
        ]), topicID: "reader")
        #expect(contents.papers[0].summary == "结果 42%")
        #expect(contents.papers[0].paragraphs.map(\.text) == ["可用的方法说明", "可用的边界提醒"])
    }

    @Test func legacyPageScreenshotsDoNotBecomeNativeFigures() throws {
        let figures: [[String: Any]] = [
            ["relative_path": "figures/01-page-3.png", "caption": "Entire page", "renderable": true],
            ["relative_path": "figures/old.png", "original_path": "Page 4", "caption": "Entire page", "renderable": true],
            ["relative_path": "figures/no.png", "caption": "Not approved", "renderable": false],
            ["relative_path": "figures/real.png", "caption": "Original", "localized_caption": "论文架构图", "renderable": true]
        ]
        let contents = try ReportContents.decode(paperDraft(overrides: ["figures": figures]), topicID: "reader")
        #expect(contents.papers[0].figures.map(\.relativePath) == ["figures/real.png"])
        #expect(contents.papers[0].figures[0].displayCaption == "论文架构图")
    }

    @Test func nativeRasterLoaderSupportsGifAndWebPAndRejectsEscape() throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let images = [
            "gif": "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
            "webp": "UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA"
        ]
        for (ext, base64) in images {
            let path = "figures/test.\(ext)"
            try #require(Data(base64Encoded: base64)).write(to: fixture.root.appending(path: path))
            let data = try ReportFigureLoader.thumbnailData(path: path, report: fixture.report, workspace: fixture.workspaceRoot)
            let image = try #require(CGImageSourceCreateWithData(data as CFData, nil))
            #expect(CGImageSourceGetCount(image) == 1)
        }
        for path in ["../outside.png", "https://example.org/image.png", "missing.png"] {
            #expect(throws: (any Error).self) {
                try ReportFigureLoader.thumbnailData(path: path, report: fixture.report, workspace: fixture.workspaceRoot)
            }
        }
    }

    @Test func nativeThumbnailsAreBoundedAndMalformedRasterIsRejected() throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let context = try #require(CGContext(data: nil, width: 2400, height: 16, bitsPerComponent: 8,
            bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        let image = try #require(context.makeImage())
        let original = NSMutableData()
        let destination = try #require(CGImageDestinationCreateWithData(original, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil)
        try #require(CGImageDestinationFinalize(destination))
        try (original as Data).write(to: fixture.root.appending(path: "figures/large.png"))
        let bytes = try ReportFigureLoader.thumbnailData(path: "figures/large.png", report: fixture.report, workspace: fixture.workspaceRoot)
        let source = try #require(CGImageSourceCreateWithData(bytes as CFData, nil))
        let thumbnail = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
        #expect(thumbnail.width == 1600)
        #expect(thumbnail.height > 0 && thumbnail.height < 16)
        try Data("not an image".utf8).write(to: fixture.root.appending(path: "figures/broken.png"))
        #expect(throws: (any Error).self) {
            try ReportFigureLoader.thumbnailData(path: "figures/broken.png", report: fixture.report, workspace: fixture.workspaceRoot)
        }
    }

    @Test func unsafeLinksAreNotExposedAsActions() throws {
        for link in ["file:///tmp/secret", "javascript:alert(1)", "https://user:pass@example.org/p", "https:///empty"] {
            let data = paperDraft(link: link)
            let contents = try ReportContents.decode(data, topicID: "reader")
            #expect(contents.papers[0].sourceURL == nil)
            #expect(contents.papers[0].claims[0].evidence[0].url == nil)
        }
    }

    @Test func safeLoaderDoesNotFollowDraftSymlinkOrAnotherRun() throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let path = URL(fileURLWithPath: fixture.report.articleDraftPath)
        try paperDraft().write(to: path)
        let before = try Data(contentsOf: path)
        let contents = try ReportContents.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        #expect(contents.papers.count == 2)
        #expect(try Data(contentsOf: path) == before)
        let moved = fixture.root.appending(path: "original.json")
        try FileManager.default.moveItem(at: path, to: moved)
        try FileManager.default.createSymbolicLink(at: path, withDestinationURL: moved)
        #expect(throws: (any Error).self) {
            try ReportContents.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        }
        let original = fixture.report
        let outside = ReportRecordV1(topicID: original.topicID, reportDate: original.reportDate,
            runDirectory: original.runDirectory, articleDraftPath: fixture.workspaceRoot.appending(path: "other.json").path,
            reportHTMLPath: original.reportHTMLPath, title: original.title, summary: original.summary,
            sourceCount: 0, deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: Date())
        try paperDraft().write(to: URL(fileURLWithPath: outside.articleDraftPath))
        #expect(throws: (any Error).self) {
            try ReportContents.load(report: outside, workspaceRoot: fixture.workspaceRoot)
        }
    }
}

@MainActor struct ReportBrowserModelTests {
    @Test func paperAndFullReportReturnToPreviewsWithoutLosingSelection() async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        try paperDraft().write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        let browser = ReportBrowserModel()
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        #expect(browser.page == .overview)
        #expect(browser.contents?.papers.count == 2)
        browser.openPaper(1)
        #expect(browser.selectedPaper?.title == "Paper B")
        browser.openPaper(900)
        #expect(browser.selectedPaper?.title == "Paper B")
        browser.back()
        #expect(browser.page == .overview)
        browser.page = .fullReport
        browser.back()
        #expect(browser.page == .overview)
    }

    @Test func missingDraftHasExplicitFallbackNotInventedPapers() async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let browser = ReportBrowserModel()
        await browser.load(report: fixture.report, workspaceRoot: fixture.workspaceRoot)
        #expect(browser.loadFailed)
        #expect(browser.contents == nil)
        #expect(browser.page == .overview)
    }
}

func paperDraft(link: String = "https://example.org/paper", overrides: [String: Any] = [:]) -> Data {
    var deep: [[String: Any]] = [
        ["title": "第一篇 Paper A", "source": ["url": link, "version": "v2"],
         "essence": "Fallback", "reader_explanation": ["core_thesis": "已经通过证据检查的说明。", "solution_walkthrough": "方法解释。"],
         "explanation_audit": "PRIVATE AUDIT", "claims": [["text": "结果 42%", "rationale": "PRIVATE AUDIT",
            "evidence": [["source_url": link, "quote": "Original evidence 42%", "location": "Page 2"]]]]],
        ["title": "Paper B", "source": ["url": "https://example.org/b"],
         "solution": ["core": "旧格式的公开方法。"], "claims": [["text": "第二篇的结论", "evidence": []]]],
        ["title": "Not a public deep read", "claims": []]
    ]
    deep[0].merge(overrides) { _, new in new }
    let root: [String: Any] = ["topic_id": "reader", "claims": [["text": "PRIVATE AUDIT", "status": "rejected"]],
        "sections": [["metadata": ["kind": "deep_reads", "deep_reads": deep]],
                     ["metadata": ["kind": "new_updated_sources", "sources": [["title": "只发现的来源", "url": "https://example.org/source", "gist": "仅来源概括", "role": "PRIVATE AUDIT"]]]],
                     ["metadata": ["kind": "seen_before", "sources": [["title": "Old link", "url": link]]]]]]
    return try! JSONSerialization.data(withJSONObject: root)
}
