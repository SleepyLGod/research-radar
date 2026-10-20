import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

actor EmailRunner: EngineProcessRunning {
    enum Outcome: Sendable { case sent, launchFailure, unknown, sentThenCrash }
    let outcome: Outcome
    let hold: Bool
    private(set) var payloads: [RetryDeliveryPayloadV1] = []
    private var release: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?

    init(_ outcome: Outcome = .sent, hold: Bool = false) { self.outcome = outcome; self.hold = hold }

    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        let requestIndex = try #require(arguments.firstIndex(of: "--request"))
        let request = try EngineProtocolCodec.decodeRequest(
            Data(contentsOf: URL(fileURLWithPath: arguments[requestIndex + 1])))
        guard case .retryDelivery(let payload) = request.payload else {
            throw EngineProtocolError.commandPayloadMismatch
        }
        payloads.append(payload)
        started?.resume(); started = nil
        if hold { await withCheckedContinuation { release = $0 } }
        #expect(payload.channel == .email)
        if outcome == .launchFailure { throw EngineSupervisorError.launchFailed }
        if outcome == .sent || outcome == .sentThenCrash {
            let resultIndex = try #require(arguments.firstIndex(of: "--result"))
            let result = EngineResultV1(requestID: request.requestID, command: .retryDelivery,
                status: .succeeded, completedAt: Date(), delivery: .init(
                    runDirectory: payload.runDirectory, channel: .email, status: .sent, completedAt: Date()))
            try EngineProtocolCodec.encode(result).write(to: URL(fileURLWithPath: arguments[resultIndex + 1]))
        }
        return EngineProcessOutcome(exitCode: outcome == .sent ? 0 : 1, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
    func waitForStart() async {
        if payloads.isEmpty { await withCheckedContinuation { started = $0 } }
    }
    func finish() { release?.resume(); release = nil }
}

@MainActor
@Suite struct EmailDeliveryTests {
    @Test func firstManualSendUsesExistingQueueAndSurvivesRestart() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner()
        let store = fixture.store(runner)
        let report = fixture.report
        let html = try Data(contentsOf: URL(fileURLWithPath: report.reportHTMLPath))
        let confirmation = try store.prepareEmailDelivery(reportID: report.id)
        #expect(confirmation.settings.toAddress == "reader@example.invalid")
        #expect(await runner.payloads.isEmpty)
        await store.sendEmail(confirmation)
        #expect(await runner.payloads.count == 1)
        #expect(store.jobs.count == 1)
        #expect(store.jobs[0].kind == .delivery)
        #expect(store.jobs[0].state == .succeeded)
        #expect(store.reports[0].deliveries.first { $0.channel == .email }?.state == .sent)
        #expect(store.reports[0].deliveries.first { $0.channel == .wechat }?.state == .created)
        #expect(try Data(contentsOf: URL(fileURLWithPath: report.reportHTMLPath)) == html)
        let restarted = try AppBootstrapService(appSupportRoot: fixture.root).load(engineURL: URL(fileURLWithPath: "/offline/engine"))
        #expect(restarted.reports[0].deliveries.first { $0.channel == .email }?.state == .sent)
        await store.sendEmail(confirmation)
        #expect(await runner.payloads.count == 1)
        #expect(store.lastErrorCode == "email_confirmation_changed")
        let resend = try store.prepareEmailDelivery(reportID: report.id)
        #expect(resend.allowResend)
        #expect(!resend.acknowledgeUnknownOutcome)
        await store.sendEmail(resend)
        #expect(await runner.payloads.count == 2)
    }

    @Test(arguments: [EmailRunner.Outcome.launchFailure, .unknown, .sentThenCrash])
    func outcomeControlsRetryAndProtectsUncertainSends(outcome: EmailRunner.Outcome) async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner(outcome)
        let store = fixture.store(runner)
        await store.sendEmail(try store.prepareEmailDelivery(reportID: fixture.report.id))
        let expected: DeliveryState = outcome == .launchFailure ? .failed : outcome == .unknown ? .unknown : .sent
        #expect(store.reports[0].deliveries.first { $0.channel == .email }?.state == expected)
        #expect(store.reports[0].isEffectiveDeepReport)
        let restarted = try AppBootstrapService(appSupportRoot: fixture.root).load(engineURL: URL(fileURLWithPath: "/offline/engine"))
        let restored = fixture.store(runner, jobs: restarted.jobs, reports: restarted.reports)
        let retry = try restored.prepareEmailDelivery(reportID: fixture.report.id)
        #expect(retry.acknowledgeUnknownOutcome == (outcome == .unknown))
        #expect(retry.allowResend == (outcome != .launchFailure))
        #expect(await runner.payloads.count == 1)
    }

    @Test func changedRecipientInvalidatesConfirmationWithoutLaunching() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner()
        let store = fixture.store(runner)
        let confirmation = try store.prepareEmailDelivery(reportID: fixture.report.id)
        try store.configureEmail(enabled: true, host: "smtp.invalid", port: 465, security: .tls,
            username: "sender@example.invalid", password: "", from: "sender@example.invalid", to: "other@example.invalid")
        await store.sendEmail(confirmation)
        #expect(await runner.payloads.isEmpty)
        #expect(store.jobs.isEmpty)
        #expect(store.lastErrorCode == "email_confirmation_changed")
    }

    @Test(arguments: [false, true]) func missingOrDeniedCredentialNeverStartsEngine(denied: Bool) throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let store = fixture.store(EmailRunner(), secrets: AdmissionSecrets(present: false, denied: denied))
        #expect(throws: EmailDeliveryActionError.self) {
            try store.prepareEmailDelivery(reportID: fixture.report.id)
        }
        #expect(store.jobs.isEmpty)
    }

    @Test func presentationScopesStateAndConfirmationToEmail() throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let view = EmailDeliveryPresentation(report: fixture.report, jobs: [],
            settings: fixture.configuration.delivery.email, busy: false)
        #expect(view.state == .notRequested)
        #expect(view.actionKey == "email.send")
        #expect(view.blockedReason == nil)
        var empty = fixture.report
        empty = ReportRecordV1(topicID: empty.topicID, reportDate: empty.reportDate,
            runDirectory: empty.runDirectory, articleDraftPath: empty.articleDraftPath,
            reportHTMLPath: empty.reportHTMLPath, title: empty.title, summary: "", sourceCount: 0,
            deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: empty.createdAt)
        #expect(EmailDeliveryPresentation(report: empty, jobs: [], settings: fixture.configuration.delivery.email,
            busy: false).blockedReason == "email.no_public_report")
        #expect(EmailDeliveryPresentation(report: fixture.report, jobs: [],
            settings: .init(), busy: false).blockedReason == "email.configure_first")
    }

    @Test func repeatedConfirmationWhileSendingDoesNotStartAnotherJob() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner(hold: true)
        let store = fixture.store(runner)
        let confirmation = try store.prepareEmailDelivery(reportID: fixture.report.id)
        let sending = Task { await store.sendEmail(confirmation) }
        await runner.waitForStart()
        await store.sendEmail(confirmation)
        #expect(await runner.payloads.count == 1)
        #expect(store.jobs.count == 1)
        #expect(throws: (any Error).self) {
            try store.configureEmail(enabled: true, host: "smtp.invalid", port: 465, security: .tls,
                username: "sender@example.invalid", password: "", from: "sender@example.invalid", to: "other@example.invalid")
        }
        await runner.finish()
        await sending.value
        #expect(store.jobs[0].state == .succeeded)
    }

    @Test func observedSendReadinessReturnsToIdleWithoutReopeningTheView() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner(hold: true)
        let store = fixture.store(runner)
        let observations = EmailReadinessObservations()
        let host = NSHostingView(rootView: EmailReadinessProbe(store: store, observations: observations))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 100),
            styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.orderBack(nil)
        defer { window.orderOut(nil); window.close() }
        try await Task.sleep(for: .milliseconds(100))
        #expect(observations.values.last == false)
        let confirmation = try store.prepareEmailDelivery(reportID: fixture.report.id)
        let sending = Task { await store.sendEmail(confirmation) }
        await runner.waitForStart()
        try await Task.sleep(for: .milliseconds(100))
        #expect(observations.values.last == true)
        await runner.finish()
        await sending.value
        try await Task.sleep(for: .milliseconds(200))
        #expect(!store.behaviorChangesBlocked)
        #expect(observations.values.last == false)
    }

    @Test func queueWriteFailureNeverLaunchesOrAddsAnAutomaticDelivery() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner()
        let store = fixture.store(runner)
        let confirmation = try store.prepareEmailDelivery(reportID: fixture.report.id)
        try FileManager.default.createDirectory(at: fixture.root.appending(path: "state/queue.json"),
            withIntermediateDirectories: false)
        await store.sendEmail(confirmation)
        #expect(await runner.payloads.isEmpty)
        #expect(store.jobs.isEmpty)
        #expect(!store.reports[0].deliveries.contains { $0.channel == .email })
        #expect(store.lastErrorCode == "delivery_retry_blocked")
    }

    @Test func priorUnknownAndSuccessRequireBothAcknowledgements() throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let jobs = try [JobState.succeeded, .deliveryUnknown].map { state in
            try JobRecordV1(kind: .delivery, topicID: fixture.report.topicID,
                reportDate: fixture.report.reportDate, deliveryChannel: .email, trigger: .retry,
                state: state, jobDirectory: fixture.root.appending(path: "jobs/\(UUID())").path,
                runDirectory: fixture.report.runDirectory, createdAt: Date())
        }
        let store = fixture.store(EmailRunner(), jobs: jobs)
        let confirmation = try store.prepareEmailDelivery(reportID: fixture.report.id)
        #expect(confirmation.allowResend)
        #expect(confirmation.acknowledgeUnknownOutcome)
    }

    @Test func crashBeforeFirstEmailRecordCanReconcileAndRequestExplicitRetry() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner()
        let job = try JobRecordV1(kind: .delivery, topicID: fixture.report.topicID,
            reportDate: fixture.report.reportDate, deliveryChannel: .email, trigger: .retry,
            state: .running, jobDirectory: fixture.root.appending(path: "jobs/interrupted").path,
            runDirectory: fixture.report.runDirectory, createdAt: Date(), startedAt: Date())
        try FileManager.default.createDirectory(atPath: job.jobDirectory, withIntermediateDirectories: true)
        try AtomicJSONStore(root: fixture.root).write(JobQueueSnapshotV1(jobs: [job]), to: "state/queue.json")
        let store = fixture.store(runner, jobs: [job])
        await store.reconcileAfterLaunch(resumePending: false)
        #expect(!store.requiresReconciliation)
        #expect(store.jobs[0].state == .deliveryUnknown)
        #expect(store.reports[0].deliveries.first { $0.channel == .email }?.state == .unknown)
        #expect(await runner.payloads.isEmpty)
        let confirmation = try store.prepareEmailDelivery(reportID: fixture.report.id)
        #expect(confirmation.allowResend)
        #expect(confirmation.acknowledgeUnknownOutcome)
        await store.reconcileAfterLaunch(resumePending: false)
        #expect(!store.requiresReconciliation)
    }

    @Test func emailViewsLayOutInBothLanguagesWithoutReadingSecretsOrSending() async throws {
        let fixture = try EmailFixture()
        defer { fixture.cleanup() }
        let runner = EmailRunner()
        for language in [AppLanguagePreference.english, .simplifiedChinese] {
            let chinese = language == .simplifiedChinese
            let localization = LocalizationStore(preference: language)
            for state in [DeliveryState.notRequested, .failed, .unknown, .sent] {
                var report = fixture.report
                report.deliveries.append(.init(channel: .email, state: state))
                let store = fixture.store(runner, reports: [report])
                let controls = ReportEmailView(store: store, report: report, localization: localization, configure: {})
                try await snapshot(controls, name: "controls-\(language.rawValue)-\(state.rawValue)",
                    width: 650, dark: chinese)
                let confirmation = try store.prepareEmailDelivery(reportID: report.id)
                try await snapshot(EmailSendConfirmationView(confirmation: confirmation, localization: localization,
                    cancel: {}, send: {}), name: "confirmation-\(language.rawValue)-\(state.rawValue)",
                    width: 460, dark: chinese)
                for key in ["email.send", "email.confirm_title", "email.unknown_warning", "email.resend_warning"] {
                    #expect(localization.text(key) != key)
                }
                #expect(store.jobs.isEmpty)
            }
        }
        #expect(await runner.payloads.isEmpty)
    }

    private func snapshot<Content: View>(_ view: Content, name: String, width: CGFloat, dark: Bool) async throws {
        let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        let host = NSHostingView(rootView: view.background(.background)
            .environment(\.colorScheme, dark ? .dark : .light))
        host.appearance = appearance
        host.frame = NSRect(x: 0, y: 0, width: width, height: 340)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = appearance
        window.contentView = host
        defer { window.orderOut(nil); window.close() }
        host.layoutSubtreeIfNeeded()
        #expect(host.fittingSize.height > 0)
        guard let path = ProcessInfo.processInfo.environment["RESEARCH_RADAR_EMAIL_EVIDENCE_ROOT"] else { return }
        let output = URL(fileURLWithPath: path, isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        window.orderBack(nil)
        try await Task.sleep(for: .milliseconds(100))
        host.layoutSubtreeIfNeeded()
        let bitmap = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        appearance?.performAsCurrentDrawingAppearance {
            host.cacheDisplay(in: host.bounds, to: bitmap)
        }
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        try png.write(to: output.appending(path: "\(name).png"), options: .atomic)
    }
}

