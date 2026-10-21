import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

actor WeChatRunner: EngineProcessRunning {
    enum Outcome: Sendable { case created, launchFailure, unknown, createdThenCrash }
    let outcome: Outcome
    let hold: Bool
    private(set) var payloads: [RetryDeliveryPayloadV1] = []
    private var release: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?

    init(_ outcome: Outcome = .created, hold: Bool = false) { self.outcome = outcome; self.hold = hold }

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let index = try #require(arguments.firstIndex(of: "--request"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf:
            URL(fileURLWithPath: arguments[index + 1])))
        guard case .retryDelivery(let payload) = request.payload else {
            throw EngineProtocolError.commandPayloadMismatch
        }
        payloads.append(payload)
        started?.resume(); started = nil
        if hold { await withCheckedContinuation { release = $0 } }
        #expect(payload.channel == .wechat)
        if outcome == .launchFailure { throw EngineSupervisorError.launchFailed }
        if outcome == .created || outcome == .createdThenCrash {
            let resultIndex = try #require(arguments.firstIndex(of: "--result"))
            let result = EngineResultV1(requestID: request.requestID, command: .retryDelivery,
                status: .succeeded, completedAt: Date(), delivery: .init(
                    runDirectory: payload.runDirectory, channel: .wechat, status: .created, completedAt: Date()))
            try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[resultIndex + 1]))
        }
        return .init(exitCode: outcome == .created ? 0 : 1, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
    func waitForStart() async {
        if payloads.isEmpty { await withCheckedContinuation { started = $0 } }
    }
    func finish() { release?.resume(); release = nil }
}

