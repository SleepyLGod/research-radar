import Foundation

public enum AppConfigurationDefaults {
    /// Updates former built-in Codex verifiers without changing custom routes.
    public static func updatingLegacyCodexDefaults(_ configuration: AppConfigurationV1) -> AppConfigurationV1 {
        guard let route = configuration.routes.firstIndex(where: {
            $0.task == "verifier" && $0.providerID == "codex"
        }), let provider = configuration.providers.firstIndex(where: {
            $0.id == "codex" && $0.kind == "codex_cli"
        }) else {
            return configuration
        }
        var updated = configuration
        switch configuration.routes[route].model {
        case "gpt-5.6-luna":
            updated.routes[route].model = "gpt-6-luna"
        case "gpt-5.6-terra" where configuration.providers[provider].reasoningEffort == "high"
            && !configuration.routes.contains(where: { $0.providerID == "codex" && $0.task != "verifier" }):
            updated.routes[route].model = "gpt-6-luna"
            updated.providers[provider].reasoningEffort = "xhigh"
        default:
            break
        }
        return updated
    }

    /// Updates only the former built-in DeepSeek model name, preserving user routes.
    public static func updatingLegacyFlashRoutes(_ configuration: AppConfigurationV1) -> AppConfigurationV1 {
        var updated = configuration
        for index in updated.routes.indices where updated.routes[index].providerID == "deepseek"
            && updated.routes[index].model == "deepseek-v4-flash" {
            updated.routes[index].model = "deepseek-flash"
        }
        return updated
    }

    /// Creates the supported v1 route set without storing any secret values.
    public static func make(workspaceRoot: URL, codexExecutable: URL?) -> AppConfigurationV1 {
        let deepSeek = ProviderRecordV1(
            id: "deepseek", kind: "openai_compatible",
            baseURL: "https://api.deepseek.com/chat/completions",
            apiKeySecret: "deepseek.api_key", timeoutSeconds: 900,
            thinking: "enabled", reasoningEffort: "high"
        )
        let codex = ProviderRecordV1(
            id: "codex", kind: "codex_cli", commandPath: codexExecutable?.path,
            timeoutSeconds: 900, reasoningEffort: "xhigh"
        )
        let deepSeekTasks = [
            "topic_bootstrap", "source_gist", "deep_reading", "anchor_repair",
            "report_localization",
        ]
        let routes = deepSeekTasks.map {
            RouteRecordV1(task: $0, providerID: "deepseek", model: "deepseek-flash")
        } + [RouteRecordV1(task: "verifier", providerID: "codex", model: "gpt-6-luna")]
        return AppConfigurationV1(
            workspaceRoot: workspaceRoot.path,
            providers: [deepSeek, codex], routes: routes,
            discovery: DiscoverySettingsV1(
                webSearchProvider: "tavily", webSearchSecret: "web_search.api_key"
            ),
            delivery: DeliverySettingsV1()
        )
    }

    /// Explicitly changes only the verifier route when the user accepts reduced review diversity.
    public static func useDeepSeekVerifier(_ configuration: AppConfigurationV1) -> AppConfigurationV1 {
        var updated = configuration
        if let index = updated.routes.firstIndex(where: { $0.task == "verifier" }) {
            updated.routes[index].providerID = "deepseek"
            updated.routes[index].model = "deepseek-flash"
        }
        return updated
    }
}
