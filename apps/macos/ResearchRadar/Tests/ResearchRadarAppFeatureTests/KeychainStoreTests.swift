import Foundation
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

    func delete(service: String, account: String) -> OSStatus {
        lock.withLock {
            values.removeValue(forKey: "\(service)|\(account)") == nil
                ? errSecItemNotFound : errSecSuccess
        }
    }
}

@Suite struct KeychainStoreTests {
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
