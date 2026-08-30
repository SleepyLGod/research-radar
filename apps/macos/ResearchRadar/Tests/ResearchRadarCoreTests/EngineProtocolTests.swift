import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct EngineProtocolTests {
    @Test func preflightRequestUsesExactSnakeCaseContract() throws {
        let requestID = UUID()
        let request = EngineRequestV1.preflight(
            requestID: requestID,
            createdAt: Date(timeIntervalSince1970: 0),
            appSupportRoot: URL(fileURLWithPath: "/tmp/ResearchRadar-Dev"),
            configPath: nil
        )

        let data = try EngineProtocolCodec.encode(request)
        let object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])

        #expect(Set(object.keys) == [
            "schema_version", "request_id", "command", "created_at",
            "app_support_root", "config_path", "payload",
        ])
        #expect(object["schema_version"] as? Int == 1)
        #expect(object["command"] as? String == "preflight")
        let payload = try #require(object["payload"] as? [String: Any])
        #expect(Set(payload.keys) == ["live_probe"])
        #expect(payload["live_probe"] as? Bool == false)
    }

    @Test func decoderRejectsUnknownFields() throws {
        let data = Data("""
            {
              "schema_version": 1,
              "request_id": "f249d072-32d8-43f3-a456-029636fa282a",
              "status": "failed",
              "code": "invalid_request",
              "message": "Invalid request",
              "unexpected": true
            }
            """.utf8)

        #expect(throws: EngineProtocolError.self) {
            try EngineProtocolCodec.decodeError(data)
        }
    }

    @Test func decoderRejectsSecretLikeFields() throws {
        for field in ["api_key", "token", "authorization", "token_value"] {
            let data = try JSONSerialization.data(withJSONObject: [
                "schema_version": 1,
                "request_id": "f249d072-32d8-43f3-a456-029636fa282a",
                "status": "succeeded",
                "preflight": [
                    "engine_version": "0.1.0",
                    "python_version": "3.13.5",
                    "dependencies": ["bridge": [field: "must-not-cross-the-bridge"]],
                ],
            ])

            #expect(throws: EngineProtocolError.secretField) {
                try EngineProtocolCodec.decodeResult(data)
            }
        }
    }
}
