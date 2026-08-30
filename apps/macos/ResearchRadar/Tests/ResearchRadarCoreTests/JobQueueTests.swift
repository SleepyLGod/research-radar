import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct JobQueueTests {
    @Test func coalescesActiveResearchAndSerializesExecution() async throws {
        let fixture = try QueueFixture()
        defer { try? trash(fixture.root) }
        let queue = fixture.queue
        let first = try await queue.enqueueResearch(
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            trigger: .runNow
        )
        let second = try await queue.enqueueResearch(
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            trigger: .schedule
        )
        guard case .enqueued(let id) = first else {
            Issue.record("Expected enqueue")
            return
        }
        #expect(second == .coalesced(id))

        let running = try await queue.nextPending()
        #expect(running?.id == id)
        #expect(try await queue.nextPending() == nil)
    }

    @Test func terminalRetryCreatesNewAttempt() async throws {
        let fixture = try QueueFixture()
        defer { try? trash(fixture.root) }
        let queue = fixture.queue
        let first = try await queue.enqueueResearch(
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            trigger: .runNow
        )
        guard case .enqueued(let firstID) = first else {
            Issue.record("Expected enqueue")
            return
        }
        _ = try await queue.nextPending()
        try await queue.transition(jobID: firstID, to: .failed)

        let retry = try await queue.enqueueResearch(
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            trigger: .retry
        )
        guard case .enqueued(let retryID) = retry else {
            Issue.record("Expected retry")
            return
        }
        #expect(retryID != firstID)
        #expect(await queue.jobs().last?.attemptCount == 2)
    }

    @Test func deliveryCoalescingIsChannelSpecific() async throws {
        let fixture = try QueueFixture()
        defer { try? trash(fixture.root) }
        let run = fixture.root.appending(path: "runs/report")
        let email = try await fixture.queue.enqueueDelivery(
            runDirectory: run,
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            channel: .email
        )
        let wechat = try await fixture.queue.enqueueDelivery(
            runDirectory: run,
            topicID: "llm-inference",
            reportDate: "2026-08-30",
            channel: .wechat
        )
        #expect(email != wechat)
    }

    @Test func unknownDeliveryRequiresExplicitAcknowledgement() async throws {
        let fixture = try QueueFixture()
        defer { try? trash(fixture.root) }
        let run = fixture.root.appending(path: "runs/report")
        _ = try await fixture.queue.enqueueDelivery(
            runDirectory: run, topicID: "memory", reportDate: "2026-08-30", channel: .email
        )
        let active = try #require(try await fixture.queue.nextPending())
        try await fixture.queue.transition(jobID: active.id, to: .deliveryUnknown)

        await #expect(throws: JobRecordError.unknownDeliveryRequiresAcknowledgement) {
            _ = try await fixture.queue.enqueueDelivery(
                runDirectory: run, topicID: "memory", reportDate: "2026-08-30", channel: .email
            )
        }
        let retry = try await fixture.queue.enqueueDelivery(
            runDirectory: run, topicID: "memory", reportDate: "2026-08-30", channel: .email,
            acknowledgeUnknownOutcome: true
        )
        guard case .enqueued(let retryID) = retry else {
            Issue.record("Expected an acknowledged retry to enqueue")
            return
        }
        #expect(await fixture.queue.jobs().first(where: { $0.id == retryID })?.acknowledgeUnknownOutcome == true)
    }

}

private func trash(_ url: URL) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}

private struct QueueFixture {
    let root: URL
    let queue: JobQueue

    init() throws {
        root = FileManager.default.temporaryDirectory
            .appending(path: "research-radar-queue-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        queue = JobQueue(
            store: AtomicJSONStore(root: root),
            jobsRoot: root.appending(path: "jobs"),
            clock: { Date(timeIntervalSince1970: 1_800_000_000) }
        )
    }
}
