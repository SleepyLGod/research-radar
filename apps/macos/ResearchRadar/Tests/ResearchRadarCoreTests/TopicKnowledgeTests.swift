import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct TopicKnowledgeTests {
    @Test func sharedPythonProjectionFixtureRoundTripsAndRejectsMalformedResults() throws {
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appending(path: "Fixtures/Protocol/topic-knowledge-result.json")
        let data = try Data(contentsOf: fixture)
        let value = try EngineProtocolCodec.decodeResult(data)
        #expect(value.knowledge?.current?.paperCount == 2)
        #expect(try EngineProtocolCodec.decodeResult(EngineProtocolCodec.encode(value)) == value)
        for change in ["wrong_topic_field", "boolean_count", "missing_current"] {
            var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
            var knowledge = try #require(object["knowledge"] as? [String: Any])
            if change == "wrong_topic_field" { knowledge["extra"] = true }
            else if change == "missing_current" { knowledge["current"] = NSNull() }
            else {
                var current = try #require(knowledge["current"] as? [String: Any])
                current["paper_count"] = true; knowledge["current"] = current
            }
            object["knowledge"] = knowledge
            #expect(throws: EngineProtocolError.self) {
                _ = try EngineProtocolCodec.decodeResult(JSONSerialization.data(withJSONObject: object))
            }
        }
    }
    @Test func organizationRequestRoundTripsWithCapturedScope() throws {
        let payload = organizationPayload()
        let request = try EngineRequestV1(requestID: UUID(), command: .organizeTopic,
            createdAt: Date(timeIntervalSince1970: 0), appSupportRoot: "/tmp/app",
            configPath: "/tmp/app/config.json", payload: .organizeTopic(payload))
        let data = try EngineProtocolCodec.encode(request)
        #expect(try EngineProtocolCodec.decodeRequest(data) == request)
        let object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let body = try #require(object["payload"] as? [String: Any])
        #expect(body["research_question"] as? String == "How is memory selected?")
    }

    @Test func organizationQueueCoalescesByTopicAndPersistsWithoutDelivery() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? trashKnowledgeTestRoot(root) }
        let store = AtomicJSONStore(root: root)
        let queue = JobQueue(store: store, jobsRoot: root.appending(path: "jobs"))
        let first = try await queue.enqueueOrganization(payload: organizationPayload(), reportDate: "2026-10-28")
        guard case .enqueued(let id) = first else { Issue.record("Expected a new organization"); return }
        #expect(try await queue.enqueueOrganization(payload: organizationPayload(), reportDate: "2026-10-29") == .coalesced(id))
        let active = try #require(try await queue.nextPending())
        #expect(active.kind == .organization)
        #expect(active.organization?.payload == organizationPayload())
        #expect(active.deliveryChannel == nil && active.requestedDeliveryChannels.isEmpty)
        #expect(try await queue.nextPending() == nil)
        try await queue.transition(jobID: id, to: .cancelled)
        let retry = try await queue.enqueueOrganization(payload: organizationPayload(), reportDate: "2026-10-29")
        #expect(retry != first)
        let saved = try store.read(JobQueueSnapshotV1.self, from: "state/queue.json")
        #expect(saved.jobs.count == 2)
        #expect(saved.jobs.last?.attemptCount == 2)
    }

    @Test func legacyResearchJobsDecodeWithoutOrganizationFields() throws {
        let old = try JobRecordV1(kind: .research, topicID: "memory", reportDate: "2026-10-28",
            trigger: .runNow, jobDirectory: "/tmp/job", createdAt: Date())
        let data = try JSONEncoder().encode(old)
        let decoded = try JSONDecoder().decode(JobRecordV1.self, from: data)
        #expect(decoded.organization == nil)
        try JobQueueSnapshotV1(jobs: [decoded]).validate()
    }
}

private func organizationPayload() -> OrganizeTopicPayloadV1 {
    .init(topicID: "memory", reports: [.init(reportID: UUID(uuidString: "11111111-1111-4111-8111-111111111111")!,
        reportDate: "2026-10-28", runDirectory: "/tmp/workspace/runs/one")],
        researchQuestion: "How is memory selected?", language: .chinese)
}

private func trashKnowledgeTestRoot(_ url: URL) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]; try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
}
