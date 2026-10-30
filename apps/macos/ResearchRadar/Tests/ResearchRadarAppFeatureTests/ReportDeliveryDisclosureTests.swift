import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@Suite struct ReportDeliveryDisclosureTests {
    private let reportID = UUID(uuidString: "20261025-0000-4000-8000-000000000001")!

    @Test func quietReportStartsCollapsedWithIndependentChannelStates() {
        let snapshot = ReportDeliverySnapshot(reportID: reportID, wechat: .created, email: .notRequested)
        let state = ReportDeliveryDisclosureState(snapshot: snapshot)
        #expect(!state.isExpanded)
        #expect(state.snapshot.wechat == .created)
        #expect(state.snapshot.email == .notRequested)
    }

    @Test(arguments: [DeliveryState.pending, .sending, .failed, .unknown])
    func attentionInEitherChannelStartsExpanded(value: DeliveryState) {
        #expect(ReportDeliveryDisclosureState(snapshot: .init(reportID: reportID,
            wechat: value, email: .sent)).isExpanded)
        #expect(ReportDeliveryDisclosureState(snapshot: .init(reportID: reportID,
            wechat: .created, email: value)).isExpanded)
    }

    @Test func manualCollapseSurvivesRefreshButNewAttentionReopensOnce() {
        let pending = ReportDeliverySnapshot(reportID: reportID, wechat: .pending, email: .notRequested)
        var state = ReportDeliveryDisclosureState(snapshot: pending)
        state.isExpanded = false
        state.update(pending)
        #expect(!state.isExpanded)
        let sending = ReportDeliverySnapshot(reportID: reportID, wechat: .sending, email: .notRequested)
        state.update(sending)
        #expect(state.isExpanded)
        state.isExpanded = false
        state.update(sending)
        #expect(!state.isExpanded)
        state.update(.init(reportID: reportID, wechat: .unknown, email: .notRequested))
        #expect(state.isExpanded)
    }

    @Test func otherChannelsSuccessDoesNotReopenAcknowledgedAttention() {
        var state = ReportDeliveryDisclosureState(snapshot: .init(reportID: reportID,
            wechat: .pending, email: .failed))
        state.isExpanded = false
        state.update(.init(reportID: reportID, wechat: .created, email: .failed))
        #expect(!state.isExpanded)
        #expect(state.snapshot.email == .failed)
    }

    @Test func switchingReportResetsPreferenceButSameReportPreservesIt() {
        let quiet = ReportDeliverySnapshot(reportID: reportID, wechat: .created, email: .sent)
        var state = ReportDeliveryDisclosureState(snapshot: quiet)
        state.isExpanded = true
        state.update(quiet)
        #expect(state.isExpanded)
        state.update(.init(reportID: UUID(), wechat: .notRequested, email: .notRequested))
        #expect(!state.isExpanded)
        state.update(.init(reportID: reportID, wechat: .created, email: .unknown))
        #expect(state.isExpanded)
    }

    @Test @MainActor func snapshotUsesExistingChannelProjectionsWithoutCredentialsOrSending() throws {
        let root = URL(fileURLWithPath: "/tmp/unused-delivery-disclosure")
        let report = task3Report(topic: "one", run: root, date: 1)
        let job = try JobRecordV1(kind: .delivery, topicID: "one", reportDate: report.reportDate,
            deliveryChannel: .wechat, trigger: .retry, state: .cancelling,
            jobDirectory: root.appending(path: "job").path, runDirectory: report.runDirectory,
            createdAt: Date())
        let configuration = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
        let snapshot = ReportDeliverySnapshot(report: report, jobs: [job], settings: configuration.delivery, busy: true)
        #expect(snapshot.wechat == .sending)
        #expect(snapshot.email == .notRequested)
        #expect(snapshot.reportID == report.id)
    }

    @Test @MainActor func anotherReportsDeliveryCannotExpandThisReport() throws {
        let root = URL(fileURLWithPath: "/tmp/unused-delivery-disclosure")
        let report = task3Report(topic: "one", run: root, date: 1)
        let job = try JobRecordV1(kind: .delivery, topicID: "two", reportDate: report.reportDate,
            deliveryChannel: .email, trigger: .retry, state: .running,
            jobDirectory: "/tmp/other-job", runDirectory: "/tmp/other-run", createdAt: Date())
        let configuration = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
        let snapshot = ReportDeliverySnapshot(report: report, jobs: [job], settings: configuration.delivery, busy: true)
        #expect(!ReportDeliveryDisclosureState(snapshot: snapshot).isExpanded)
        #expect(snapshot.email == .notRequested)
        #expect(snapshot.wechat == .notRequested)
    }
}
