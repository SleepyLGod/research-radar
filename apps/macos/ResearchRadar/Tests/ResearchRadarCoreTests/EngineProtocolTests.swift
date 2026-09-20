import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct EngineProtocolTests {
    @Test func legacyOutcomeIsUnknownAndMalformedOutcomesAreRejected() throws {
        let legacy = try CanonicalFixture.objectDictionary(named: "run-daily-result.json")
        #expect(try EngineProtocolCodec.decodeResult(CanonicalFixture.data(from: legacy)).report?.researchOutcome == nil)
        let malformed: [Any] = [NSNull(), "ready", [:], ["status": "unknown", "reasons": []],
            ["status": "ready", "reasons": ["invented"]], ["status": "ready"],
            ["status": "ready", "reasons": ["reading_failed", "reading_failed"]],
            ["status": "ready", "reasons": [], "extra": true], ["status": "ready", "reasons": "reading_failed"]]
        for value in malformed {
            var object = legacy
            var report = try #require(object["report"] as? [String: Any])
            report["research_outcome"] = value
            object["report"] = report
            #expect(throws: (any Error).self) { try EngineProtocolCodec.decodeResult(CanonicalFixture.data(from: object)) }
        }
        var object = legacy
        var report = try #require(object["report"] as? [String: Any])
        report["unexpected"] = true
        object["report"] = report
        #expect(throws: EngineProtocolError.unexpectedFields) { try EngineProtocolCodec.decodeResult(CanonicalFixture.data(from: object)) }
    }

    @Test func durableOutcomeUsesSameStrictModelAndLegacyRemainsNil() throws {
        let legacy = ReportRecordV1(topicID: "one", reportDate: "2026-09-20", runDirectory: "/run",
            articleDraftPath: "/a", reportHTMLPath: "/h", title: "Empty", summary: "",
            sourceCount: 0, deepReadCount: 0, publishableClaimCount: 0, deliveries: [], createdAt: Date())
        let encoder = JSONEncoder(), decoder = JSONDecoder()
        let data = try encoder.encode(legacy)
        #expect(try decoder.decode(ReportRecordV1.self, from: data).researchOutcome == nil)
        var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        for value: Any in [NSNull(), ["status": "ready", "reasons": ["invented"]],
                           ["status": "ready", "reasons": ["reading_failed", "reading_failed"]],
                           ["status": "ready", "reasons": [], "extra": true]] {
            object["researchOutcome"] = value
            #expect(throws: (any Error).self) { try decoder.decode(ReportRecordV1.self, from: JSONSerialization.data(withJSONObject: object)) }
        }
        object["researchOutcome"] = ["status": "ready", "reasons": ["full_text_unavailable"]]
        let decoded = try decoder.decode(ReportRecordV1.self, from: JSONSerialization.data(withJSONObject: object))
        #expect(decoded.researchOutcome == .init(status: .ready, reasons: [.fullTextUnavailable]))
        #expect(try decoder.decode(ReportRecordV1.self, from: encoder.encode(decoded)) == decoded)
    }

    @Test func additiveResearchOutcomeRoundTrips() throws {
        var result = try CanonicalFixture.objectDictionary(named: "run-daily-result.json")
        var report = try #require(result["report"] as? [String: Any])
        report["research_outcome"] = ["status": "no_new_content", "reasons": ["no_eligible_papers"]]
        result["report"] = report
        let data = try CanonicalFixture.data(from: result)
        let decoded = try EngineProtocolCodec.decodeResult(data)
        #expect(try CanonicalFixture.object(from: EngineProtocolCodec.encode(decoded)) == CanonicalFixture.object(from: data))
    }

    @Test(arguments: CanonicalFixture.requestNames)
    func canonicalRequestsRoundTrip(_ fixtureName: String) throws {
        let data = try CanonicalFixture.data(named: fixtureName)
        let request = try EngineProtocolCodec.decodeRequest(data)
        let encoded = try EngineProtocolCodec.encode(request)

        #expect(try CanonicalFixture.object(from: encoded) == CanonicalFixture.object(from: data))
    }

    @Test func requestPayloadsAreStronglyTyped() throws {
        let preflight = try EngineProtocolCodec.decodeRequest(
            CanonicalFixture.data(named: "preflight-request.json")
        )
        let bootstrap = try EngineProtocolCodec.decodeRequest(
            CanonicalFixture.data(named: "bootstrap-topic-request.json")
        )
        let daily = try EngineProtocolCodec.decodeRequest(
            CanonicalFixture.data(named: "run-daily-request.json")
        )
        let delivery = try EngineProtocolCodec.decodeRequest(
            CanonicalFixture.data(named: "retry-delivery-request.json")
        )

        #expect(preflight.payload == .preflight(PreflightPayloadV1(liveProbe: false)))
        #expect(
            bootstrap.payload == .bootstrapTopic(
                BootstrapTopicPayloadV1(
                    description: "LLM inference systems",
                    language: .chinese
                )
            )
        )
        #expect(
            daily.payload == .runDaily(
                RunDailyPayloadV1(
                    topicID: "llm-inference",
                    reportDate: "2026-08-12",
                    limit: 5,
                    deepLimit: 2,
                    language: .chinese,
                    modelCache: true,
                    modelCacheLimitBytes: nil
                )
            )
        )
        #expect(
            delivery.payload == .retryDelivery(
                RetryDeliveryPayloadV1(
                    runDirectory: "/Users/example/Library/Application Support/ResearchRadar/workspace/runs/2026-08-12-090000000000-llm-inference",
                    channel: .email,
                    allowResend: false,
                    acknowledgeUnknownOutcome: true
                )
            )
        )
    }

    @Test func preflightFactoryUsesTypedCommandAndPayload() {
        let request = EngineRequestV1.preflight(
            requestID: UUID(uuidString: "0b5f8bc4-f934-4d86-b513-265e950fb44a")!,
            createdAt: Date(timeIntervalSince1970: 0),
            appSupportRoot: URL(fileURLWithPath: "/tmp/ResearchRadar-Dev"),
            configPath: nil
        )

        #expect(request.command == .preflight)
        #expect(request.payload == .preflight(PreflightPayloadV1(liveProbe: false)))
    }

    @Test(arguments: CanonicalFixture.resultNames)
    func canonicalResultsRoundTrip(_ fixtureName: String) throws {
        let data = try CanonicalFixture.data(named: fixtureName)
        let result = try EngineProtocolCodec.decodeResult(data)
        let encoded = try EngineProtocolCodec.encode(result)

        #expect(try CanonicalFixture.object(from: encoded) == CanonicalFixture.object(from: data))
    }

    @Test func canonicalErrorRoundTrips() throws {
        let data = try CanonicalFixture.data(named: "engine-error.json")
        let error = try EngineProtocolCodec.decodeError(data)
        let encoded = try EngineProtocolCodec.encode(error)

        #expect(error.status == .failed)
        #expect(error.stage == .deepReading)
        #expect(error.code == "research_failed")
        #expect(try CanonicalFixture.object(from: encoded) == CanonicalFixture.object(from: data))
    }

    @Test func canonicalEventsDecodeStrictly() throws {
        let data = try CanonicalFixture.data(named: "engine-events.jsonl")
        let events = try EngineProtocolCodec.decodeEvents(data)
        let encoded = try EngineProtocolCodec.encode(events[0])

        #expect(events.map(\.sequence) == [1, 2, 3, 4])
        #expect(events.map(\.type) == [.started, .stageChanged, .deliveryResult, .completed])
        #expect(events[1].stage == .deepReading)
        #expect(events[2].deliveryChannel == .wechat)
        #expect(events[3].stage == .complete)
        #expect(!encoded.contains(0x0A))
    }

    @Test func rejectsUnknownRequestAndPayloadFields() throws {
        let request = try CanonicalFixture.objectDictionary(named: "run-daily-request.json")
        var unknownRoot = request
        unknownRoot["unexpected"] = true
        #expect(throws: EngineProtocolError.unexpectedFields) {
            try EngineProtocolCodec.decodeRequest(CanonicalFixture.data(from: unknownRoot))
        }

        var unknownPayload = request
        var payload = try #require(unknownPayload["payload"] as? [String: Any])
        payload["temperature"] = 0
        unknownPayload["payload"] = payload
        #expect(throws: EngineProtocolError.unexpectedFields) {
            try EngineProtocolCodec.decodeRequest(CanonicalFixture.data(from: unknownPayload))
        }
    }

    @Test func rejectsCommandPayloadMismatch() throws {
        var request = try CanonicalFixture.objectDictionary(named: "run-daily-request.json")
        request["command"] = "bootstrap_topic"

        #expect(throws: EngineProtocolError.commandPayloadMismatch) {
            try EngineProtocolCodec.decodeRequest(CanonicalFixture.data(from: request))
        }
    }

    @Test func rejectsUnknownEnumsAndInvalidCacheLimit() throws {
        var request = try CanonicalFixture.objectDictionary(named: "run-daily-request.json")
        var payload = try #require(request["payload"] as? [String: Any])
        payload["language"] = "fr"
        request["payload"] = payload
        #expect(throws: EngineProtocolError.invalidValue) {
            try EngineProtocolCodec.decodeRequest(CanonicalFixture.data(from: request))
        }

        payload["language"] = "zh"
        payload["model_cache_limit_bytes"] = 0
        request["payload"] = payload
        #expect(throws: EngineProtocolError.invalidValue) {
            try EngineProtocolCodec.decodeRequest(CanonicalFixture.data(from: request))
        }
    }

    @Test func rejectsSecretLikeFieldsAtAnyDepth() throws {
        for field in ["api_key", "token", "authorization", "token_value"] {
            var request = try CanonicalFixture.objectDictionary(named: "bootstrap-topic-request.json")
            var payload = try #require(request["payload"] as? [String: Any])
            payload[field] = "must-not-cross-the-bridge"
            request["payload"] = payload

            #expect(throws: EngineProtocolError.secretField) {
                try EngineProtocolCodec.decodeRequest(CanonicalFixture.data(from: request))
            }
        }
    }

    @Test func rejectsResultPayloadThatDoesNotMatchCommand() throws {
        var result = try CanonicalFixture.objectDictionary(named: "run-daily-result.json")
        result["command"] = "preflight"

        #expect(throws: EngineProtocolError.commandPayloadMismatch) {
            try EngineProtocolCodec.decodeResult(CanonicalFixture.data(from: result))
        }
    }

    @Test func rejectsMalformedEventLine() throws {
        let valid = try String(
            contentsOf: CanonicalFixture.url(named: "engine-events.jsonl"),
            encoding: .utf8
        )
        let data = Data((valid + "{not-json}\n").utf8)

        #expect(throws: EngineProtocolError.invalidJSON) {
            try EngineProtocolCodec.decodeEvents(data)
        }
    }
}

private enum CanonicalFixture {
    static let requestNames = [
        "preflight-request.json",
        "bootstrap-topic-request.json",
        "run-daily-request.json",
        "retry-delivery-request.json",
    ]

    static let resultNames = [
        "preflight-result.json",
        "bootstrap-topic-result.json",
        "run-daily-result.json",
        "retry-delivery-result.json",
    ]

    static func url(named name: String) -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "Fixtures/Protocol/\(name)")
    }

    static func data(named name: String) throws -> Data {
        try Data(contentsOf: url(named: name))
    }

    static func object(from data: Data) throws -> NSObject {
        try #require(JSONSerialization.jsonObject(with: data) as? NSObject)
    }

    static func objectDictionary(named name: String) throws -> [String: Any] {
        try #require(JSONSerialization.jsonObject(with: data(named: name)) as? [String: Any])
    }

    static func data(from object: Any) throws -> Data {
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }
}
