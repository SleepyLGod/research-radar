import Foundation

public enum EngineProtocolError: Error, Equatable, Sendable {
    case invalidJSON
    case unexpectedFields
    case secretField
    case unsupportedSchema
}

public struct PreflightPayloadV1: Codable, Equatable, Sendable {
    public let liveProbe: Bool

    enum CodingKeys: String, CodingKey {
        case liveProbe = "live_probe"
    }
}

public struct EngineRequestV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let command: String
    public let createdAt: String
    public let appSupportRoot: String
    public let configPath: String?
    public let payload: PreflightPayloadV1

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case command
        case createdAt = "created_at"
        case appSupportRoot = "app_support_root"
        case configPath = "config_path"
        case payload
    }

    public static func preflight(
        requestID: UUID,
        createdAt: Date,
        appSupportRoot: URL,
        configPath: URL?
    ) -> Self {
        Self(
            schemaVersion: 1,
            requestID: requestID,
            command: "preflight",
            createdAt: ISO8601DateFormatter().string(from: createdAt),
            appSupportRoot: appSupportRoot.path,
            configPath: configPath?.path,
            payload: PreflightPayloadV1(liveProbe: false)
        )
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(requestID.uuidString.lowercased(), forKey: .requestID)
        try container.encode(command, forKey: .command)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(appSupportRoot, forKey: .appSupportRoot)
        if let configPath {
            try container.encode(configPath, forKey: .configPath)
        } else {
            try container.encodeNil(forKey: .configPath)
        }
        try container.encode(payload, forKey: .payload)
    }
}

public struct DependencyStatusV1: Codable, Equatable, Sendable {
    public let available: Bool
    public let version: String
    public let backend: String?
}

public struct PreflightSummaryV1: Codable, Equatable, Sendable {
    public let engineVersion: String
    public let pythonVersion: String
    public let dependencies: [String: DependencyStatusV1]

    enum CodingKeys: String, CodingKey {
        case engineVersion = "engine_version"
        case pythonVersion = "python_version"
        case dependencies
    }
}

public struct EngineResultV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let status: String
    public let preflight: PreflightSummaryV1

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case status
        case preflight
    }
}

public struct EngineErrorV1: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let requestID: UUID
    public let status: String
    public let code: String
    public let message: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case requestID = "request_id"
        case status
        case code
        case message
    }
}

public enum EngineProtocolCodec {
    public static func encode(_ request: EngineRequestV1) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(request)
    }

    public static func decodeResult(_ data: Data) throws -> EngineResultV1 {
        try validateObject(
            data,
            exactKeys: ["schema_version", "request_id", "status", "preflight"]
        )
        let value = try JSONDecoder().decode(EngineResultV1.self, from: data)
        guard value.schemaVersion == 1 else { throw EngineProtocolError.unsupportedSchema }
        return value
    }

    public static func decodeError(_ data: Data) throws -> EngineErrorV1 {
        try validateObject(
            data,
            exactKeys: ["schema_version", "request_id", "status", "code", "message"]
        )
        let value = try JSONDecoder().decode(EngineErrorV1.self, from: data)
        guard value.schemaVersion == 1 else { throw EngineProtocolError.unsupportedSchema }
        return value
    }

    private static func validateObject(_ data: Data, exactKeys: Set<String>) throws {
        guard let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any]
        else {
            throw EngineProtocolError.invalidJSON
        }
        if containsSecretField(dictionary) { throw EngineProtocolError.secretField }
        guard Set(dictionary.keys) == exactKeys else {
            throw EngineProtocolError.unexpectedFields
        }
    }

    private static func containsSecretField(_ value: Any) -> Bool {
        let forbidden = Set([
            "api_key", "password", "secret_value", "token",
            "api_key_value", "token_value", "authorization", "cookie",
        ])
        if let dictionary = value as? [String: Any] {
            return dictionary.contains { key, item in
                forbidden.contains(key.lowercased()) || containsSecretField(item)
            }
        }
        if let array = value as? [Any] {
            return array.contains(where: containsSecretField)
        }
        return false
    }
}
