import Foundation

public enum EngineProtocolError: Error, Equatable, Sendable {
    case invalidJSON
    case unexpectedFields
    case secretField
    case unsupportedSchema
    case invalidValue
    case commandPayloadMismatch
}

public enum EngineCommand: String, Codable, Equatable, Sendable {
    case preflight
    case bootstrapTopic = "bootstrap_topic"
    case runDaily = "run_daily"
    case retryDelivery = "retry_delivery"
}

public enum ReportLanguageV1: String, Codable, Equatable, Sendable {
    case english = "en"
    case chinese = "zh"
}

public enum DeliveryChannel: String, Codable, Equatable, Sendable {
    case wechat
    case email
}

public struct PreflightPayloadV1: Codable, Equatable, Sendable {
    public let liveProbe: Bool

    public init(liveProbe: Bool) {
        self.liveProbe = liveProbe
    }

    private enum CodingKeys: String, CodingKey {
        case liveProbe = "live_probe"
    }
}

public struct BootstrapTopicPayloadV1: Codable, Equatable, Sendable {
    public let description: String
    public let language: ReportLanguageV1

    public init(description: String, language: ReportLanguageV1) {
        self.description = description
        self.language = language
    }
}

public struct RunDailyPayloadV1: Codable, Equatable, Sendable {
    public let topicID: String
    public let reportDate: String
    public let limit: Int
    public let deepLimit: Int
    public let language: ReportLanguageV1
    public let modelCache: Bool
    public let modelCacheLimitBytes: Int?

    public init(
        topicID: String,
        reportDate: String,
        limit: Int,
        deepLimit: Int,
        language: ReportLanguageV1,
        modelCache: Bool,
        modelCacheLimitBytes: Int?
    ) {
        self.topicID = topicID
        self.reportDate = reportDate
        self.limit = limit
        self.deepLimit = deepLimit
        self.language = language
        self.modelCache = modelCache
        self.modelCacheLimitBytes = modelCacheLimitBytes
    }

    private enum CodingKeys: String, CodingKey {
        case topicID = "topic_id"
        case reportDate = "report_date"
        case limit
        case deepLimit = "deep_limit"
        case language
        case modelCache = "model_cache"
        case modelCacheLimitBytes = "model_cache_limit_bytes"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(topicID, forKey: .topicID)
        try container.encode(reportDate, forKey: .reportDate)
        try container.encode(limit, forKey: .limit)
        try container.encode(deepLimit, forKey: .deepLimit)
        try container.encode(language, forKey: .language)
        try container.encode(modelCache, forKey: .modelCache)
        try container.encode(modelCacheLimitBytes, forKey: .modelCacheLimitBytes)
    }
}

public struct RetryDeliveryPayloadV1: Codable, Equatable, Sendable {
    public let runDirectory: String
    public let channel: DeliveryChannel
    public let allowResend: Bool
    public let acknowledgeUnknownOutcome: Bool

    public init(
        runDirectory: String,
        channel: DeliveryChannel,
        allowResend: Bool,
        acknowledgeUnknownOutcome: Bool
    ) {
        self.runDirectory = runDirectory
        self.channel = channel
        self.allowResend = allowResend
        self.acknowledgeUnknownOutcome = acknowledgeUnknownOutcome
    }

    private enum CodingKeys: String, CodingKey {
        case runDirectory = "run_dir"
        case channel
        case allowResend = "allow_resend"
        case acknowledgeUnknownOutcome = "acknowledge_unknown_outcome"
    }
}

public enum EnginePayloadV1: Equatable, Sendable {
    case preflight(PreflightPayloadV1)
    case bootstrapTopic(BootstrapTopicPayloadV1)
    case runDaily(RunDailyPayloadV1)
    case retryDelivery(RetryDeliveryPayloadV1)

    public var command: EngineCommand {
        switch self {
        case .preflight: .preflight
        case .bootstrapTopic: .bootstrapTopic
        case .runDaily: .runDaily
        case .retryDelivery: .retryDelivery
        }
    }
}

