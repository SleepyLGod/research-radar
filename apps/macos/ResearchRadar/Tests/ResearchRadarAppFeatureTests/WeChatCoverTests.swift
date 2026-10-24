import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

actor CoverRunner: EngineProcessRunning {
    enum Outcome: Sendable { case uploaded, unknown, mismatched }
    let outcome: Outcome
    let afterResult: (@Sendable () throws -> Void)?
    let hold: Bool
    private(set) var calls = 0
    private var release: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?
    init(_ outcome: Outcome = .uploaded, hold: Bool = false, afterResult: (@Sendable () throws -> Void)? = nil) {
        self.outcome = outcome; self.afterResult = afterResult; self.hold = hold
    }
    func cancel() async { release?.resume(); release = nil }
    func waitForStart() async { if calls == 0 { await withCheckedContinuation { started = $0 } } }
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        calls += 1
        started?.resume(); started = nil
        if hold { await withCheckedContinuation { release = $0 } }
        let path = try #require(arguments.firstIndex(of: "--request"))
        let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: URL(fileURLWithPath: arguments[path + 1])))
        guard case .uploadWeChatCover(let payload) = request.payload else {
            Issue.record("Cover upload must not invoke daily or draft delivery")
            throw EngineProtocolError.commandPayloadMismatch
        }
        let data = try Data(contentsOf: URL(fileURLWithPath: payload.imagePath))
        #expect(data == coverPNG())
        #expect(URL(fileURLWithPath: payload.imagePath).deletingLastPathComponent() == eventsURL.deletingLastPathComponent())
        if outcome != .unknown {
            let result = EngineResultV1(requestID: request.requestID, command: .uploadWeChatCover,
                status: .succeeded, completedAt: Date(),
                cover: WeChatCoverResultV1(mediaID: "offline-cover-new",
                    imageSHA256: outcome == .mismatched ? String(repeating: "0", count: 64) : payload.imageSHA256))
            try EngineProtocolCodec.encode(result).write(to: eventsURL.deletingLastPathComponent().appending(path: "result.json"))
            try afterResult?()
        }
        return .init(exitCode: outcome == .uploaded ? 0 : 1, startedProcessGroup: nil,
            standardOutput: Data(), standardError: Data())
    }
}

