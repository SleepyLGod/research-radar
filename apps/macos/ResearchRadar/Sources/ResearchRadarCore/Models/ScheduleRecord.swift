import Foundation

public struct DailyScheduleV1: Codable, Equatable, Identifiable, Sendable {
    public let id: UUID
    public let topicID: String
    public var hour: Int
    public var minute: Int
    public var isEnabled: Bool
    public var deliveryChannels: [DeliveryChannel]

    public init(
        id: UUID = UUID(), topicID: String, hour: Int, minute: Int,
        isEnabled: Bool = true, deliveryChannels: [DeliveryChannel] = []
    ) {
        self.id = id; self.topicID = topicID; self.hour = hour; self.minute = minute
        self.isEnabled = isEnabled; self.deliveryChannels = deliveryChannels
    }
}

public struct ScheduleSnapshotV1: Codable, Equatable, Sendable, ValidatableDurableState {
    public let schemaVersion: Int
    public var schedules: [DailyScheduleV1]
    public var lastEvaluatedAt: Date?

    public init(
        schemaVersion: Int = 1,
        schedules: [DailyScheduleV1] = [],
        lastEvaluatedAt: Date? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.schedules = schedules
        self.lastEvaluatedAt = lastEvaluatedAt
    }

    public func validate() throws {
        guard Set(schedules.map(\.id)).count == schedules.count,
              Set(schedules.map(\.topicID)).count == schedules.count
        else { throw DurableStateValidationError.duplicateIdentifier }
        for schedule in schedules {
            guard !schedule.topicID.isEmpty,
                  (0...23).contains(schedule.hour),
                  (0...59).contains(schedule.minute),
                  Set(schedule.deliveryChannels).count == schedule.deliveryChannels.count
            else { throw DurableStateValidationError.invalidValue }
        }
    }
}

public struct DueResearchJob: Equatable, Sendable {
    public let topicID: String
    public let reportDate: String
    public let trigger: JobTrigger
    public let deliveryChannels: [DeliveryChannel]

    public init(
        topicID: String,
        reportDate: String,
        trigger: JobTrigger,
        deliveryChannels: [DeliveryChannel]
    ) {
        self.topicID = topicID
        self.reportDate = reportDate
        self.trigger = trigger
        self.deliveryChannels = deliveryChannels
    }
}
