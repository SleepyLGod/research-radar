import Foundation

public enum OnboardingStep: String, Codable, Sendable {
    case storage, providers
    case topicDescription = "topic_description"
    case topicReview = "topic_review"
    case delivery, schedule, preflight, complete
}

public struct AppRuntimeStateV1: Codable, Equatable, Sendable, VersionedDurableState {
    public let schemaVersion: Int
    public var onboardingStep: OnboardingStep
    public var windowMode: WindowMode
    public var selectedTopicID: String?
    public var schedulesPaused: Bool
    public var legacyHistoryImportedAt: Date?
    public var updatedAt: Date

    public init(
        schemaVersion: Int = 1, onboardingStep: OnboardingStep = .storage,
        windowMode: WindowMode = .compact, selectedTopicID: String? = nil,
        schedulesPaused: Bool = false, legacyHistoryImportedAt: Date? = nil,
        updatedAt: Date
    ) {
        self.schemaVersion = schemaVersion; self.onboardingStep = onboardingStep
        self.windowMode = windowMode; self.selectedTopicID = selectedTopicID
        self.schedulesPaused = schedulesPaused
        self.legacyHistoryImportedAt = legacyHistoryImportedAt; self.updatedAt = updatedAt
    }
}
