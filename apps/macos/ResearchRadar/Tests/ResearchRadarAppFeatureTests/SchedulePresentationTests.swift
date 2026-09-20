import Foundation
import Testing
import ResearchRadarCore
@testable import ResearchRadarAppFeature

@Suite struct SchedulePresentationTests {
    @Test func blockersNeverAdvertiseAnActiveNextRun() {
        var topic = TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Memory",
            queries: ["memory"], paperQueries: ["memory paper"], reportLanguage: .english)
        let schedule = DailyScheduleV1(topicID: "memory", hour: 9, minute: 0)
        func presentation(paused: Bool = false, faulted: Bool = false, error: String? = nil) -> SchedulePresentation {
            SchedulePresentation(topic: topic, schedule: schedule, paused: paused, faulted: faulted,
                configurationError: error, now: Date(), calendar: .current)
        }
        #expect(presentation().nextRun != nil)
        #expect(presentation(paused: true).status == .paused)
        #expect(presentation(paused: true).nextRun == nil)
        #expect(presentation(faulted: true).status == .faulted)
        #expect(presentation(faulted: true).nextRun == nil)
        #expect(presentation(error: "codex_not_configured").status == .configurationBlocked)
        #expect(presentation(error: "codex_not_configured").nextRun == nil)
        topic.isPaused = true
        #expect(presentation().status == .disabled)
        #expect(presentation().nextRun == nil)
        #expect(SchedulePresentation(topic: topic, schedule: nil, paused: false, faulted: false,
            configurationError: nil, now: Date(), calendar: .current).status == .absent)
    }
}
