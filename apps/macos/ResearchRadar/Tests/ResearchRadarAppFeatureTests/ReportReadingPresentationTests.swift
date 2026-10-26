import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

struct ReportReadingPresentationTests {
    @Test func friendlyHeadingRequiresTheMatchingTopicAndPreservesOriginalTitle() throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        let topic = TopicRecordV1(id: "reader", displayName: "智能体记忆研究", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["memory"], reportLanguage: .chinese)
        #expect(ReportHeading.title(report: fixture.report, topic: topic) == "智能体记忆研究")
        #expect(ReportHeading.title(report: fixture.report, topic: nil) == fixture.report.title)
        let unrelated = TopicRecordV1(id: "different", displayName: "Do not use this", researchFocus: "Other",
            queries: ["other"], paperQueries: ["other"], reportLanguage: .english)
        #expect(ReportHeading.title(report: fixture.report, topic: unrelated) == fixture.report.title)
        var empty = topic
        empty.displayName = "  "
        #expect(ReportHeading.title(report: fixture.report, topic: empty) == fixture.report.title)
        #expect(fixture.report.title != "智能体记忆研究")
    }

    @Test func previewsPreferAnExistingResearchQuestionThenThesisThenSummary() throws {
        let withQuestion = try ReportContents.decode(paperDraft(overrides: [
            "reader_explanation": ["core_thesis": "原有核心思路", "problem_walkthrough": "原有研究问题"]
        ]), topicID: "reader").papers[0]
        #expect(withQuestion.preview.titleKey == "paper.problem")
        #expect(withQuestion.preview.text == "原有研究问题")
        let withThesis = try ReportContents.decode(paperDraft(), topicID: "reader").papers[0]
        #expect(withThesis.preview.titleKey == "paper.thesis")
        #expect(withThesis.preview.text == "已经通过证据检查的说明。")
        let withClaim = try ReportContents.decode(paperDraft(overrides: [
            "reader_explanation": [:], "essence": ""
        ]), topicID: "reader").papers[0]
        #expect(withClaim.preview.titleKey == "paper.preview_summary")
        #expect(withClaim.preview.text == "结果 42%")
    }

    @Test func chapterMenuContainsOnlyTheExistingPublicSections() throws {
        let contents = try ReportContents.decode(paperDraft(), topicID: "reader")
        #expect(contents.papers[0].readingSections.map(\.id) == [.paragraph("thesis"), .paragraph("method"), .evidence])
        #expect(contents.papers[1].readingSections.map(\.id) == [.paragraph("method"), .evidence])
        let withFigure = try ReportContents.decode(paperDraft(overrides: ["figures": [[
            "relative_path": "figures/pixel.png", "caption": "Safe figure", "renderable": true
        ]]]), topicID: "reader").papers[0]
        #expect(withFigure.readingSections.map(\.id) == [.paragraph("thesis"), .paragraph("method"), .figures, .evidence])
        #expect(Set(withFigure.readingSections.map(\.id)).count == withFigure.readingSections.count)
    }
}

@MainActor struct ReportReadingNavigationTests {
    @Test func deliveryIsReportLevelAndNeverInterruptsPaperSelection() async throws {
        let fixture = try ReaderFixture()
        defer { task3Trash(fixture.workspaceRoot) }
        try paperDraft().write(to: URL(fileURLWithPath: fixture.report.articleDraftPath))
        let report = fixture.report
        let browser = ReportBrowserModel()
        await browser.load(report: report, workspaceRoot: fixture.workspaceRoot)
        var fold = ReportDeliveryDisclosureState(snapshot: .init(reportID: report.id, wechat: .failed, email: .notRequested))
        fold.isExpanded = false
        #expect(browser.showsDelivery)
        browser.openPaper(1)
        #expect(!browser.showsDelivery)
        #expect(browser.selectedPaper?.title == "Paper B")
        browser.openPaper(0)
        #expect(browser.selectedPaper?.title == "第一篇 Paper A")
        browser.page = .fullReport
        #expect(!browser.showsDelivery)
        browser.back()
        #expect(browser.showsDelivery)
        fold.update(.init(reportID: report.id, wechat: .failed, email: .notRequested))
        #expect(!fold.isExpanded)
        fold.update(.init(reportID: report.id, wechat: .failed, email: .unknown))
        #expect(fold.isExpanded)
        #expect(browser.page == .overview)
    }
}
