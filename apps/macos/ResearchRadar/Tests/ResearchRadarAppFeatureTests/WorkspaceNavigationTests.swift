import AppKit
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct WorkspaceNavigationTests {
    @Test func navigationRetainsEditPageSelection() {
        var navigation = WorkspaceNavigation()
        for section in [WorkspaceSection.topics, .settings] {
            navigation.section = section
            #expect(navigation.section == section)
        }
        for section in [WorkspaceSection.overview, .reports, .diagnostics] {
            navigation.section = section
        }
        navigation.openReport(UUID())
        #expect(navigation.isReading)
    }

    @Test func navigationBackKeepsReportSelection() {
        var navigation = WorkspaceNavigation()
        let id = UUID()
        navigation.openReport(id)
        #expect(navigation.section == .reports)
        #expect(navigation.reportID == id)
        navigation.showReportList()
        #expect(!navigation.isReading)
        #expect(navigation.reportID == id)
        navigation.openReport(id)
        #expect(navigation.isReading)
    }

    @Test func changingSectionCannotLeaveReaderVisible() {
        var navigation = WorkspaceNavigation()
        navigation.openReport(UUID())
        navigation.section = .settings
        #expect(!navigation.isReading)
        #expect(navigation.reportID != nil)
    }
}