@MainActor @Suite struct WeChatDeliveryTests {
    @Test func firstManualDraftAddsOnlyItsChannelAndSurvivesRestart() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = WeChatRunner()
        let store = fixture.store(runner)
        let html = try Data(contentsOf: URL(fileURLWithPath: fixture.report.reportHTMLPath))
        let confirmation = try store.prepareWeChatDraft(reportID: fixture.report.id)
        #expect(store.jobs.isEmpty)
        #expect(confirmation.settings.thumbMediaID == "offline-cover")
        #expect(!confirmation.allowResend)
        await store.createWeChatDraft(confirmation)
        #expect(store.jobs.count == 1)
        #expect(store.jobs.first?.state == .succeeded)
        #expect(store.reports[0].deliveries.first { $0.channel == .wechat }?.state == .created)
        #expect(store.reports[0].deliveries.first { $0.channel == .email }?.state == .sent)
        #expect(try Data(contentsOf: URL(fileURLWithPath: fixture.report.reportHTMLPath)) == html)
        let restarted = try AppBootstrapService(appSupportRoot: fixture.root).load(
            engineURL: URL(fileURLWithPath: "/offline/engine"))
        #expect(restarted.reports[0].deliveries.first { $0.channel == .wechat }?.state == .created)
        #expect(await runner.payloads.count == 1)
        await store.createWeChatDraft(confirmation)
        #expect(store.lastErrorCode == "wechat_confirmation_changed")
        #expect(await runner.payloads.count == 1)
        let repeatConfirmation = try store.prepareWeChatDraft(reportID: fixture.report.id)
        #expect(repeatConfirmation.previouslyCreated)
        #expect(repeatConfirmation.allowResend)
        await store.createWeChatDraft(repeatConfirmation)
        #expect(await runner.payloads.count == 2)
    }

    @Test(arguments: [WeChatRunner.Outcome.launchFailure, .unknown, .createdThenCrash])
    func failuresAndConfirmedSuccessKeepChannelSpecificRetryRules(outcome: WeChatRunner.Outcome) async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = WeChatRunner(outcome)
        let store = fixture.store(runner)
        await store.createWeChatDraft(try store.prepareWeChatDraft(reportID: fixture.report.id))
        let expected: DeliveryState = outcome == .launchFailure ? .failed : outcome == .unknown ? .unknown : .created
        #expect(store.reports[0].deliveries.first { $0.channel == .wechat }?.state == expected)
        #expect(store.reports[0].deliveries.first { $0.channel == .email }?.state == .sent)
        let next = try store.prepareWeChatDraft(reportID: fixture.report.id)
        #expect(next.acknowledgeUnknownOutcome == (outcome == .unknown))
        #expect(next.allowResend == (outcome != .launchFailure))
        #expect(WeChatDraftPresentation(report: store.reports[0], jobs: store.jobs,
            settings: fixture.configuration.delivery.wechat, busy: false).actionKey ==
            (outcome == .launchFailure ? "wechat.retry" : outcome == .unknown ? "wechat.review_create" : "wechat.create_again"))
        await store.createWeChatDraft(next)
        let payload = try #require(await runner.payloads.last)
        #expect(payload.acknowledgeUnknownOutcome == (outcome == .unknown))
        #expect(payload.allowResend == (outcome != .launchFailure))
    }

    @Test(arguments: [false, true])
    func changedCoverOrCredentialsInvalidateConfirmationBeforeAnyJob(credentialsOnly: Bool) async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = WeChatRunner()
        let store = fixture.store(runner)
        let confirmation = try store.prepareWeChatDraft(reportID: fixture.report.id)
        try store.configureWeChat(enabled: true, author: "Offline author",
            thumbMediaID: credentialsOnly ? "offline-cover" : "other-cover",
            appID: credentialsOnly ? "offline-replacement" : "", appSecret: "")
        await store.createWeChatDraft(confirmation)
        #expect(store.lastErrorCode == "wechat_confirmation_changed")
        #expect(store.jobs.isEmpty)
        #expect(await runner.payloads.isEmpty)
    }

    @Test(arguments: ["wechat.app_id", "wechat.app_secret", "denied"])
    func missingOrDeniedMetadataNeverLaunchesOrReadsValues(missing: String) throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let store = fixture.store(WeChatRunner(), secrets: WeChatMetadataSecrets(missing: missing))
        #expect(throws: WeChatDraftActionError.self) { try store.prepareWeChatDraft(reportID: fixture.report.id) }
        #expect(store.jobs.isEmpty)
    }

    @Test func disabledOrMissingCoverAndEmptyReportCannotBeSubmitted() throws {
        var fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        fixture.configuration.delivery.wechat.thumbMediaID = " "
        let store = fixture.store(WeChatRunner())
        #expect(throws: WeChatDraftActionError.blocked("wechat.configure_first")) {
            try store.prepareWeChatDraft(reportID: fixture.report.id)
        }
        let settings = WeChatDeliverySettingsV1(enabled: false, thumbMediaID: "cover")
        #expect(WeChatDraftPresentation(report: fixture.report, jobs: [], settings: settings,
            busy: false).blockedReason == "wechat.configure_first")
        let report = fixture.report
        let empty = ReportRecordV1(topicID: report.topicID, reportDate: report.reportDate,
            runDirectory: report.runDirectory, articleDraftPath: report.articleDraftPath,
            reportHTMLPath: report.reportHTMLPath, title: report.title, summary: "", sourceCount: 0,
            deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: report.createdAt)
        #expect(WeChatDraftPresentation(report: empty, jobs: [], settings: settings,
            busy: false).blockedReason == "wechat.no_public_report")
    }

    @Test func simultaneousConfirmationsCannotDuplicateAndBusyPreventsConfigEdits() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = WeChatRunner(hold: true)
        let store = fixture.store(runner)
        let confirmation = try store.prepareWeChatDraft(reportID: fixture.report.id)
        let creating = Task { await store.createWeChatDraft(confirmation) }
        await runner.waitForStart()
        await store.createWeChatDraft(confirmation)
        #expect(store.jobs.count == 1)
        #expect(await runner.payloads.count == 1)
        #expect(throws: (any Error).self) {
            try store.configureWeChat(enabled: true, author: "Other", thumbMediaID: "other", appID: "", appSecret: "")
        }
        await runner.finish()
        await creating.value
        #expect(!store.behaviorChangesBlocked)
    }

    @Test func crashBeforeChannelIndexWriteRecoversUnknownWithoutAutoRetry() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let job = try JobRecordV1(kind: .delivery, topicID: "memory", reportDate: fixture.report.reportDate,
            deliveryChannel: .wechat, trigger: .retry, state: .running,
            jobDirectory: fixture.root.appending(path: "jobs/interrupted").path,
            runDirectory: fixture.report.runDirectory, createdAt: Date(), startedAt: Date())
        try FileManager.default.createDirectory(atPath: job.jobDirectory, withIntermediateDirectories: true)
        try AtomicJSONStore(root: fixture.root).write(JobQueueSnapshotV1(jobs: [job]), to: "state/queue.json")
        let runner = WeChatRunner()
        let store = fixture.store(runner, jobs: [job])
        await store.reconcileAfterLaunch(resumePending: false)
        #expect(!store.requiresReconciliation)
        #expect(store.jobs[0].state == .deliveryUnknown)
        #expect(store.reports[0].deliveries.first { $0.channel == .wechat }?.state == .unknown)
        #expect(store.reports[0].deliveries.first { $0.channel == .email }?.state == .sent)
        #expect(try store.prepareWeChatDraft(reportID: fixture.report.id).acknowledgeUnknownOutcome)
        #expect(await runner.payloads.isEmpty)
    }

    @Test func queueWriteFailureDoesNotLaunchOrCreateAutomaticWork() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = WeChatRunner()
        let store = fixture.store(runner)
        let confirmation = try store.prepareWeChatDraft(reportID: fixture.report.id)
        try FileManager.default.createDirectory(at: fixture.root.appending(path: "state/queue.json"), withIntermediateDirectories: false)
        await store.createWeChatDraft(confirmation)
        #expect(store.jobs.isEmpty)
        #expect(await runner.payloads.isEmpty)
        #expect(!store.reports[0].deliveries.contains { $0.channel == .wechat })
        #expect(store.lastErrorCode == "delivery_retry_blocked")
    }

    @Test func priorSuccessAndUnknownBothRemainVisibleInConfirmation() throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let jobs = try [JobState.succeeded, .deliveryUnknown].map { state in
            try JobRecordV1(kind: .delivery, topicID: "memory", reportDate: fixture.report.reportDate,
                deliveryChannel: .wechat, trigger: .retry, state: state,
                jobDirectory: fixture.root.appending(path: "jobs/\(UUID())").path,
                runDirectory: fixture.report.runDirectory, createdAt: Date())
        }
        let confirmation = try fixture.store(WeChatRunner(), jobs: jobs).prepareWeChatDraft(reportID: fixture.report.id)
        #expect(confirmation.previouslyCreated)
        #expect(confirmation.acknowledgeUnknownOutcome)
        #expect(confirmation.allowResend)
    }

    @Test func viewsRenderInBothLanguagesWithoutReadingSecretsOrDispatching() async throws {
        _ = NSApplication.shared
        var fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = WeChatRunner()
        for language in [AppLanguagePreference.english, .simplifiedChinese] {
            let localization = LocalizationStore(preference: language)
            for state in [DeliveryState.notRequested, .failed, .unknown, .created] {
                fixture.report.deliveries = [.init(channel: .email, state: .sent), .init(channel: .wechat, state: state)]
                let store = fixture.store(runner)
                let confirmation = try store.prepareWeChatDraft(reportID: fixture.report.id)
                try await snapshot(ReportWeChatView(store: store, report: fixture.report, localization: localization,
                    configure: {}), name: "controls-\(language.rawValue)-\(state.rawValue)", width: 620,
                    dark: language == .simplifiedChinese)
                try await snapshot(WeChatDraftConfirmationView(confirmation: confirmation, localization: localization,
                    cancel: {}, create: { Issue.record("Rendering must not create a draft") }),
                    name: "confirmation-\(language.rawValue)-\(state.rawValue)", width: 460,
                    dark: language == .simplifiedChinese)
                for key in ["wechat.create", "wechat.confirm_title", "wechat.unknown_warning", "wechat.duplicate_warning"] {
                    #expect(localization.text(key) != key)
                }
                #expect(store.jobs.isEmpty)
            }
        }
        #expect(await runner.payloads.isEmpty)
    }

    private func snapshot<Content: View>(_ view: Content, name: String, width: CGFloat, dark: Bool) async throws {
        let host = NSHostingView(rootView: view.background(.background)
            .environment(\.colorScheme, dark ? .dark : .light))
        host.frame = NSRect(x: 0, y: 0, width: width, height: 360)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        window.contentView = host
        defer { window.orderOut(nil); window.close() }
        host.layoutSubtreeIfNeeded()
        #expect(host.fittingSize.height > 0)
        guard let path = ProcessInfo.processInfo.environment["RESEARCH_RADAR_WECHAT_EVIDENCE_ROOT"] else { return }
        let root = URL(fileURLWithPath: path, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        window.orderBack(nil)
        try await Task.sleep(for: .milliseconds(100))
        host.layoutSubtreeIfNeeded()
        let bitmap = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        window.appearance?.performAsCurrentDrawingAppearance {
            host.cacheDisplay(in: host.bounds, to: bitmap)
        }
        try #require(bitmap.representation(using: .png, properties: [:]))
            .write(to: root.appending(path: "\(name).png"), options: .atomic)
    }
}