public struct EngineRequestV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let command: EngineCommand
    public let createdAt: Date
    public let appSupportRoot: String
    public let configPath: String?
    public let payload: EnginePayloadV1

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case command
        case createdAt = "created_at"
        case appSupportRoot = "app_support_root"
        case configPath = "config_path"
        case payload
    }

    public init(
        schemaVersion: Int = 1,
        requestID: UUID,
        command: EngineCommand,
        createdAt: Date,
        appSupportRoot: String,
        configPath: String?,
        payload: EnginePayloadV1
    ) throws {
        guard command == payload.command else {
            throw EngineProtocolError.commandPayloadMismatch
        }
        self.schemaVersion = schemaVersion
        self.requestID = requestID
        self.command = command
        self.createdAt = createdAt
        self.appSupportRoot = appSupportRoot
        self.configPath = configPath
        self.payload = payload
    }

    private init(
        validatedCommand command: EngineCommand,
        requestID: UUID,
        createdAt: Date,
        appSupportRoot: String,
        configPath: String?,
        payload: EnginePayloadV1
    ) {
        self.schemaVersion = 1
        self.requestID = requestID
        self.command = command
        self.createdAt = createdAt
        self.appSupportRoot = appSupportRoot
        self.configPath = configPath
        self.payload = payload
    }

    public static func preflight(
        requestID: UUID,
        createdAt: Date,
        appSupportRoot: URL,
        configPath: URL?
    ) -> Self {
        Self(
            validatedCommand: .preflight,
            requestID: requestID,
            createdAt: createdAt,
            appSupportRoot: appSupportRoot.path,
            configPath: configPath?.path,
            payload: .preflight(PreflightPayloadV1(liveProbe: false))
        )
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let command = try container.decode(EngineCommand.self, forKey: .command)
        let payload: EnginePayloadV1 = switch command {
        case .preflight:
            .preflight(try container.decode(PreflightPayloadV1.self, forKey: .payload))
        case .bootstrapTopic:
            .bootstrapTopic(
                try container.decode(BootstrapTopicPayloadV1.self, forKey: .payload)
            )
        case .runDaily:
            .runDaily(try container.decode(RunDailyPayloadV1.self, forKey: .payload))
        case .retryDelivery:
            .retryDelivery(
                try container.decode(RetryDeliveryPayloadV1.self, forKey: .payload)
            )
        }
        try self.init(
            schemaVersion: container.decode(Int.self, forKey: .schemaVersion),
            requestID: container.decode(UUID.self, forKey: .requestID),
            command: command,
            createdAt: container.decode(Date.self, forKey: .createdAt),
            appSupportRoot: container.decode(String.self, forKey: .appSupportRoot),
            configPath: container.decodeIfPresent(String.self, forKey: .configPath),
            payload: payload
        )
    }

    public func encode(to encoder: Encoder) throws {
        guard command == payload.command else {
            throw EngineProtocolError.commandPayloadMismatch
        }
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(requestID.uuidString.lowercased(), forKey: .requestID)
        try container.encode(command, forKey: .command)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(appSupportRoot, forKey: .appSupportRoot)
        try container.encode(configPath, forKey: .configPath)
        switch payload {
        case let .preflight(value):
            try container.encode(value, forKey: .payload)
        case let .bootstrapTopic(value):
            try container.encode(value, forKey: .payload)
        case let .runDaily(value):
            try container.encode(value, forKey: .payload)
        case let .retryDelivery(value):
            try container.encode(value, forKey: .payload)
        }
    }
}

public enum EngineEventType: String, Codable, Equatable, Sendable {
    case started
    case stageChanged = "stage_changed"
    case progress
    case deliveryResult = "delivery_result"
    case completed
    case failed
    case cancelled
}

public enum EngineStage: String, Codable, Equatable, Sendable {
    case preflight
    case topicBootstrap = "topic_bootstrap"
    case discovery
    case sourceGist = "source_gist"
    case acquisition
    case deepReading = "deep_reading"
    case anchorRepair = "anchor_repair"
    case verifier
    case localization
    case compose
    case wechatDraft = "wechat_draft"
    case email
    case complete
}

public enum EngineEventStatus: String, Codable, Equatable, Sendable {
    case running
    case succeeded
    case failed
}

public enum EngineResultStatus: String, Codable, Equatable, Sendable {
    case succeeded
    case partialSuccess = "partial_success"
}

