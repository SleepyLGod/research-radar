import Foundation

public enum EngineProtocolCodec {
    public static func encode(_ request: EngineRequestV1) throws -> Data {
        try encodeValidated(request, validator: validateRequest)
    }

    public static func encode(_ result: EngineResultV1) throws -> Data {
        try encodeValidated(result, validator: validateResult)
    }

    public static func encode(_ error: EngineErrorV1) throws -> Data {
        try encodeValidated(error, validator: validateError)
    }

    public static func encode(_ event: EngineEventV1) throws -> Data {
        try encodeValidated(event, validator: validateEvent)
    }

    public static func decodeRequest(_ data: Data) throws -> EngineRequestV1 {
        try validateRequest(data)
        return try decode(EngineRequestV1.self, from: data)
    }

    public static func decodeResult(_ data: Data) throws -> EngineResultV1 {
        try validateResult(data)
        return try decode(EngineResultV1.self, from: data)
    }

    public static func decodeError(_ data: Data) throws -> EngineErrorV1 {
        try validateError(data)
        return try decode(EngineErrorV1.self, from: data)
    }

    public static func decodeEvent(_ data: Data) throws -> EngineEventV1 {
        try validateEvent(data)
        return try decode(EngineEventV1.self, from: data)
    }

    public static func decodeEvents(_ data: Data) throws -> [EngineEventV1] {
        guard let text = String(data: data, encoding: .utf8) else {
            throw EngineProtocolError.invalidJSON
        }
        let lines = text.split(separator: "\n", omittingEmptySubsequences: true)
        let events = try lines.map { line in
            try decodeEvent(Data(line.utf8))
        }
        guard events.enumerated().allSatisfy({ index, event in
            event.sequence == index + 1
        }) else {
            throw EngineProtocolError.invalidValue
        }
        return events
    }

