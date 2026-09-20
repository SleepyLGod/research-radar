import Foundation
import LocalAuthentication
import Testing
@testable import ResearchRadarAppFeature

private final class FakeKeychainAccess: KeychainAccessing, @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: Data] = [:]

    func update(service: String, account: String, value: Data) -> OSStatus {
        lock.withLock {
            let key = "\(service)|\(account)"
            guard values[key] != nil else { return errSecItemNotFound }
            values[key] = value
            return errSecSuccess
        }
    }

    func add(service: String, account: String, value: Data) -> OSStatus {
        lock.withLock { values["\(service)|\(account)"] = value; return errSecSuccess }
    }

    func read(service: String, account: String) -> (OSStatus, Data?) {
        lock.withLock {
            guard let value = values["\(service)|\(account)"] else {
                return (errSecItemNotFound, nil)
            }
            return (errSecSuccess, value)
        }
    }

    func presence(service: String, account: String) -> OSStatus {
        lock.withLock { values["\(service)|\(account)"] == nil ? errSecItemNotFound : errSecSuccess }
    }

    func delete(service: String, account: String) -> OSStatus {
        lock.withLock {
            values.removeValue(forKey: "\(service)|\(account)") == nil
                ? errSecItemNotFound : errSecSuccess
        }
    }
}

private struct MetadataOnlyKeychainAccess: KeychainAccessing {
    let status: OSStatus
    func presence(service: String, account: String) -> OSStatus { status }
    func read(service: String, account: String) -> (OSStatus, Data?) {
        Issue.record("Presence must not request secret bytes")
        return (errSecAuthFailed, nil)
    }
    func update(service: String, account: String, value: Data) -> OSStatus { errSecAuthFailed }
    func add(service: String, account: String, value: Data) -> OSStatus { errSecAuthFailed }
    func delete(service: String, account: String) -> OSStatus { errSecAuthFailed }
}

@Suite struct KeychainStoreTests {
    @Test func metadataQueryCannotReadSecretsOrShowAuthenticationUI() {
        let query = SystemKeychainAccess.presenceQuery(service: "test-service", account: "test-account")
        #expect(query[kSecAttrService as String] as? String == "test-service")
        #expect(query[kSecAttrAccount as String] as? String == "test-account")
        #expect(query[kSecReturnAttributes as String] as? Bool == true)
        #expect(query[kSecReturnData as String] == nil)
        #expect(query[kSecValueData as String] == nil)
        let context = query[kSecUseAuthenticationContext as String] as? LAContext
        #expect(context?.interactionNotAllowed == true)
    }

    @Test func presenceUsesMetadataWithoutReadingSecret() throws {
        let present = KeychainStore(service: "test", access: MetadataOnlyKeychainAccess(status: errSecSuccess))
        let missing = KeychainStore(service: "test", access: MetadataOnlyKeychainAccess(status: errSecItemNotFound))
        #expect(try present.contains(account: "deepseek.api_key"))
        #expect(try !missing.contains(account: "deepseek.api_key"))
    }

    @Test(arguments: [errSecInteractionNotAllowed, errSecAuthFailed, errSecNotAvailable, errSecUserCanceled])
    func unavailablePresenceIsUnknownNotMissing(status: OSStatus) {
        let store = KeychainStore(service: "test", access: MetadataOnlyKeychainAccess(status: status))
        #expect(throws: KeychainStoreError.unexpectedStatus(status)) {
            try store.contains(account: "deepseek.api_key")
        }
    }

    @Test func genericPasswordLifecycleIsScopedByServiceAndAccount() throws {
        let service = "ResearchRadar.Tests.\(UUID().uuidString)"
        let account = "deepseek.api_key"
        let access = FakeKeychainAccess()
        let store = KeychainStore(service: service, access: access)
        let otherStore = KeychainStore(service: "\(service).other", access: access)
        let secret = Data("test-secret".utf8)
        defer { try? store.delete(account: account) }

        #expect(try store.contains(account: account) == false)
        #expect(try store.read(account: account) == nil)

        try store.write(secret, account: account)

        #expect(try store.contains(account: account))
        #expect(try store.read(account: account) == secret)
        #expect(try otherStore.read(account: account) == nil)

        try store.write(Data("replacement".utf8), account: account)
        #expect(try store.read(account: account) == Data("replacement".utf8))

        try store.delete(account: account)
        #expect(try store.contains(account: account) == false)
        #expect(try store.read(account: account) == nil)
    }

    @Test func deletingAMissingSecretIsIdempotent() throws {
        let store = KeychainStore(
            service: "ResearchRadar.Tests.\(UUID().uuidString)",
            access: FakeKeychainAccess()
        )

        try store.delete(account: "missing")

        #expect(try store.contains(account: "missing") == false)
    }
}
