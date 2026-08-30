import Foundation

public enum AppConfigurationDefaults {
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
            timeoutSeconds: 900, reasoningEffort: "high"
        )
        let deepSeekTasks = [
            "topic_bootstrap", "source_gist", "deep_reading", "anchor_repair",
            "report_localization",
        ]
        let routes = deepSeekTasks.map {
            RouteRecordV1(task: $0, providerID: "deepseek", model: "deepseek-v4-flash")
        } + [RouteRecordV1(task: "verifier", providerID: "codex", model: "gpt-5.6-terra")]
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
            updated.routes[index].model = "deepseek-v4-flash"
        }
        return updated
    }
}
