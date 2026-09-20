import CryptoKit
import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

private struct FrozenSecrets: SecretStoring {
    func set(_ value: Data, account: String) throws { throw CocoaError(.featureUnsupported) }
    func read(account: String) throws -> Data? { nil }
    func contains(account: String) throws -> Bool { false }
    func remove(account: String) throws { throw CocoaError(.featureUnsupported) }
}

@MainActor
@Suite struct FrozenDailyWorkflowTests {
    @Test(.enabled(if: ProcessInfo.processInfo.environment["RESEARCH_RADAR_OFFLINE_ENGINE"] != nil))
    func frozenPipelinePersistsReportAndChannelOutcomesAcrossRestart() async throws {
        let environment = ProcessInfo.processInfo.environment
        let engine = URL(fileURLWithPath: try #require(environment["RESEARCH_RADAR_OFFLINE_ENGINE"]))
        let helper = URL(fileURLWithPath: try #require(environment["RESEARCH_RADAR_OFFLINE_PDF_HELPER"]))
        #expect(FileManager.default.isExecutableFile(atPath: engine.path))
        #expect(FileManager.default.isExecutableFile(atPath: helper.path))
        let base = environment["RESEARCH_RADAR_OFFLINE_ARTIFACTS"].map {
            URL(fileURLWithPath: $0, isDirectory: true)
        } ?? FileManager.default.temporaryDirectory
        let root = base.appending(path: "frozen-workflow-\(UUID().uuidString)", directoryHint: .isDirectory)
            .resolvingSymlinksInPath()
        try FileManager.default.createDirectory(
            at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
        )
        var config = AppConfigurationV1(
            uiLanguage: .english, workspaceRoot: root.appending(path: "workspace").path,
            topics: [TopicRecordV1(
                id: "memory", displayName: "Agent Memory", researchFocus: "Agent memory evidence",
                queries: ["agent memory"], paperQueries: ["agent memory benchmark"],
                reportLanguage: .english, sourceLimit: 1, deepReadLimit: 1,
                modelCacheEnabled: false
            )],
            discovery: DiscoverySettingsV1(),
            delivery: DeliverySettingsV1(
                wechat: WeChatDeliverySettingsV1(
                    enabled: true, author: "Offline Fixture", thumbMediaID: "offline-thumb"
                ),
                email: EmailDeliverySettingsV1(
                    enabled: true, smtpHost: "smtp.invalid", username: "offline@example.com",
                    fromAddress: "offline@example.com", toAddress: "offline@example.com"
                )
            )
        )
        config.providers = [ProviderRecordV1(id: "offline", kind: "local", timeoutSeconds: 30)]
        config.routes = ["source_gist", "deep_reading", "anchor_repair", "report_localization", "verifier"].map {
            RouteRecordV1(task: $0, providerID: "offline", model: "local")
        }
        let runtime = AppRuntimeStateV1(
            onboardingStep: .complete, selectedTopicID: "memory", updatedAt: Date()
        )
        let persistence = AtomicJSONStore(root: root)
        try persistence.write(config, to: "config/app-config.json")
        try persistence.write(runtime, to: "state/app-state.json")
        let store = AppStore(
            configuration: config, runtime: runtime, appSupportRoot: root, engineURL: engine,
            pdfHelperURL: helper, runner: EngineProcessSupervisor(), secretStore: FrozenSecrets()
        )
        let date = DateFormatter()
        date.locale = Locale(identifier: "en_US_POSIX")
        date.timeZone = .current
        date.dateFormat = "yyyy-MM-dd"
        let started = Date()
        await store.runNow(topicID: "memory", reportDate: date.string(from: started))
        let elapsed = Date().timeIntervalSince(started)
        let report = try #require(store.reports.first)
        #expect(report.deepReadCount == 1)
        #expect(report.publishableClaimCount > 0)
        #expect(report.deliveries.first { $0.channel == .wechat }?.state == .unknown)
        #expect(report.deliveries.first { $0.channel == .email }?.state == .sent)
        #expect(store.jobs.filter { $0.kind == .research }.first?.state == .succeeded)
        #expect(store.jobs.filter { $0.deliveryChannel == .wechat }.first?.state == .deliveryUnknown)
        #expect(store.jobs.filter { $0.deliveryChannel == .email }.first?.state == .succeeded)
        let draft = try Data(contentsOf: URL(fileURLWithPath: report.articleDraftPath))
        let html = try Data(contentsOf: URL(fileURLWithPath: report.reportHTMLPath))
        let value = try #require(JSONSerialization.jsonObject(with: draft) as? [String: Any])
        #expect(!(try #require(value["sections"] as? [Any])).isEmpty)
        #expect(html.count > 1_000)
        #expect(String(decoding: html, as: UTF8.self).contains("figures/"))
        let indexBefore = try persistence.read(ReportIndexV1.self, from: "state/report-index.json")
        // Durable ISO-8601 dates have second precision; compare the persisted contract.
        #expect(try JSONCoding.encode(indexBefore.reports) == JSONCoding.encode(store.reports))

        // Reload durable state via the production startup loader. No window/UI claim.
        let restarted = try AppBootstrapService(appSupportRoot: root).load(
            engineURL: engine, pdfHelperURL: helper
        )
        #expect(try JSONCoding.encode(restarted.reports) == JSONCoding.encode(store.reports))
        #expect(try JSONCoding.encode(restarted.jobs) == JSONCoding.encode(store.jobs))
        #expect(try Data(contentsOf: URL(fileURLWithPath: report.articleDraftPath)) == draft)
        #expect(try Data(contentsOf: URL(fileURLWithPath: report.reportHTMLPath)) == html)
        let evidence: [String: Any] = [
            "scope": "AppStore queue + real supervisor + frozen pipeline + startup loader; no GUI",
            "elapsed_seconds": elapsed, "app_support_root": root.path,
            "run_dir": report.runDirectory, "report_bytes": html.count,
            "report_sha256": SHA256.hash(data: html).map { String(format: "%02x", $0) }.joined(),
            "restart_index_verified": true,
        ]
        try JSONSerialization.data(withJSONObject: evidence, options: [.prettyPrinted, .sortedKeys])
            .write(to: root.appending(path: "native-verification.json"))
        print("Frozen workflow evidence: \(root.path)")
        // Retain diagnostics for the controller; no deletion and no production fixture bundle.
    }
}
