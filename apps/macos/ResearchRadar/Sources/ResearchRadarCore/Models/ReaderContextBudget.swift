import Foundation

public struct ReaderContextBudgetV1: Codable, Equatable, Sendable {
    public var contextWindowTokens: Int
    public var outputReserveTokens: Int
    public var overheadReserveTokens: Int

    public init(contextWindowTokens: Int, outputReserveTokens: Int, overheadReserveTokens: Int) {
        self.contextWindowTokens = contextWindowTokens
        self.outputReserveTokens = outputReserveTokens
        self.overheadReserveTokens = overheadReserveTokens
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case contextWindowTokens, outputReserveTokens, overheadReserveTokens
    }

    private struct BudgetKey: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    public init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: BudgetKey.self)
        guard Set(fields.allKeys.map(\.stringValue)) == Set(CodingKeys.allCases.map(\.stringValue)) else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                debugDescription: "Reader context budgets require exactly the three capacity and reserve fields."))
        }
        let values = try decoder.container(keyedBy: CodingKeys.self)
        contextWindowTokens = try values.decode(Int.self, forKey: .contextWindowTokens)
        outputReserveTokens = try values.decode(Int.self, forKey: .outputReserveTokens)
        overheadReserveTokens = try values.decode(Int.self, forKey: .overheadReserveTokens)
    }

    public func validate() throws {
        guard contextWindowTokens > 0, outputReserveTokens > 0, overheadReserveTokens > 0,
              overheadReserveTokens < contextWindowTokens,
              outputReserveTokens < contextWindowTokens - overheadReserveTokens
        else { throw DurableStateValidationError.invalidValue }
    }
}