    private static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }

    private static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    private static func encodeValidated<T: Encodable>(
        _ value: T,
        validator: (Data) throws -> Void
    ) throws -> Data {
        let data = try encoder().encode(value)
        try validator(data)
        return data
    }

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try decoder().decode(type, from: data)
        } catch let error as EngineProtocolError {
            throw error
        } catch is DecodingError {
            throw EngineProtocolError.invalidValue
        } catch {
            throw EngineProtocolError.invalidJSON
        }
    }

    private static func validateRequest(_ data: Data) throws {
        let object = try protocolObject(data)
        try requireExactKeys(object, requestKeys)
        try requireSchemaVersion(object)
        let command = try requireEnum(EngineCommand.self, object["command"])
        let payload = try requireObject(object["payload"])
        let expectedKeys = payloadKeys[command]!
        guard Set(payload.keys) == expectedKeys else {
            if payloadKeys.values.contains(Set(payload.keys)) {
                throw EngineProtocolError.commandPayloadMismatch
            }
            throw EngineProtocolError.unexpectedFields
        }
        if command == .runDaily,
           let cacheLimit = payload["model_cache_limit_bytes"],
           !(cacheLimit is NSNull) {
            guard let number = cacheLimit as? NSNumber,
                  !isJSONBoolean(number),
                  number.int64Value > 0,
                  number.doubleValue == Double(number.int64Value)
            else {
                throw EngineProtocolError.invalidValue
            }
        }
    }

    private static func validateResult(_ data: Data) throws {
        let object = try protocolObject(data)
        try requireExactKeys(object, resultKeys)
        try requireSchemaVersion(object)
        let command = try requireEnum(EngineCommand.self, object["command"])
        _ = try requireEnum(EngineResultStatus.self, object["status"])

        let populated = Set(resultPayloadKeys.filter { key in
            guard let value = object[key] else { return false }
            return !(value is NSNull)
        })
        let expected = resultPayloadKey[command]!
        guard populated == [expected] else {
            throw EngineProtocolError.commandPayloadMismatch
        }

        switch command {
        case .preflight:
            try validatePreflight(try requireObject(object[expected]))
        case .bootstrapTopic:
            try validateTopicDraft(try requireObject(object[expected]))
        case .runDaily:
            try requireExactKeys(try requireObject(object[expected]), reportKeys)
        case .retryDelivery:
            let delivery = try requireObject(object[expected])
            try requireExactKeys(delivery, deliveryKeys)
            _ = try requireEnum(DeliveryChannel.self, delivery["channel"])
            _ = try requireEnum(DeliveryResultStatus.self, delivery["status"])
        }
    }

    private static func validateError(_ data: Data) throws {
        let object = try protocolObject(data)
        try requireExactKeys(object, errorKeys)
        try requireSchemaVersion(object)
        _ = try requireEnum(EngineErrorStatus.self, object["status"])
        _ = try requireEnum(EngineStage.self, object["stage"])
        guard let code = object["code"] as? String,
              knownErrorCodes.contains(code),
              let message = object["message"] as? String,
              message.count <= 500
        else {
            throw EngineProtocolError.invalidValue
        }
    }

    private static func validateEvent(_ data: Data) throws {
        let object = try protocolObject(data)
        try requireExactKeys(object, eventKeys)
        try requireSchemaVersion(object)
        let type = try requireEnum(EngineEventType.self, object["type"])
        if let stage = object["stage"], !(stage is NSNull) {
            _ = try requireEnum(EngineStage.self, stage)
        }
        if let status = object["status"], !(status is NSNull) {
            _ = try requireEnum(EngineEventStatus.self, status)
        }
        if let channel = object["delivery_channel"], !(channel is NSNull) {
            _ = try requireEnum(DeliveryChannel.self, channel)
        }
        if let error = object["error"], !(error is NSNull) {
            try requireExactKeys(try requireObject(error), redactedErrorKeys)
        }
        if type == .deliveryResult, object["delivery_channel"] is NSNull {
            throw EngineProtocolError.invalidValue
        }
        if type == .failed, object["error"] is NSNull {
            throw EngineProtocolError.invalidValue
        }
    }

    private static func validatePreflight(_ object: [String: Any]) throws {
        try requireExactKeys(object, preflightKeys)
        guard let checks = object["checks"] as? [Any] else {
            throw EngineProtocolError.invalidValue
        }
        for value in checks {
            let check = try requireObject(value)
            try requireExactKeys(check, preflightCheckKeys)
            _ = try requireEnum(PreflightCheckStatus.self, check["status"])
        }
    }

    private static func validateTopicDraft(_ object: [String: Any]) throws {
        try requireExactKeys(object, topicDraftKeys)
        _ = try requireEnum(ReportLanguageV1.self, object["report_language"])
        guard let groups = object["concept_groups"] as? [String: Any],
              groups.values.allSatisfy({ value in
                  guard let strings = value as? [Any] else { return false }
                  return strings.allSatisfy { $0 is String }
              })
        else {
            throw EngineProtocolError.invalidValue
        }
    }

    private static func protocolObject(_ data: Data) throws -> [String: Any] {
        guard let value = try? JSONSerialization.jsonObject(with: data),
              let object = value as? [String: Any]
        else {
            throw EngineProtocolError.invalidJSON
        }
        if containsSecretField(object) {
            throw EngineProtocolError.secretField
        }
        return object
    }

    private static func requireSchemaVersion(_ object: [String: Any]) throws {
        guard let version = object["schema_version"] as? NSNumber,
              !isJSONBoolean(version),
              version.intValue == 1
        else {
            throw EngineProtocolError.unsupportedSchema
        }
    }

    private static func isJSONBoolean(_ number: NSNumber) -> Bool {
        CFGetTypeID(number) == CFBooleanGetTypeID()
    }

    private static func requireExactKeys(_ object: [String: Any], _ keys: Set<String>) throws {
        guard Set(object.keys) == keys else {
            throw EngineProtocolError.unexpectedFields
        }
    }

    private static func requireObject(_ value: Any?) throws -> [String: Any] {
        guard let object = value as? [String: Any] else {
            throw EngineProtocolError.invalidValue
        }
        return object
    }

    private static func requireEnum<T: RawRepresentable>(
        _ type: T.Type,
        _ value: Any?
    ) throws -> T where T.RawValue == String {
        guard let rawValue = value as? String, let result = T(rawValue: rawValue) else {
            throw EngineProtocolError.invalidValue
        }
        return result
    }

    private static func containsSecretField(_ value: Any) -> Bool {
        if let dictionary = value as? [String: Any] {
            return dictionary.contains { key, item in
                forbiddenSecretFields.contains(key.lowercased()) || containsSecretField(item)
            }
        }
        if let array = value as? [Any] {
            return array.contains(where: containsSecretField)
        }
        return false
    }

    private static let requestKeys: Set<String> = [
        "schema_version", "request_id", "command", "created_at",
        "app_support_root", "config_path", "payload",
    ]
    private static let payloadKeys: [EngineCommand: Set<String>] = [
        .preflight: ["live_probe"],
        .bootstrapTopic: ["description", "language"],
        .runDaily: [
            "topic_id", "report_date", "limit", "deep_limit", "language",
            "model_cache", "model_cache_limit_bytes",
        ],
        .retryDelivery: [
            "run_dir", "channel", "allow_resend", "acknowledge_unknown_outcome",
        ],
    ]
    private static let resultKeys: Set<String> = [
        "schema_version", "request_id", "command", "status", "completed_at",
        "report", "preflight", "topic_draft", "delivery",
    ]
    private static let resultPayloadKeys = ["report", "preflight", "topic_draft", "delivery"]
    private static let resultPayloadKey: [EngineCommand: String] = [
        .preflight: "preflight",
        .bootstrapTopic: "topic_draft",
        .runDaily: "report",
        .retryDelivery: "delivery",
    ]
    private static let preflightKeys: Set<String> = ["checks", "ready"]
    private static let preflightCheckKeys: Set<String> = [
        "id", "status", "message", "provider", "model",
    ]
    private static let topicDraftKeys: Set<String> = [
        "id", "display_name", "research_focus", "queries", "paper_queries",
        "web_queries", "exclusion_terms", "required_phrases", "concept_groups",
        "negative_phrases", "priority_sources", "source_intent", "report_language",
        "warnings",
    ]
    private static let reportKeys: Set<String> = [
        "run_dir", "report_date", "article_draft_path", "report_html_path", "title",
        "summary", "source_count", "deep_read_count", "publishable_claim_count",
    ]
    private static let deliveryKeys: Set<String> = [
        "run_dir", "channel", "status", "completed_at",
    ]
    private static let errorKeys: Set<String> = [
        "schema_version", "request_id", "status", "stage", "code", "message",
        "retryable", "completed_at",
    ]
    private static let eventKeys: Set<String> = [
        "schema_version", "sequence", "request_id", "emitted_at", "type", "stage",
        "status", "message", "completed", "total", "delivery_channel", "run_dir", "error",
    ]
    private static let redactedErrorKeys: Set<String> = ["code", "message", "retryable"]
    private static let forbiddenSecretFields: Set<String> = [
        "api_key", "password", "secret_value", "token", "api_key_value",
        "token_value", "authorization", "cookie",
    ]
    private static let knownErrorCodes: Set<String> = [
        "invalid_request", "command_unavailable", "unsupported_schema",
        "invalid_configuration", "missing_secret", "missing_executable",
        "provider_unavailable", "invalid_report_date", "research_failed",
        "delivery_failed", "engine_crashed", "parent_lost", "protocol_error",
        "cancelled",
    ]
}
