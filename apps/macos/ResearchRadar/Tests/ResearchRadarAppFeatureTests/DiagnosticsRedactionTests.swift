import AppKit
import Foundation
import ResearchRadarCore
import SwiftUI
import Synchronization
import Testing
@testable import ResearchRadarAppFeature

@MainActor @Suite struct DiagnosticsRedactionTests {
    @Test func copyUsesCurrentSelectedStateWithoutChangingItOrAccessingServices() throws {
        let secrets = DiagnosticsSecrets()
        let store = try fixture(secrets: secrets)
        let configuration = store.configuration
        let jobs = store.jobs
        let reports = store.reports
        let runtime = store.runtime
        let metadataReads = secrets.lookups
        let pasteboard = NSPasteboard.withUniqueName()
        defer { pasteboard.releaseGlobally() }
        #expect(pasteboard.setString("Previous private clipboard", forType: .string))

        try DiagnosticsClipboard.copy(from: store, to: pasteboard)
        let text = try #require(pasteboard.string(forType: .string))
        let report = try object(text)
        #expect(report["scope"] as? String == "selected_topic")
        let attempt = try #require(report["latest_attempt"] as? [String: Any])
        #expect(attempt["state"] as? String == "failed")
        #expect(attempt["kind"] as? String == "research")
        #expect(attempt["recorded_stage"] as? String == "source_gist")
        #expect(attempt["error_code"] as? String == "model_transport_failed")
        let routes = try #require(report["routes"] as? [[String: String]])
        #expect(routes.contains { $0["task"] == "verifier" && $0["model"] == "gpt-5.6-luna"
            && $0["provider"] == "Codex" && $0["reasoning_effort"] == "xhigh" })
        #expect(routes.contains { $0["task"] == "deep_reading" && $0["model"] == "deepseek-flash" })
        let lastReport = try #require(report["latest_report"] as? [String: Any])
        let deliveries = try #require(lastReport["deliveries"] as? [[String: String]])
        #expect(deliveries.contains { $0["channel"] == "wechat" && $0["state"] == "created" })
        #expect(deliveries.contains { $0["channel"] == "email" && $0["state"] == "unknown" })
        #expect(store.configuration == configuration && store.jobs == jobs)
        #expect(store.reports == reports && store.runtime == runtime)
        #expect(secrets.lookups == metadataReads)
        #expect(!text.contains("Previous private clipboard"))
        #expect(text.utf8.count < 16_384)
    }

    @Test func privateFieldsAndUnrecognizedIdentifiersNeverReachClipboard() throws {
        let store = try fixture(hostile: true)
        store.showWeChatCoverError(WeChatDraftActionError.blocked("unknown_error_private_canary"))
        let pasteboard = NSPasteboard.withUniqueName()
        defer { pasteboard.releaseGlobally() }
        try DiagnosticsClipboard.copy(from: store, to: pasteboard)
        let text = try #require(pasteboard.string(forType: .string))
        let fakeSensitivePrefixes = ["/Users/", "/private/", "https://", "Bearer"]
        for canary in ["sk-private-canary", "tvly-private-canary", "private_canary", "reader@example.test",
                       "Original evidence quote", "Unpublished paper"] + fakeSensitivePrefixes {
            #expect(!text.contains(canary), "Diagnostic output leaked \(canary)")
        }
        let report = try object(text)
        #expect(report["last_error_code"] as? String == "unknown")
        let routes = try #require(report["routes"] as? [[String: String]])
        let reading = try #require(routes.first { $0["task"] == "deep_reading" })
        #expect(reading["model"] == "custom_omitted")
        #expect(reading["reasoning_effort"] == "custom_omitted")
        let attempt = try #require(report["latest_attempt"] as? [String: Any])
        #expect(attempt["error_code"] as? String == "unknown")
    }

    @Test func emptyStateDoesNotInventFailuresReportsOrAnEngineVersion() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "diagnostics-empty-\(UUID())")
        let store = AppStore(configuration: AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil),
            runtime: .init(updatedAt: Date()), appSupportRoot: root, secretStore: DiagnosticsSecrets())
        let report = try object(RedactedDiagnostics.text(for: store))
        #expect(report["latest_attempt"] == nil)
        #expect(report["latest_report"] == nil)
        #expect(report["last_error_code"] as? String == "none")
        #expect(report["engine_version"] as? String == "not_recorded")
    }

    @Test func engineVersionAcceptsOnlyTheRecordedVersionGrammarNotArbitraryMessages() {
        #expect(RedactedDiagnostics.engineVersion(from: "ResearchRadar 0.1.0 on Python 3.13.") == "0.1.0")
        #expect(RedactedDiagnostics.engineVersion(from: "ResearchRadar 0.3.0b1 on Python 3.13.") == "0.3.0b1")
        for message in [nil, "ResearchRadar /Users/someone/private_canary on Python 3.13.",
                        "ResearchRadar 0.3.0b/private_canary on Python 3.13.",
                        "ResearchRadar 0.1.0 on Python 3.13. Bearer sk-private-canary", "Original evidence quote"] {
            #expect(RedactedDiagnostics.engineVersion(from: message) == "not_recorded")
        }
    }

    @Test func bilingualCopyControlsRenderWithoutStartingServices() throws {
        _ = NSApplication.shared
        let secrets = DiagnosticsSecrets()
        let store = try fixture(secrets: secrets)
        let lookups = secrets.lookups
        let pasteboard = NSPasteboard.withUniqueName()
        defer { pasteboard.releaseGlobally() }
        for language: AppLanguagePreference in [.english, .simplifiedChinese] {
            let localization = LocalizationStore(preference: language)
            let view = NSHostingView(rootView: WorkspaceDiagnosticsView(store: store,
                localization: localization, pasteboard: pasteboard))
            view.frame = NSRect(x: 0, y: 0, width: 620, height: 520)
            view.layoutSubtreeIfNeeded()
            #expect(view.fittingSize.height > 0)
            #expect(localization.text("diagnostics.copy") != "diagnostics.copy")
        }
        #expect(secrets.lookups == lookups)
        #expect(pasteboard.string(forType: .string) == nil)
    }

    private func object(_ text: String) throws -> [String: Any] {
        try #require(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
    }

    private func fixture(hostile: Bool = false, secrets: DiagnosticsSecrets = DiagnosticsSecrets()) throws -> AppStore {
        let root = FileManager.default.temporaryDirectory.appending(path: "diagnostics-\(UUID())")
        let topicID = "private_canary"
        var config = AppConfigurationDefaults.make(workspaceRoot: root, codexExecutable: nil)
        config.topics = [.init(id: topicID, displayName: "Unpublished paper", researchFocus: "Original evidence quote",
            queries: ["private_canary", "tvly-private-canary"], paperQueries: ["private_canary"], reportLanguage: .chinese)]
        config.delivery.email.toAddress = "reader@example.test"
        config.delivery.wechat.thumbMediaID = "private_canary"
        config.providers[0].baseURL = "https://reader@example.test/private_canary"
        config.providers[0].apiKeySecret = "fake_private_canary.api_key"
        config.discovery.webSearchSecret = "fake_private_canary.api_key"
        if hostile {
            let reading = try #require(config.routes.firstIndex { $0.task == "deep_reading" })
            config.routes[reading].model = "sk-private-canary"
            config.routes.append(.init(task: "private_canary", providerID: "private_canary", model: "Original evidence quote"))
            config.providers[0].reasoningEffort = "/Users/someone/private_canary"
            config.providers[0].thinking = "Bearer sk-private-canary"
            let verifier = try #require(config.routes.firstIndex { $0.task == "verifier" })
            config.routes[verifier].providerID = "reader@example.test"
        }
        let error = RedactedEngineErrorV1(code: hostile ? "unknown_error_private_canary" : "model_transport_failed",
            message: "Bearer sk-private-canary /Users/someone/private_canary Original evidence quote", retryable: false)
        let job = try JobRecordV1(kind: .research, topicID: topicID, reportDate: "private_canary",
            trigger: .runNow, state: .failed, stage: .sourceGist, jobDirectory: "/private/private_canary",
            createdAt: Date(timeIntervalSince1970: 20), error: error)
        let other = try JobRecordV1(kind: .research, topicID: "other", reportDate: "private_canary",
            trigger: .runNow, state: .running, stage: .verifier, jobDirectory: "/Users/someone/private_canary",
            createdAt: Date(timeIntervalSince1970: 30))
        let report = ReportRecordV1(topicID: topicID, reportDate: "private_canary", runDirectory: "/Users/someone/private_canary",
            articleDraftPath: "/Users/someone/private_canary/article.json", reportHTMLPath: "/Users/someone/private_canary/report.html",
            title: "Unpublished paper", summary: "Original evidence quote", sourceCount: 1, deepReadCount: 1,
            publishableClaimCount: 1, deliveries: [.init(channel: .wechat, state: .created),
                .init(channel: .email, state: .unknown, error: error)], createdAt: Date(timeIntervalSince1970: 10))
        return AppStore(configuration: config, queueSnapshot: .init(jobs: [other, job]),
            reportSnapshot: .init(reports: [report]), runtime: .init(onboardingStep: .complete,
                selectedTopicID: topicID, schedulesPaused: true, updatedAt: Date()),
            appSupportRoot: root, secretStore: secrets)
    }
}

private final class DiagnosticsSecrets: SecretStoring {
    private let count = Mutex(0)
    var lookups: Int { count.withLock { $0 } }
    func contains(account: String) throws -> Bool { count.withLock { $0 += 1 }; return false }
    func read(account: String) throws -> Data? { Issue.record("Diagnostics must not read credentials"); return nil }
    func set(_ value: Data, account: String) throws { Issue.record("Diagnostics must not write credentials") }
    func remove(account: String) throws { Issue.record("Diagnostics must not remove credentials") }
}