@MainActor @Suite struct WeChatCoverTests {
    @Test(.enabled(if: ProcessInfo.processInfo.environment["RESEARCH_RADAR_OFFLINE_ENGINE"] != nil))
    func frozenCoverUploadUsesProductionBridgeWithoutChangingReportsOrQueue() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let engine = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["RESEARCH_RADAR_OFFLINE_ENGINE"]))
        let store = AppStore(configuration: fixture.configuration, reportSnapshot: .init(reports: [fixture.report]),
            runtime: .init(onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()),
            appSupportRoot: fixture.root, engineURL: engine, runner: EngineProcessSupervisor(), secretStore: AdmissionSecrets())
        let html = try Data(contentsOf: URL(fileURLWithPath: fixture.report.reportHTMLPath))
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "frozen-cover.png"))
        await store.uploadWeChatCover(try store.prepareWeChatCoverUpload())
        if store.coverUploadReceipt == nil {
            for directory in try FileManager.default.contentsOfDirectory(at: fixture.root.appending(path: "jobs"),
                includingPropertiesForKeys: nil) {
                let error = directory.appending(path: "error.json")
                if FileManager.default.fileExists(atPath: error.path) {
                    print("Offline cover terminal: \(String(decoding: try Data(contentsOf: error), as: UTF8.self))")
                }
            }
        }
        #expect(store.coverUploadReceipt?.mediaID == "offline-cover-id")
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover-id")
        #expect(store.jobs.isEmpty)
        #expect(store.reports == [fixture.report])
        #expect(try Data(contentsOf: URL(fileURLWithPath: fixture.report.reportHTMLPath)) == html)
    }

    @Test func selectedImageDoesNotReadSecretsOrStartJobsAndUploadPersistsOnlyCover() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner()
        let store = fixture.store(runner)
        let selected = try WeChatCoverImage(data: coverPNG(), filename: "chosen.png")
        try store.selectWeChatCover(selected)
        let confirmation = try store.prepareWeChatCoverUpload()
        #expect(await runner.calls == 0)
        #expect(store.jobs.isEmpty)
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover")
        await store.uploadWeChatCover(confirmation)
        #expect(await runner.calls == 1)
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover-new")
        #expect(store.coverUploadReceipt?.mediaID == "offline-cover-new")
        #expect(store.jobs.isEmpty)
        #expect(store.reports == [fixture.report])
        let saved = try AtomicJSONStore(root: fixture.root).read(AppConfigurationV1.self, from: "config/app-config.json")
        #expect(saved.delivery.wechat.thumbMediaID == "offline-cover-new")
        await store.uploadWeChatCover(confirmation)
        #expect(await runner.calls == 1)
    }

    @Test func changedSelectionInvalidatesConfirmation() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner()
        let store = fixture.store(runner)
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "first.png"))
        let old = try store.prepareWeChatCoverUpload()
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "second.png"))
        await store.uploadWeChatCover(old)
        #expect(await runner.calls == 0)
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover")
    }

    @Test(arguments: [CoverRunner.Outcome.unknown, .mismatched])
    func unknownUploadPreservesOldCoverAndDoesNotRetry(outcome: CoverRunner.Outcome) async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner(outcome)
        let store = fixture.store(runner)
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "chosen.png"))
        await store.uploadWeChatCover(try store.prepareWeChatCoverUpload())
        #expect(await runner.calls == 1)
        #expect(store.coverUploadUncertain)
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover")
        #expect(store.coverUploadReceipt == nil)
        #expect(store.jobs.isEmpty)
    }

    @Test func successfulUploadCanRetryOnlyLocalSaveAfterFailure() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let config = fixture.root.appending(path: "config/app-config.json")
        let backup = fixture.root.appending(path: "config/saved-config.json")
        let runner = CoverRunner(afterResult: {
            try FileManager.default.moveItem(at: config, to: backup)
            try FileManager.default.createDirectory(at: config, withIntermediateDirectories: false)
        })
        let store = fixture.store(runner)
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "chosen.png"))
        await store.uploadWeChatCover(try store.prepareWeChatCoverUpload())
        #expect(store.coverUploadReceipt?.mediaID == "offline-cover-new")
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover")
        #expect(store.lastErrorCode == "wechat_cover_save_failed")
        try FileManager.default.moveItem(at: config, to: fixture.root.appending(path: "config/write-blocker"))
        try FileManager.default.moveItem(at: backup, to: config)
        try store.saveUploadedWeChatCover()
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover-new")
        #expect(await runner.calls == 1)
    }

    @Test func credentialChangeInvalidatesApprovalWithoutLaunching() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner()
        let store = fixture.store(runner)
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "chosen.png"))
        let old = try store.prepareWeChatCoverUpload()
        try store.configureWeChat(enabled: true, author: "Offline author", thumbMediaID: "offline-cover",
            appID: "offline-replacement", appSecret: "")
        await store.uploadWeChatCover(old)
        #expect(await runner.calls == 0)
        #expect(store.lastErrorCode == "wechat_confirmation_changed")
    }

    @Test func cancellationAndDuplicateClickCannotStartAnotherUpload() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner(.unknown, hold: true)
        let store = fixture.store(runner)
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "chosen.png"))
        let confirmation = try store.prepareWeChatCoverUpload()
        let uploading = Task { await store.uploadWeChatCover(confirmation) }
        await runner.waitForStart()
        #expect(store.isUploadingWeChatCover)
        await store.uploadWeChatCover(confirmation)
        #expect(await runner.calls == 1)
        await store.cancelActiveJob()
        await uploading.value
        #expect(!store.isEngineRunning && !store.isUploadingWeChatCover)
        #expect(store.configuration.delivery.wechat.thumbMediaID == "offline-cover")
        #expect(store.coverUploadUncertain)
    }

    @Test func missingCredentialAndSymbolicLinkDoNotStartUpload() async throws {
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner()
        let store = fixture.store(runner, secrets: CoverMissingSecrets())
        let image = fixture.root.appending(path: "original.png")
        try coverPNG().write(to: image)
        let link = fixture.root.appending(path: "linked.png")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: image)
        #expect(throws: (any Error).self) { try store.selectWeChatCover(from: link) }
        try store.selectWeChatCover(from: image)
        #expect(throws: WeChatDraftActionError.blocked("wechat_credentials_missing")) {
            try store.prepareWeChatCoverUpload()
        }
        #expect(await runner.calls == 0)
    }

    @Test func viewsRenderBilingualPreviewsWithoutReadingOrUploading() async throws {
        _ = NSApplication.shared
        let fixture = try WeChatFixture()
        defer { fixture.cleanup() }
        let runner = CoverRunner()
        let store = fixture.store(runner)
        try store.selectWeChatCover(WeChatCoverImage(data: coverPNG(), filename: "Offline cover.png"))
        for language in [AppLanguagePreference.english, .simplifiedChinese] {
            let localization = LocalizationStore(preference: language)
            let host = NSHostingView(rootView: WeChatCoverView(store: store, localization: localization))
            host.frame = NSRect(x: 0, y: 0, width: 520, height: 260)
            host.layoutSubtreeIfNeeded()
            #expect(host.fittingSize.height > 0)
            #expect(localization.text("cover.choose") != "cover.choose")
            let sheet = NSHostingView(rootView: WeChatCoverConfirmationView(
                confirmation: try store.prepareWeChatCoverUpload(), localization: localization,
                cancel: {}, upload: { Issue.record("Layout cannot upload") }))
            sheet.frame = NSRect(x: 0, y: 0, width: 460, height: 300)
            sheet.layoutSubtreeIfNeeded()
            #expect(sheet.fittingSize.height > 0)
            if let path = ProcessInfo.processInfo.environment["RESEARCH_RADAR_COVER_EVIDENCE_ROOT"] {
                let root = URL(fileURLWithPath: path, isDirectory: true)
                try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
                try await capture(WeChatCoverView(store: store, localization: localization),
                    to: root.appending(path: "settings-\(language.rawValue).png"),
                    dark: language == .simplifiedChinese, width: 520)
                try await capture(WeChatCoverConfirmationView(
                    confirmation: try store.prepareWeChatCoverUpload(), localization: localization,
                    cancel: {}, upload: { Issue.record("Layout cannot upload") }),
                    to: root.appending(path: "confirmation-\(language.rawValue).png"),
                    dark: language == .simplifiedChinese, width: 460)
            }
        }
        #expect(store.jobs.isEmpty)
    }

    private func capture<Content: View>(_ content: Content, to path: URL, dark: Bool, width: CGFloat) async throws {
        let host = NSHostingView(rootView: content.background(.background)
            .environment(\.colorScheme, dark ? .dark : .light))
        host.sizingOptions = []
        host.frame = NSRect(x: 0, y: 0, width: width, height: 320)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        window.contentView = host
        defer { window.orderOut(nil); window.close() }
        window.orderBack(nil)
        try await Task.sleep(for: .milliseconds(100))
        host.layoutSubtreeIfNeeded()
        #expect(host.bounds.width == width && host.bounds.height == 320)
        let bitmap = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        window.appearance?.performAsCurrentDrawingAppearance { host.cacheDisplay(in: host.bounds, to: bitmap) }
        try #require(bitmap.representation(using: .png, properties: [:])).write(to: path)
    }

    @Test func unsafeImagesAreRejectedBeforeAnyTask() throws {
        #expect(throws: (any Error).self) { try WeChatCoverImage(data: Data("no image".utf8), filename: "bad.png") }
        #expect(throws: (any Error).self) {
            try WeChatCoverImage(data: Data(repeating: 0, count: 2 * 1024 * 1024 + 1), filename: "big.png")
        }
        let image = try WeChatCoverImage(data: coverPNG(), filename: "cover.png")
        #expect(image.width == 32 && image.height == 18)
        #expect(image.fileExtension == "png")
        #expect(!image.previewData.isEmpty)
        let jpeg = try #require(NSBitmapImageRep(data: coverPNG())?.representation(using: .jpeg, properties: [:]))
        let selectedJPEG = try WeChatCoverImage(data: jpeg, filename: "camera.jpeg")
        #expect(selectedJPEG.fileExtension == "jpg")
        #expect(selectedJPEG.width == 32 && selectedJPEG.height == 18)
    }
}

private struct CoverMissingSecrets: SecretStoring {
    func contains(account: String) throws -> Bool { false }
    func read(account: String) throws -> Data? { Issue.record("Must not read values"); return nil }
    func set(_ value: Data, account: String) throws { Issue.record("Must not write credentials") }
    func remove(account: String) throws { Issue.record("Must not remove credentials") }
}

private func coverPNG() -> Data {
    Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAACAAAAASCAIAAAC1qksFAAAAK0lEQVR4nGNkaGhgoCVgoqnpDKMWEAFG44AgGA0igmA0iAiC0SAiCGgeRABRfwEkrX0B+wAAAABJRU5ErkJggg==")!
}
