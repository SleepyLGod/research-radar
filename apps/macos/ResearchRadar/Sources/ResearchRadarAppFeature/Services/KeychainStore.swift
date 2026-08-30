import Foundation
import Security

public enum KeychainStoreError: Error, Equatable, Sendable {
    case invalidAccount
    case unexpectedStatus(OSStatus)
}

public protocol SecretStoring: Sendable {
    func set(_ value: Data, account: String) throws
    func read(account: String) throws -> Data?
    func contains(account: String) throws -> Bool
    func remove(account: String) throws
}

protocol KeychainAccessing: Sendable {
    func update(service: String, account: String, value: Data) -> OSStatus
    func add(service: String, account: String, value: Data) -> OSStatus
    func read(service: String, account: String) -> (OSStatus, Data?)
    func delete(service: String, account: String) -> OSStatus
}

private struct SystemKeychainAccess: KeychainAccessing {
    func update(service: String, account: String, value: Data) -> OSStatus {
        SecItemUpdate(
            baseQuery(service: service, account: account) as CFDictionary,
            [kSecValueData as String: value] as CFDictionary
        )
    }

    func add(service: String, account: String, value: Data) -> OSStatus {
        var item = baseQuery(service: service, account: account)
        item[kSecValueData as String] = value
        return SecItemAdd(item as CFDictionary, nil)
    }

    func read(service: String, account: String) -> (OSStatus, Data?) {
        var query = baseQuery(service: service, account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        return (status, result as? Data)
    }

    func delete(service: String, account: String) -> OSStatus {
        SecItemDelete(baseQuery(service: service, account: account) as CFDictionary)
    }

    private func baseQuery(service: String, account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}

public struct KeychainStore: SecretStoring {
    public static let service = "ResearchRadar"
    private let service: String
    private let access: any KeychainAccessing

    public init(service: String = Self.service) {
        self.service = service
        access = SystemKeychainAccess()
    }

    init(service: String, access: any KeychainAccessing) {
        self.service = service
        self.access = access
    }

    public func set(_ value: Data, account: String) throws {
        guard !account.isEmpty, !value.isEmpty else { throw KeychainStoreError.invalidAccount }
        let status = access.update(service: service, account: account, value: value)
        if status == errSecItemNotFound {
            let addStatus = access.add(service: service, account: account, value: value)
            guard addStatus == errSecSuccess else {
                throw KeychainStoreError.unexpectedStatus(addStatus)
            }
        } else if status != errSecSuccess {
            throw KeychainStoreError.unexpectedStatus(status)
        }
    }

    public func read(account: String) throws -> Data? {
        guard !account.isEmpty else { throw KeychainStoreError.invalidAccount }
        let (status, result) = access.read(service: service, account: account)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result else {
            throw KeychainStoreError.unexpectedStatus(status)
        }
        return data
    }

    public func contains(account: String) throws -> Bool {
        try read(account: account) != nil
    }

    public func remove(account: String) throws {
        guard !account.isEmpty else { throw KeychainStoreError.invalidAccount }
        let status = access.delete(service: service, account: account)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainStoreError.unexpectedStatus(status)
        }
    }

    public func write(_ value: Data, account: String) throws {
        try set(value, account: account)
    }

    public func delete(account: String) throws {
        try remove(account: account)
    }
}
