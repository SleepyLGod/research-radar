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
        if command == .uploadWeChatCover {
            guard let path = payload["image_path"] as? String, path.hasPrefix("/"),
                  validDigest(payload["image_sha256"]) else { throw EngineProtocolError.invalidValue }
        }
        if command == .readTopicKnowledge {
            guard let topic = payload["topic_id"] as? String, !topic.isEmpty else { throw EngineProtocolError.invalidValue }
        }
        if command == .organizeTopic {
            guard let question = payload["research_question"] as? String,
                  !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  question.count <= 10_000 else { throw EngineProtocolError.invalidValue }
            _ = try requireEnum(ReportLanguageV1.self, payload["language"])
        }
        if command == .readPaperLedger || command == .organizeTopic {
            guard let topic = payload["topic_id"] as? String, !topic.isEmpty,
                  let reports = payload["reports"] as? [[String: Any]] else { throw EngineProtocolError.invalidValue }
            for report in reports {
                try requireExactKeys(report, ["report_id", "report_date", "run_dir"])
                guard let id = report["report_id"] as? String, UUID(uuidString: id) != nil,
                      validReportDate(report["report_date"]),
                      let path = report["run_dir"] as? String, path.hasPrefix("/") else { throw EngineProtocolError.invalidValue }
            }
            if command == .organizeTopic && (reports.isEmpty || Set(reports.compactMap {
                ($0["report_id"] as? String).flatMap(UUID.init(uuidString:))
            }).count != reports.count) {
                throw EngineProtocolError.invalidValue
            }
        }
    }

    private static func validateResult(_ data: Data) throws {
        let object = try protocolObject(data)
        try requireExactKeys(object, resultKeys.union(["cover", "paper_ledger", "knowledge"].filter { object[$0] != nil }))
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
            let report = try requireObject(object[expected])
            try requireExactKeys(report, report["research_outcome"] == nil
                ? reportKeys : reportKeys.union(["research_outcome"]))
            if let value = report["research_outcome"] {
                let outcome = try requireObject(value)
                try requireExactKeys(outcome, ["status", "reasons"])
                _ = try requireEnum(ResearchOutcomeV1.Status.self, outcome["status"])
                guard let reasons = outcome["reasons"] as? [String],
                      Set(reasons).count == reasons.count else {
                    throw EngineProtocolError.invalidValue
                }
                for reason in reasons { _ = try requireEnum(ResearchOutcomeV1.Reason.self, reason) }
            }
        case .retryDelivery:
            let delivery = try requireObject(object[expected])
            try requireExactKeys(delivery, deliveryKeys)
            _ = try requireEnum(DeliveryChannel.self, delivery["channel"])
            _ = try requireEnum(DeliveryResultStatus.self, delivery["status"])
        case .uploadWeChatCover:
            let cover = try requireObject(object[expected])
            try requireExactKeys(cover, ["media_id", "image_sha256"])
            guard let mediaID = cover["media_id"] as? String,
                  !mediaID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  validDigest(cover["image_sha256"]) else { throw EngineProtocolError.invalidValue }
        case .readPaperLedger:
            try validatePaperLedger(try requireObject(object[expected]))
        case .organizeTopic, .readTopicKnowledge:
            try validateKnowledge(try requireObject(object[expected]), requiresCurrent: command == .organizeTopic)
        }
    }

    private static func validateKnowledge(_ value: [String: Any], requiresCurrent: Bool) throws {
        try requireExactKeys(value, value["graph"] == nil ? ["topic_id", "current"] : ["topic_id", "current", "graph"])
        guard let topic = value["topic_id"] as? String, !topic.isEmpty else { throw EngineProtocolError.invalidValue }
        if value["current"] is NSNull {
            guard !requiresCurrent, value["graph"] == nil || value["graph"] is NSNull else { throw EngineProtocolError.invalidValue }
            return
        }
        let current = try requireObject(value["current"])
        try requireExactKeys(current, ["snapshot_id", "created_at", "input_fingerprint", "report_ids",
            "provider", "model", "paper_count", "feature_count", "group_count", "relation_count"])
        guard let id = current["snapshot_id"] as? String, id.count == 32,
              id.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              validDigest(current["input_fingerprint"]),
              let reports = current["report_ids"] as? [String], !reports.isEmpty,
              Set(reports).count == reports.count, reports.allSatisfy({ UUID(uuidString: $0) != nil })
        else { throw EngineProtocolError.invalidValue }
        for key in ["created_at", "provider", "model"] {
            guard let text = current[key] as? String, !text.isEmpty, text.count <= 500 else { throw EngineProtocolError.invalidValue }
        }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = current["created_at"] as? String else { throw EngineProtocolError.invalidValue }
        if formatter.date(from: date) == nil {
            formatter.formatOptions = [.withInternetDateTime]
            guard formatter.date(from: date) != nil else { throw EngineProtocolError.invalidValue }
        }
        for key in ["paper_count", "feature_count", "group_count", "relation_count"] {
            guard let number = current[key] as? NSNumber, !isJSONBoolean(number),
                  number.intValue >= (key == "paper_count" ? 1 : 0),
                  number.doubleValue == Double(number.intValue) else { throw EngineProtocolError.invalidValue }
        }
        if let graph = value["graph"], !(graph is NSNull) {
            let data = try JSONSerialization.data(withJSONObject: graph)
            let summary = try decode(KnowledgeSummaryV1.self, from: JSONSerialization.data(withJSONObject: current))
            try KnowledgeGraphValidation.validate(data, summary: summary)
        }
    }

    private static func validReportDate(_ value: Any?) -> Bool {
        guard let text = value as? String, text.count == 10 else { return false }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        guard let date = formatter.date(from: text) else { return false }
        return formatter.string(from: date) == text
    }

    private static func validatePaperLedger(_ ledger: [String: Any]) throws {
        try requireExactKeys(ledger, ["schema_version", "topic_id", "report_ids", "papers", "unavailable_reports"])
        try requireSchemaVersion(ledger)
        guard let topic = ledger["topic_id"] as? String, !topic.isEmpty,
              let reports = ledger["report_ids"] as? [String],
              Set(reports).count == reports.count, reports.allSatisfy({ UUID(uuidString: $0) != nil }),
              let missing = ledger["unavailable_reports"] as? [String],
              Set(missing).count == missing.count, Set(missing).isSubset(of: Set(reports)),
              let papers = ledger["papers"] as? [[String: Any]] else { throw EngineProtocolError.invalidValue }
        var identities = Set<String>(), occurrences = Set<String>()
        for paper in papers {
            try requireExactKeys(paper, ["paper_id", "title", "occurrences"])
            guard validDigest(paper["paper_id"]), let id = paper["paper_id"] as? String,
                  identities.insert(id).inserted, validLedgerTitle(paper["title"]),
                  let entries = paper["occurrences"] as? [[String: Any]], !entries.isEmpty else { throw EngineProtocolError.invalidValue }
            for entry in entries {
                try requireExactKeys(entry, ["occurrence_id", "report_id", "report_date", "version", "source_url", "title", "paper_index"])
                guard validDigest(entry["occurrence_id"]), let id = entry["occurrence_id"] as? String,
                      occurrences.insert(id).inserted,
                      let report = entry["report_id"] as? String, reports.contains(report), !missing.contains(report),
                      validReportDate(entry["report_date"]), validLedgerTitle(entry["title"]),
                      let rawURL = entry["source_url"] as? String,
                      let url = URLComponents(string: rawURL), ["http", "https"].contains(url.scheme?.lowercased()),
                      url.host?.isEmpty == false, url.user == nil, url.password == nil else { throw EngineProtocolError.invalidValue }
                if !(entry["version"] is NSNull) {
                    guard let version = entry["version"] as? String, !version.isEmpty else { throw EngineProtocolError.invalidValue }
                }
                if !(entry["paper_index"] is NSNull) {
                    guard let index = entry["paper_index"] as? NSNumber, !isJSONBoolean(index),
                          index.int64Value >= 0, index.doubleValue == Double(index.int64Value) else { throw EngineProtocolError.invalidValue }
                }
            }
        }
    }

    private static func validLedgerTitle(_ value: Any?) -> Bool {
        guard let title = value as? String else { return false }
        return !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && title.count <= 500
    }

    private static func validDigest(_ value: Any?) -> Bool {
        guard let digest = value as? String else { return false }
        return digest.utf8.count == 64 && digest.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
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
        try requireExactKeys(object, eventKeys.union(object.keys.contains("paper") ? ["paper"] : []))
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
        if let value = object["paper"] {
            let paper = try requireObject(value)
            try requireExactKeys(paper, ["source_id", "title", "status"])
            let status = try requireEnum(EnginePaperStatus.self, paper["status"])
            guard let id = paper["source_id"] as? String, id.count == 64,
                  id.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
                  let title = paper["title"] as? String, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  title.count <= 500, type == .progress,
                  object["status"] as? String == EngineEventStatus.running.rawValue,
                  object["stage"] as? String == status.stage.rawValue
            else { throw EngineProtocolError.invalidValue }
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
        .uploadWeChatCover: ["image_path", "image_sha256"],
        .readPaperLedger: ["topic_id", "reports"],
        .organizeTopic: ["topic_id", "reports", "research_question", "language"],
        .readTopicKnowledge: ["topic_id"],
    ]
    private static let resultKeys: Set<String> = [
        "schema_version", "request_id", "command", "status", "completed_at",
        "report", "preflight", "topic_draft", "delivery",
    ]
    private static let resultPayloadKeys = ["report", "preflight", "topic_draft", "delivery", "cover", "paper_ledger", "knowledge"]
    private static let resultPayloadKey: [EngineCommand: String] = [
        .preflight: "preflight",
        .bootstrapTopic: "topic_draft",
        .runDaily: "report",
        .retryDelivery: "delivery",
        .uploadWeChatCover: "cover",
        .readPaperLedger: "paper_ledger",
        .organizeTopic: "knowledge",
        .readTopicKnowledge: "knowledge",
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
        "codex_not_configured",
        "provider_unavailable", "invalid_report_date", "research_failed",
        "delivery_failed", "engine_crashed", "parent_lost", "protocol_error",
        "model_transport_failed", "model_response_interrupted", "model_response_retry_exhausted",
        "cancelled",
        "cover_upload_failed",
        "knowledge_failed",
    ]
}
