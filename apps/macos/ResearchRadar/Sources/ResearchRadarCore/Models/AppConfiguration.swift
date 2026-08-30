import Foundation

public enum AppLanguagePreference: String, CaseIterable, Codable, Sendable {
    case system
    case simplifiedChinese = "zh-Hans"
    case english = "en"
}

public enum ResolvedAppLanguage: String, Codable, Sendable {
    case simplifiedChinese = "zh-Hans"
    case english = "en"
}

public enum JobTrigger: String, Codable, Sendable { case schedule, runNow = "run_now", retry }
public enum JobKind: String, Codable, Sendable { case research, delivery }
public enum JobState: String, Codable, Sendable {
    case pending, running, cancelling, succeeded
    case partialSuccess = "partial_success"
    case failed, cancelled, interrupted
    case deliveryUnknown = "delivery_unknown"
}
public enum WindowMode: String, Codable, Sendable { case compact, full }
public enum DeliveryState: String, Codable, Sendable {
    case notRequested = "not_requested"
    case pending, sending, created, sent, failed, unknown
}
public enum LoginItemStatus: String, Codable, Sendable {
    case notRegistered = "not_registered"
    case enabled
    case requiresApproval = "requires_approval"
    case unavailable
}
public enum EmailSecurityV1: String, Codable, Sendable { case tls, starttls }

public struct TopicRecordV1: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public var displayName: String
    public var researchFocus: String
    public var queries: [String]
    public var paperQueries: [String]
    public var webQueries: [String]
    public var exclusionTerms: [String]
    public var requiredPhrases: [String]
    public var conceptGroups: [String: [String]]
    public var negativePhrases: [String]
    public var prioritySources: [String]
    public var sourceIntent: String
    public var reportLanguage: ReportLanguageV1
    public var sourceLimit: Int
    public var deepReadLimit: Int
    public var modelCacheEnabled: Bool
    public var isPaused: Bool

    public init(
        id: String,
        displayName: String,
        researchFocus: String,
        queries: [String],
        paperQueries: [String],
        webQueries: [String] = [],
        exclusionTerms: [String] = [],
        requiredPhrases: [String] = [],
        conceptGroups: [String: [String]] = [:],
        negativePhrases: [String] = [],
        prioritySources: [String] = [],
        sourceIntent: String = "research_brief",
        reportLanguage: ReportLanguageV1,
        sourceLimit: Int = 5,
        deepReadLimit: Int = 2,
        modelCacheEnabled: Bool = true,
        isPaused: Bool = false
    ) {
        self.id = id
        self.displayName = displayName
        self.researchFocus = researchFocus
        self.queries = queries
        self.paperQueries = paperQueries
        self.webQueries = webQueries
        self.exclusionTerms = exclusionTerms
        self.requiredPhrases = requiredPhrases
        self.conceptGroups = conceptGroups
        self.negativePhrases = negativePhrases
        self.prioritySources = prioritySources
        self.sourceIntent = sourceIntent
        self.reportLanguage = reportLanguage
        self.sourceLimit = sourceLimit
        self.deepReadLimit = deepReadLimit
        self.modelCacheEnabled = modelCacheEnabled
        self.isPaused = isPaused
    }
}

public struct ProviderRecordV1: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public var kind: String
    public var baseURL: String?
    public var apiKeySecret: String?
    public var commandPath: String?
    public var timeoutSeconds: Int
    public var thinking: String?
    public var reasoningEffort: String?

    public init(
        id: String, kind: String, baseURL: String? = nil, apiKeySecret: String? = nil,
        commandPath: String? = nil, timeoutSeconds: Int,
        thinking: String? = nil, reasoningEffort: String? = nil
    ) {
        self.id = id; self.kind = kind; self.baseURL = baseURL
        self.apiKeySecret = apiKeySecret; self.commandPath = commandPath
        self.timeoutSeconds = timeoutSeconds; self.thinking = thinking
        self.reasoningEffort = reasoningEffort
    }
}

public struct RouteRecordV1: Codable, Equatable, Sendable {
    public let task: String
    public var providerID: String
    public var model: String

    public init(task: String, providerID: String, model: String) {
        self.task = task; self.providerID = providerID; self.model = model
    }
}

public struct DiscoverySettingsV1: Codable, Equatable, Sendable {
    public var trustedDomains: [String]
    public var webSearchProvider: String?
    public var webSearchSecret: String?
    public var webSearchEndpoint: String?
    public var webSearchMaxResults: Int
    public var webSearchDepth: String
    public var webSearchTimeoutSeconds: Int

    public init(
        trustedDomains: [String] = [], webSearchProvider: String? = nil,
        webSearchSecret: String? = nil, webSearchEndpoint: String? = nil,
        webSearchMaxResults: Int = 5, webSearchDepth: String = "advanced",
        webSearchTimeoutSeconds: Int = 30
    ) {
        self.trustedDomains = trustedDomains; self.webSearchProvider = webSearchProvider
        self.webSearchSecret = webSearchSecret; self.webSearchEndpoint = webSearchEndpoint
        self.webSearchMaxResults = webSearchMaxResults; self.webSearchDepth = webSearchDepth
        self.webSearchTimeoutSeconds = webSearchTimeoutSeconds
    }
}

public struct WeChatDeliverySettingsV1: Codable, Equatable, Sendable {
    public var enabled: Bool
    public var author: String
    public var thumbMediaID: String
    public var appIDSecret: String
    public var appSecretSecret: String