public enum EngineErrorStatus: String, Codable, Equatable, Sendable {
    case failed
}

public struct RedactedEngineErrorV1: Codable, Equatable, Sendable {
    public let code: String
    public let message: String
    public let retryable: Bool

    public init(code: String, message: String, retryable: Bool) {
        self.code = code; self.message = message; self.retryable = retryable
    }
}

public struct EngineEventV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let sequence: Int
    public let requestID: UUID
    public let emittedAt: Date
    public let type: EngineEventType
    public let stage: EngineStage?
    public let status: EngineEventStatus?
    public let message: String?
    public let completed: Int?
    public let total: Int?
    public let deliveryChannel: DeliveryChannel?
    public let runDirectory: String?
    public let error: RedactedEngineErrorV1?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sequence
        case requestID = "request_id"
        case emittedAt = "emitted_at"
        case type
        case stage
        case status
        case message
        case completed
        case total
        case deliveryChannel = "delivery_channel"
        case runDirectory = "run_dir"
        case error
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(sequence, forKey: .sequence)
        try container.encode(requestID.uuidString.lowercased(), forKey: .requestID)
        try container.encode(emittedAt, forKey: .emittedAt)
        try container.encode(type, forKey: .type)
        try container.encode(stage, forKey: .stage)
        try container.encode(status, forKey: .status)
        try container.encode(message, forKey: .message)
        try container.encode(completed, forKey: .completed)
        try container.encode(total, forKey: .total)
        try container.encode(deliveryChannel, forKey: .deliveryChannel)
        try container.encode(runDirectory, forKey: .runDirectory)
        try container.encode(error, forKey: .error)
    }
}

public enum PreflightCheckStatus: String, Codable, Equatable, Sendable {
    case ready
    case optional
    case actionRequired = "action_required"
    case unavailable
}

public struct PreflightCheckV1: Codable, Equatable, Sendable {
    public let id: String
    public let status: PreflightCheckStatus
    public let message: String
    public let provider: String?
    public let model: String?

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(status, forKey: .status)
        try container.encode(message, forKey: .message)
        try container.encode(provider, forKey: .provider)
        try container.encode(model, forKey: .model)
    }
}

public struct PreflightSummaryV1: Codable, Equatable, Sendable {
    public let checks: [PreflightCheckV1]
    public let ready: Bool
}

public struct TopicDraftV1: Codable, Equatable, Sendable {
    public let id: String
    public let displayName: String
    public let researchFocus: String
    public let queries: [String]
    public let paperQueries: [String]
    public let webQueries: [String]
    public let exclusionTerms: [String]
    public let requiredPhrases: [String]
    public let conceptGroups: [String: [String]]
    public let negativePhrases: [String]
    public let prioritySources: [String]
    public let sourceIntent: String
    public let reportLanguage: ReportLanguageV1
    public let warnings: [String]

    public init(
        id: String, displayName: String, researchFocus: String, queries: [String],
        paperQueries: [String], webQueries: [String] = [], exclusionTerms: [String] = [],
        requiredPhrases: [String] = [], conceptGroups: [String: [String]] = [:],
        negativePhrases: [String] = [], prioritySources: [String] = [],
        sourceIntent: String = "research_brief", reportLanguage: ReportLanguageV1,
        warnings: [String] = []
    ) {
        self.id = id; self.displayName = displayName; self.researchFocus = researchFocus
        self.queries = queries; self.paperQueries = paperQueries; self.webQueries = webQueries
        self.exclusionTerms = exclusionTerms; self.requiredPhrases = requiredPhrases
        self.conceptGroups = conceptGroups; self.negativePhrases = negativePhrases
        self.prioritySources = prioritySources; self.sourceIntent = sourceIntent
        self.reportLanguage = reportLanguage; self.warnings = warnings
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case researchFocus = "research_focus"
        case queries
        case paperQueries = "paper_queries"
        case webQueries = "web_queries"
        case exclusionTerms = "exclusion_terms"
        case requiredPhrases = "required_phrases"
        case conceptGroups = "concept_groups"
        case negativePhrases = "negative_phrases"
        case prioritySources = "priority_sources"
        case sourceIntent = "source_intent"
        case reportLanguage = "report_language"
        case warnings
    }
}

