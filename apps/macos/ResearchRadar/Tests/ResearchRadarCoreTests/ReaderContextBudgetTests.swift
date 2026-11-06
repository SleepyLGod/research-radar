import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct ReaderContextBudgetTests {
    @Test func exactModelBudgetSurvivesConfigurationRoundTrip() throws {
        var config = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: "/offline"), codexExecutable: nil)
        let budget = ReaderContextBudgetV1(contextWindowTokens: 200_000, outputReserveTokens: 10_000, overheadReserveTokens: 5_000)
        config.providers[0].readerContexts = ["offline-model": budget]
        let decoded = try JSONCoding.decode(AppConfigurationV1.self, from: JSONCoding.encode(config))
        try decoded.validate()
        #expect(decoded.providers[0].readerContexts?["offline-model"] == budget)
        #expect(decoded.providers[0].readerContexts?["deepseek-flash"] == nil)
    }

    @Test func absentLimitsRemainUnknown() throws {
        let config = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: "/offline"), codexExecutable: nil)
        let decoded = try JSONCoding.decode(AppConfigurationV1.self, from: JSONCoding.encode(config))
        #expect(decoded.providers.allSatisfy { $0.readerContexts == nil })
    }

    @Test func unknownBudgetKeysRejectReadWithoutRewritingConfiguration() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"), codexExecutable: nil)
        config.providers[0].readerContexts = ["offline-model": ReaderContextBudgetV1(
            contextWindowTokens: 200_000, outputReserveTokens: 10_000, overheadReserveTokens: 5_000)]
        var object = try #require(JSONSerialization.jsonObject(with: JSONCoding.encode(config)) as? [String: Any])
        var providers = try #require(object["providers"] as? [[String: Any]])
        var contexts = try #require(providers[0]["reader_contexts"] as? [String: [String: Any]])
        contexts["offline-model"]?["extra_limit"] = 12345
        providers[0]["reader_contexts"] = contexts
        object["providers"] = providers
        let original = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        try FileManager.default.createDirectory(at: root.appending(path: "config"), withIntermediateDirectories: true)
        let path = root.appending(path: "config/app-config.json")
        try original.write(to: path)

        #expect(throws: DecodingError.self) {
            try JSONCoding.decode(AppConfigurationV1.self, from: original)
        }
        #expect(throws: AtomicJSONStoreError.corruptFile(path)) {
            try AtomicJSONStore(root: root).read(AppConfigurationV1.self, from: "config/app-config.json")
        }
        #expect(try Data(contentsOf: path) == original)
    }

    @Test func paddedModelBudgetKeysCannotBeSaved() throws {
        var config = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: "/offline"), codexExecutable: nil)
        config.providers[0].readerContexts = [" offline-model ": ReaderContextBudgetV1(
            contextWindowTokens: 200_000, outputReserveTokens: 10_000, overheadReserveTokens: 5_000)]
        #expect(throws: DurableStateValidationError.self) { try config.validate() }
    }

    @Test(arguments: [(100, 99, 1), (100, 0, 1), (100, 1, -1), (100, Int.max, Int.max)])
    func reservesCannotOverflowOrConsumeTheWholeWindow(values: (Int, Int, Int)) throws {
        let budget = ReaderContextBudgetV1(contextWindowTokens: values.0,
            outputReserveTokens: values.1, overheadReserveTokens: values.2)
        #expect(throws: DurableStateValidationError.self) { try budget.validate() }
    }
}