private struct WeChatMetadataSecrets: SecretStoring {
    let missing: String
    func contains(account: String) throws -> Bool {
        if missing == "denied" { throw KeychainStoreError.invalidAccount }
        return account != missing
    }
    func read(account: String) throws -> Data? { Issue.record("Must not read credential values"); return nil }
    func set(_ value: Data, account: String) throws { Issue.record("Must not write credentials") }
    func remove(account: String) throws { Issue.record("Must not remove credentials") }
}

@MainActor struct WeChatFixture {
    let root: URL
    var configuration: AppConfigurationV1
    var report: ReportRecordV1

    init() throws {
        root = FileManager.default.temporaryDirectory.appending(path: "wechat-entry-\(UUID())")
            .resolvingSymlinksInPath()
        let run = root.appending(path: "workspace/runs/offline")
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700])
        let html = run.appending(path: "wechat.html")
        let draft = run.appending(path: "article_draft.json")
        try Data("<meta charset='utf-8'><p>离线报告 Offline report</p>".utf8).write(to: html)
        try Data("{\"topic_id\":\"memory\"}".utf8).write(to: draft)
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.topics = [.init(id: "memory", displayName: "Memory", researchFocus: "Agent memory",
            queries: ["agent memory"], paperQueries: ["memory evaluation"], reportLanguage: .chinese)]
        config.delivery.wechat = .init(enabled: true, author: "Offline author", thumbMediaID: "offline-cover")
        configuration = config
        report = .init(topicID: "memory", reportDate: "2026-10-20", runDirectory: run.path,
            articleDraftPath: draft.path, reportHTMLPath: html.path, title: "离线报告 Offline report", summary: "",
            sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1,
            deliveries: [.init(channel: .email, state: .sent)], createdAt: Date())
        let disk = AtomicJSONStore(root: root)
        try disk.write(config, to: "config/app-config.json")
        try disk.write(ReportIndexV1(reports: [report]), to: "state/report-index.json")
        try disk.write(AppRuntimeStateV1(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            to: "state/app-state.json")
    }

    func store(_ runner: any EngineProcessRunning, secrets: any SecretStoring = AdmissionSecrets(),
               jobs: [JobRecordV1] = []) -> AppStore {
        AppStore(configuration: configuration, queueSnapshot: .init(jobs: jobs), reportSnapshot: .init(reports: [report]),
            runtime: .init(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: root, engineURL: URL(fileURLWithPath: "/offline/engine"), runner: runner, secretStore: secrets)
    }

    func cleanup() {
        do {
            let trash = Process()
            trash.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
            trash.arguments = [root.path]
            try trash.run(); trash.waitUntilExit()
            #expect(trash.terminationStatus == 0)
        } catch { Issue.record("Could not move WeChat fixture to Trash: \(error)") }
    }
}
