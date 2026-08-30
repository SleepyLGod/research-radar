import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct DurableStateTests {
    @Test func topLevelSnapshotsRoundTripWithSchemaVersion() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let values: [any Codable & Sendable] = [
            AppRuntimeStateV1(
                schemaVersion: 1,
                onboardingStep: .providers,
                windowMode: .compact,
                selectedTopicID: nil,
                schedulesPaused: false,
                legacyHistoryImportedAt: nil,
                updatedAt: now
            ),
            JobQueueSnapshotV1(),
            ScheduleSnapshotV1(),
            ReportIndexV1(),
        ]

        for value in values {
            let data = try JSONCoding.encode(value)
            let object = try #require(
                JSONSerialization.jsonObject(with: data) as? [String: Any]
            )
            #expect(object["schema_version"] as? Int == 1)
        }
    }

    @Test func UIAndReportLanguagesRemainIndependent() throws {
        var topic = topicRecord(language: .chinese)
        var configuration = appConfiguration(topic: topic, uiLanguage: .english)

        configuration.uiLanguage = .simplifiedChinese

        #expect(configuration.topics[0].reportLanguage == .chinese)
        topic.reportLanguage = .english
        #expect(configuration.uiLanguage == .simplifiedChinese)
    }

    @Test func jobValidationAndTransitionsFailClosed() throws {
        #expect(throws: JobRecordError.deliveryChannelRequired) {
            _ = try JobRecordV1(
                kind: .delivery,
                topicID: "topic",
                reportDate: "2026-08-30",
                trigger: .retry,
                jobDirectory: "/jobs/one",
                createdAt: .now
            )
        }
        var job = try researchJob()
        try job.transition(to: .running, stage: .deepReading, at: .now)
        try job.transition(to: .succeeded, at: .now)
        #expect(job.stage == .deepReading)
        #expect(throws: JobRecordError.invalidTransition(.succeeded, .running)) {
            try job.transition(to: .running, at: .now)
        }
    }
}

func topicRecord(language: ReportLanguageV1 = .english) -> TopicRecordV1 {
    TopicRecordV1(
        id: "llm-inference",
        displayName: "LLM Inference",
        researchFocus: "Efficient serving",
        queries: ["LLM serving"],
        paperQueries: ["LLM serving benchmark"],
        reportLanguage: language
    )
}

func appConfiguration(
    topic: TopicRecordV1 = topicRecord(),
    uiLanguage: AppLanguagePreference = .system
) -> AppConfigurationV1 {
    AppConfigurationV1(
        schemaVersion: 1,
        projectName: "ResearchRadar",
        uiLanguage: uiLanguage,
        workspaceRoot: "/workspace",
        providers: [],
        routes: [],
        topics: [topic],
        discovery: DiscoverySettingsV1(
            trustedDomains: [],
            webSearchProvider: nil,
            webSearchSecret: nil,
            webSearchEndpoint: nil,
            webSearchMaxResults: 5,
            webSearchDepth: "advanced",
            webSearchTimeoutSeconds: 30
        ),
        delivery: DeliverySettingsV1(
            wechat: WeChatDeliverySettingsV1(
                enabled: false,
                author: "ResearchRadar",
                thumbMediaID: "",
                appIDSecret: "wechat.app_id",
                appSecretSecret: "wechat.app_secret"
            ),
            email: EmailDeliverySettingsV1(
                enabled: false,
                smtpHost: "",
                smtpPort: 465,
                security: .tls,
                username: "",
                passwordSecret: "email.smtp_password",
                fromAddress: "",
                toAddress: "",
                timeoutSeconds: 30
            )
        ),
        storage: StorageSettingsV1(modelCacheLimitBytes: nil),
        startAtLogin: false
    )
}

func researchJob(
    id: UUID = UUID(),
    state: JobState = .pending,
    reportDate: String = "2026-08-30",
    createdAt: Date = Date(timeIntervalSince1970: 1_800_000_000)
) throws -> JobRecordV1 {
    try JobRecordV1(
        id: id,
        kind: .research,
        topicID: "llm-inference",
        reportDate: reportDate,
        trigger: .runNow,
        state: state,
        jobDirectory: "/jobs/\(id.uuidString.lowercased())",
        createdAt: createdAt
    )
}