@MainActor private final class EmailReadinessObservations {
    var values: [Bool] = []
}

private struct EmailReadinessProbe: View {
    let store: AppStore
    let observations: EmailReadinessObservations
    var body: some View {
        let blocked = store.behaviorChangesBlocked
        let _ = observations.values.append(blocked)
        Text(blocked ? "Busy" : "Ready")
    }
}

@MainActor
private struct EmailFixture {
    let root: URL
    let configuration: AppConfigurationV1
    let report: ReportRecordV1

    init() throws {
        root = FileManager.default.temporaryDirectory.appending(path: "email-entry-\(UUID().uuidString)")
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
        config.delivery.email = .init(enabled: true, smtpHost: "smtp.invalid", username: "sender@example.invalid",
            fromAddress: "sender@example.invalid", toAddress: "reader@example.invalid")
        configuration = config
        report = ReportRecordV1(topicID: "memory", reportDate: "2026-10-20", runDirectory: run.path,
            articleDraftPath: draft.path, reportHTMLPath: html.path, title: "Offline report", summary: "",
            sourceCount: 1, deepReadCount: 1, publishableClaimCount: 1,
            deliveries: [.init(channel: .wechat, state: .created)], createdAt: Date())
        let disk = AtomicJSONStore(root: root)
        try disk.write(config, to: "config/app-config.json")
        try disk.write(ReportIndexV1(reports: [report]), to: "state/report-index.json")
        try disk.write(AppRuntimeStateV1(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            to: "state/app-state.json")
    }

    func store(_ runner: EmailRunner, secrets: any SecretStoring = AdmissionSecrets(),
               jobs: [JobRecordV1] = [], reports: [ReportRecordV1]? = nil) -> AppStore {
        AppStore(configuration: configuration, queueSnapshot: .init(jobs: jobs), reportSnapshot: .init(reports: reports ?? [report]),
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
        } catch { Issue.record("Could not move email fixture to Trash: \(error)") }
    }
}
