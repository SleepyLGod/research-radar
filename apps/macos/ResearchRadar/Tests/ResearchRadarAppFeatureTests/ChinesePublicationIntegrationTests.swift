import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@Suite struct ChinesePublicationIntegrationTests {
    @Test(.enabled(if: ProcessInfo.processInfo.environment["RR_PUBLICATION_FIXTURE"] != nil))
    func generatedPublicationLoadsThroughTheNativeReader() throws {
        let path = try #require(ProcessInfo.processInfo.environment["RR_PUBLICATION_FIXTURE"])
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let contents = try ReportContents.decode(data, topicID: "memory")
        #expect(contents.papers.count == 2)
        let first = contents.papers[0].paragraphs.map(\.text).joined(separator: "\n")
        let second = contents.papers[1].paragraphs.map(\.text).joined(separator: "\n")
        #expect(first.contains("12 个 instance"))
        #expect(first.contains("macro-average"))
        #expect(second.contains("最终成功率"))
        #expect(second.contains("QA units"))
        #expect(!first.contains("所给材料不包含论文的明确局限性部分"))
        #expect(contents.papers.allSatisfy { !$0.claims.isEmpty })
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["RR_APP_CONFIG_EXPORT"] != nil))
    func exportIsTheActualSwiftConfigurationEncoder() throws {
        let path = try #require(ProcessInfo.processInfo.environment["RR_APP_CONFIG_EXPORT"])
        let url = URL(fileURLWithPath: path)
        let root = url.deletingLastPathComponent().deletingLastPathComponent()
        var config = AppConfigurationDefaults.make(workspaceRoot: root.appending(path: "workspace"),
            codexExecutable: URL(fileURLWithPath: "/usr/bin/true"))
        let budget = ReaderContextBudgetV1(contextWindowTokens: 2_000_000,
            outputReserveTokens: 50_000, overheadReserveTokens: 10_000)
        for index in config.providers.indices {
            let models = Set(config.routes.filter {
                $0.providerID == config.providers[index].id && ["deep_reading", "verifier"].contains($0.task)
            }.map(\.model))
            config.providers[index].readerContexts = Dictionary(uniqueKeysWithValues: models.map { ($0, budget) })
        }
        try config.validate()
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONCoding.encode(config).write(to: url, options: .withoutOverwriting)
    }
}
