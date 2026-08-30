import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

private actor FakeDailyWorkflowRunner: EngineProcessRunning {
    let failingChannel: DeliveryChannel?

    init(failingChannel: DeliveryChannel? = nil) {
        self.failingChannel = failingChannel
    }

    func run(
        executable: URL,
        arguments: [String],
        eventsURL: URL
    ) async throws -> EngineProcessOutcome {
        let requestIndex = try #require(arguments.firstIndex(of: "--request"))
        let resultIndex = try #require(arguments.firstIndex(of: "--result"))
        let request = try EngineProtocolCodec.decodeRequest(
            Data(contentsOf: URL(fileURLWithPath: arguments[requestIndex + 1]))
        )
        if case .retryDelivery(let payload) = request.payload {
            if payload.channel == failingChannel {
                return EngineProcessOutcome(
                    exitCode: 1,
                    startedProcessGroup: nil,
                    standardOutput: Data(),
                    standardError: Data("fixture failure".utf8)
                )
            }
            let delivery = DeliveryResultV1(
                runDirectory: payload.runDirectory,
                channel: payload.channel,
                status: payload.channel == .wechat ? .created : .sent,
                completedAt: Date(timeIntervalSince1970: 1_800_000_001)
            )
            let result = EngineResultV1(
                requestID: request.requestID,
                command: .retryDelivery,
                status: .succeeded,
                completedAt: Date(timeIntervalSince1970: 1_800_000_001),
                delivery: delivery
            )
            try EngineProtocolCodec.encode(result).write(
                to: URL(fileURLWithPath: arguments[resultIndex + 1])
            )
            return EngineProcessOutcome(
                exitCode: 0,
                startedProcessGroup: nil,
                standardOutput: Data(),
                standardError: Data()
            )
        }

        let appRoot = URL(fileURLWithPath: request.appSupportRoot)
        let run = appRoot.appending(
            path: "workspace/runs/2026-08-30-090000000000-memory",
            directoryHint: .isDirectory
        )
        try FileManager.default.createDirectory(
            at: run,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let draft = run.appending(path: "article_draft.json")
        let html = run.appending(path: "wechat.html")
        try Data(#"{"schema_version":1,"title":"Fixture report"}"#.utf8).write(to: draft)
        try Data("<html><body>Fixture report</body></html>".utf8).write(to: html)
        let result = EngineResultV1(
            requestID: request.requestID,
            command: .runDaily,
            status: .succeeded,
            completedAt: Date(timeIntervalSince1970: 1_800_000_000),
            report: EngineReportSummaryV1(
                runDirectory: run.path,
                reportDate: "2026-08-30",
                articleDraftPath: draft.path,
                reportHTMLPath: html.path,
                title: "Fixture report",
                summary: "One verified fixture report.",
                sourceCount: 3,
                deepReadCount: 1,
                publishableClaimCount: 4
            )
        )
        try EngineProtocolCodec.encode(result).write(
            to: URL(fileURLWithPath: arguments[resultIndex + 1])
        )
        return EngineProcessOutcome(
            exitCode: 0,
            startedProcessGroup: nil,
            standardOutput: Data(),
            standardError: Data()
        )
    }

    func cancel() async {}
}

@MainActor
@Suite struct FakeDailyWorkflowTests {
    @Test func runNowPersistsARealReportShapeThatSurvivesAppRestart() async throws {
        let root = try fakeWorkflowRoot()
        defer { try? trashFakeWorkflowRoot(root) }
        var configuration = AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: nil
        )
        configuration.topics = [TopicRecordV1(
            id: "memory",
            displayName: "Agent Memory",
            researchFocus: "Long-term memory for agents",
            queries: ["agent memory"],
            paperQueries: ["agent memory benchmark"],
            reportLanguage: .chinese
        )]
        let persistence = AtomicJSONStore(root: root)
        try persistence.write(configuration, to: "config/app-config.json")
        let runtime = AppRuntimeStateV1(
            onboardingStep: .complete,
            selectedTopicID: "memory",
            updatedAt: Date(timeIntervalSince1970: 1_800_000_000)
        )
        try persistence.write(runtime, to: "state/app-state.json")
        let store = AppStore(
            configuration: configuration,
            runtime: runtime,
            appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/fixture/engine"),
            runner: FakeDailyWorkflowRunner()
        )

        await store.runNow(topicID: "memory", reportDate: "2026-08-30")

        let report = try #require(store.reports.first)
        #expect(report.title == "Fixture report")
        #expect(FileManager.default.fileExists(atPath: report.articleDraftPath))
        #expect(FileManager.default.fileExists(atPath: report.reportHTMLPath))
        let restarted = try AppBootstrapService(appSupportRoot: root).load(
            engineURL: URL(fileURLWithPath: "/fixture/engine")
        )
        #expect(restarted.reports.map(\.title) == ["Fixture report"])
        #expect(restarted.jobs.first?.state == .succeeded)
    }

    @Test func oneFailedDeliveryDoesNotBlockTheOtherChannel() async throws {
        let root = try fakeWorkflowRoot()
        defer { try? trashFakeWorkflowRoot(root) }
        var configuration = AppConfigurationDefaults.make(
            workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: nil
        )
        configuration.topics = [TopicRecordV1(
            id: "memory",
            displayName: "Agent Memory",
            researchFocus: "Long-term memory for agents",
            queries: ["agent memory"],
            paperQueries: ["agent memory benchmark"],
            reportLanguage: .chinese
        )]
        configuration.delivery.wechat.enabled = true
        configuration.delivery.email.enabled = true
        let persistence = AtomicJSONStore(root: root)
        try persistence.write(configuration, to: "config/app-config.json")
        let runtime = AppRuntimeStateV1(
            onboardingStep: .complete,
            selectedTopicID: "memory",
            updatedAt: Date(timeIntervalSince1970: 1_800_000_000)
        )
        let store = AppStore(
            configuration: configuration,
            runtime: runtime,
            appSupportRoot: root,
            engineURL: URL(fileURLWithPath: "/fixture/engine"),
            runner: FakeDailyWorkflowRunner(failingChannel: .wechat)
        )

        await store.runNow(topicID: "memory", reportDate: "2026-08-30")

        let deliveryJobs = store.jobs.filter { $0.kind == .delivery }
        #expect(deliveryJobs.first { $0.deliveryChannel == .wechat }?.state == .failed)
        #expect(deliveryJobs.first { $0.deliveryChannel == .email }?.state == .succeeded)
        let report = try #require(store.reports.first)
        #expect(report.deliveries.first { $0.channel == .wechat }?.state == .failed)
        #expect(report.deliveries.first { $0.channel == .email }?.state == .sent)
    }
}

private func fakeWorkflowRoot() throws -> URL {
    let root = FileManager.default.temporaryDirectory.appending(
        path: "fake-daily-workflow-\(UUID().uuidString)",
        directoryHint: .isDirectory
    )
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    return root
}

private func trashFakeWorkflowRoot(_ root: URL) throws {
    guard FileManager.default.fileExists(atPath: root.path) else { return }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [root.path]
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