public enum DeliveryResultStatus: String, Codable, Equatable, Sendable {
    case created
    case sent
    case dryRun = "dry_run"
}

public struct DeliveryResultV1: Codable, Equatable, Sendable {
    public let runDirectory: String
    public let channel: DeliveryChannel
    public let status: DeliveryResultStatus
    public let completedAt: Date

    public init(
        runDirectory: String,
        channel: DeliveryChannel,
        status: DeliveryResultStatus,
        completedAt: Date
    ) {
        self.runDirectory = runDirectory
        self.channel = channel
        self.status = status
        self.completedAt = completedAt
    }

    private enum CodingKeys: String, CodingKey {
        case runDirectory = "run_dir"
        case status
        case channel
        case completedAt = "completed_at"
    }
}

public struct EngineReportSummaryV1: Codable, Equatable, Sendable {
    public let runDirectory: String
    public let reportDate: String
    public let articleDraftPath: String
    public let reportHTMLPath: String
    public let title: String
    public let summary: String
    public let sourceCount: Int
    public let deepReadCount: Int
    public let publishableClaimCount: Int

    public init(
        runDirectory: String, reportDate: String, articleDraftPath: String,
        reportHTMLPath: String, title: String, summary: String, sourceCount: Int,
        deepReadCount: Int, publishableClaimCount: Int
    ) {
        self.runDirectory = runDirectory; self.reportDate = reportDate
        self.articleDraftPath = articleDraftPath; self.reportHTMLPath = reportHTMLPath
        self.title = title; self.summary = summary; self.sourceCount = sourceCount
        self.deepReadCount = deepReadCount; self.publishableClaimCount = publishableClaimCount
    }

    private enum CodingKeys: String, CodingKey {
        case runDirectory = "run_dir"
        case reportDate = "report_date"
        case articleDraftPath = "article_draft_path"
        case reportHTMLPath = "report_html_path"
        case title
        case summary
        case sourceCount = "source_count"
        case deepReadCount = "deep_read_count"
        case publishableClaimCount = "publishable_claim_count"
    }
}

public struct EngineResultV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let command: EngineCommand
    public let status: EngineResultStatus
    public let completedAt: Date
    public let report: EngineReportSummaryV1?
    public let preflight: PreflightSummaryV1?
    public let topicDraft: TopicDraftV1?
    public let delivery: DeliveryResultV1?

    public init(
        schemaVersion: Int = 1, requestID: UUID, command: EngineCommand,
        status: EngineResultStatus, completedAt: Date, report: EngineReportSummaryV1? = nil,
        preflight: PreflightSummaryV1? = nil, topicDraft: TopicDraftV1? = nil,
        delivery: DeliveryResultV1? = nil
    ) {
        self.schemaVersion = schemaVersion; self.requestID = requestID; self.command = command
        self.status = status; self.completedAt = completedAt; self.report = report
        self.preflight = preflight; self.topicDraft = topicDraft; self.delivery = delivery
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case command
        case status
        case completedAt = "completed_at"
        case report
        case preflight
        case topicDraft = "topic_draft"
        case delivery
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(requestID.uuidString.lowercased(), forKey: .requestID)
        try container.encode(command, forKey: .command)
        try container.encode(status, forKey: .status)
        try container.encode(completedAt, forKey: .completedAt)
        try container.encode(report, forKey: .report)
        try container.encode(preflight, forKey: .preflight)
        try container.encode(topicDraft, forKey: .topicDraft)
        try container.encode(delivery, forKey: .delivery)
    }
}

public struct EngineErrorV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let status: EngineErrorStatus
    public let stage: EngineStage
    public let code: String
    public let message: String
    public let retryable: Bool
    public let completedAt: Date

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case status
        case stage
        case code
        case message
        case retryable
        case completedAt = "completed_at"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(requestID.uuidString.lowercased(), forKey: .requestID)
        try container.encode(status, forKey: .status)
        try container.encode(stage, forKey: .stage)
        try container.encode(code, forKey: .code)
        try container.encode(message, forKey: .message)
        try container.encode(retryable, forKey: .retryable)
        try container.encode(completedAt, forKey: .completedAt)
    }
}
