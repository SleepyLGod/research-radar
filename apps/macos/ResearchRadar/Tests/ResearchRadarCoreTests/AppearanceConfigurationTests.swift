import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct AppearanceConfigurationTests {
    @Test(arguments: ["model_transport_failed", "model_response_interrupted", "model_response_retry_exhausted"])
    func existingModelFailureCodesRemainTypedInStrictCodec(code: String) throws {
        let payload: [String: Any] = ["schema_version": 1, "request_id": "0b5f8bc4-f934-4d86-b513-265e950fb44a",
            "status": "failed", "stage": "source_gist", "code": code,
            "message": "Offline fixture failure", "retryable": true, "completed_at": "2026-09-20T00:00:00Z"]
        let failure = try EngineProtocolCodec.decodeError(JSONSerialization.data(withJSONObject: payload))
        #expect(failure.code == code)
        #expect(failure.stage == .sourceGist)
    }

    @Test func defaultsEncodeSystemAppearance() throws {
        let config = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: "/workspace"), codexExecutable: nil)
        let object = try #require(JSONSerialization.jsonObject(with: JSONCoding.encode(config)) as? [String: Any])
        #expect(object["ui_appearance"] as? String == "system")
    }

    @Test func legacyCoreFixtureDefaultsAndRoundTripsWithoutChangingConfiguration() throws {
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: repository.appending(path: "tests/fixtures/offline_frozen/swift-app-config-omitted-optionals.json"))
        let config = try JSONCoding.decode(AppConfigurationV1.self, from: data)
        try config.validate()
        var original = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        original["ui_appearance"] = original["ui_appearance"] ?? "system"
        let encoded = try #require(JSONSerialization.jsonObject(with: JSONCoding.encode(config)) as? [String: Any])
        #expect(NSDictionary(dictionary: encoded) == NSDictionary(dictionary: original))
        for value in ["system", "light", "dark"] {
            original["ui_appearance"] = value
            let decoded = try JSONCoding.decode(AppConfigurationV1.self, from: JSONSerialization.data(withJSONObject: original))
            let result = try #require(JSONSerialization.jsonObject(with: JSONCoding.encode(decoded)) as? [String: Any])
            #expect(result["ui_appearance"] as? String == value)
        }
        original["ui_appearance"] = "sepia"
        #expect(throws: DecodingError.self) {
            try JSONCoding.decode(AppConfigurationV1.self, from: JSONSerialization.data(withJSONObject: original))
        }
    }
}
