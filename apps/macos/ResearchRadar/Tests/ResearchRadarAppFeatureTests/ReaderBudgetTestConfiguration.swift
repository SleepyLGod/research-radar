import ResearchRadarCore

enum ReaderBudgetTestConfiguration {
    /// Synthetic capacity for tests of admission, not a claim about any real model.
    static func declaringBudgets(_ configuration: AppConfigurationV1) -> AppConfigurationV1 {
        var result = configuration
        let budget = ReaderContextBudgetV1(contextWindowTokens: 200_000,
            outputReserveTokens: 10_000, overheadReserveTokens: 5_000)
        for route in result.routes where ["deep_reading", "verifier"].contains(route.task) {
            guard let index = result.providers.firstIndex(where: { $0.id == route.providerID }),
                  result.providers[index].kind != "local" else { continue }
            var contexts = result.providers[index].readerContexts ?? [:]
            contexts[route.model] = budget
            result.providers[index].readerContexts = contexts
        }
        return result
    }
}