    public init(
        enabled: Bool = false, author: String = "", thumbMediaID: String = "",
        appIDSecret: String = "wechat.app_id", appSecretSecret: String = "wechat.app_secret"
    ) {
        self.enabled = enabled; self.author = author; self.thumbMediaID = thumbMediaID
        self.appIDSecret = appIDSecret; self.appSecretSecret = appSecretSecret
    }
}

public struct EmailDeliverySettingsV1: Codable, Equatable, Sendable {
    public var enabled: Bool
    public var smtpHost: String
    public var smtpPort: Int
    public var security: EmailSecurityV1
    public var username: String
    public var passwordSecret: String
    public var fromAddress: String
    public var toAddress: String
    public var timeoutSeconds: Int

    public init(
        enabled: Bool = false, smtpHost: String = "", smtpPort: Int = 465,
        security: EmailSecurityV1 = .tls, username: String = "",
        passwordSecret: String = "email.smtp_password", fromAddress: String = "",
        toAddress: String = "", timeoutSeconds: Int = 30
    ) {
        self.enabled = enabled; self.smtpHost = smtpHost; self.smtpPort = smtpPort
        self.security = security; self.username = username
        self.passwordSecret = passwordSecret; self.fromAddress = fromAddress
        self.toAddress = toAddress; self.timeoutSeconds = timeoutSeconds
    }
}

public struct DeliverySettingsV1: Codable, Equatable, Sendable {
    public var wechat: WeChatDeliverySettingsV1
    public var email: EmailDeliverySettingsV1

    public init(
        wechat: WeChatDeliverySettingsV1 = WeChatDeliverySettingsV1(),
        email: EmailDeliverySettingsV1 = EmailDeliverySettingsV1()
    ) { self.wechat = wechat; self.email = email }
}

public struct StorageSettingsV1: Codable, Equatable, Sendable {
    public var modelCacheLimitBytes: UInt64?

    public init(modelCacheLimitBytes: UInt64? = nil) {
        self.modelCacheLimitBytes = modelCacheLimitBytes
    }
}

public enum DurableStateValidationError: Error, Equatable, Sendable {
    case duplicateIdentifier
    case invalidValue
    case missingReference(String)
}

public struct AppConfigurationV1: Codable, Equatable, Sendable, ValidatableDurableState {
    public let schemaVersion: Int
    public var projectName: String
    public var uiLanguage: AppLanguagePreference
    public var workspaceRoot: String
    public var providers: [ProviderRecordV1]
    public var routes: [RouteRecordV1]
    public var topics: [TopicRecordV1]
    public var discovery: DiscoverySettingsV1
    public var delivery: DeliverySettingsV1
    public var storage: StorageSettingsV1
    public var startAtLogin: Bool

    public init(
        schemaVersion: Int = 1,
        projectName: String = "ResearchRadar",
        uiLanguage: AppLanguagePreference = .system,
        workspaceRoot: String,
        providers: [ProviderRecordV1] = [],
        routes: [RouteRecordV1] = [],
        topics: [TopicRecordV1] = [],
        discovery: DiscoverySettingsV1,
        delivery: DeliverySettingsV1,
        storage: StorageSettingsV1 = StorageSettingsV1(modelCacheLimitBytes: nil),
        startAtLogin: Bool = false
    ) {
        self.schemaVersion = schemaVersion
        self.projectName = projectName
        self.uiLanguage = uiLanguage
        self.workspaceRoot = workspaceRoot
        self.providers = providers
        self.routes = routes
        self.topics = topics
        self.discovery = discovery
        self.delivery = delivery
        self.storage = storage
        self.startAtLogin = startAtLogin
    }

    public func validate() throws {
        guard !projectName.isEmpty,
              !workspaceRoot.isEmpty,
              discovery.webSearchMaxResults > 0,
              discovery.webSearchTimeoutSeconds > 0,
              storage.modelCacheLimitBytes.map({ $0 > 0 }) ?? true
        else { throw DurableStateValidationError.invalidValue }
        guard Set(providers.map(\.id)).count == providers.count,
              Set(routes.map(\.task)).count == routes.count,
              Set(topics.map(\.id)).count == topics.count
        else { throw DurableStateValidationError.duplicateIdentifier }
        let providerIDs = Set(providers.map(\.id))
        for provider in providers {
            guard !provider.id.isEmpty, !provider.kind.isEmpty, provider.timeoutSeconds > 0 else {
                throw DurableStateValidationError.invalidValue
            }
        }
        for route in routes {
            guard !route.task.isEmpty, !route.model.isEmpty else {
                throw DurableStateValidationError.invalidValue
            }
            guard providerIDs.contains(route.providerID) else {
                throw DurableStateValidationError.missingReference(route.providerID)
            }
        }
        for topic in topics {
            guard !topic.id.isEmpty,
                  !topic.displayName.isEmpty,
                  !topic.researchFocus.isEmpty,
                  !topic.queries.isEmpty,
                  !topic.paperQueries.isEmpty,
                  topic.sourceLimit > 0,
                  topic.deepReadLimit > 0
            else { throw DurableStateValidationError.invalidValue }
        }
        if delivery.email.enabled {
            guard !delivery.email.smtpHost.isEmpty,
                  (1...65_535).contains(delivery.email.smtpPort),
                  !delivery.email.fromAddress.isEmpty,
                  !delivery.email.toAddress.isEmpty,
                  delivery.email.timeoutSeconds > 0
            else { throw DurableStateValidationError.invalidValue }
        }
    }
}
