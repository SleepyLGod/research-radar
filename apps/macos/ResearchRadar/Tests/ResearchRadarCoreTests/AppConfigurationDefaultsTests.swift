import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct AppConfigurationDefaultsTests {
    @Test func flashMigrationChangesOnlyLegacyDeepSeekRoutesAndIsIdempotent() {
        var original = AppConfigurationDefaults.make(
            workspaceRoot: URL(fileURLWithPath: "/app/workspace"), codexExecutable: nil
        )
        original.routes[0].model = "deepseek-v4-flash"
        original.routes[1].model = "my-pinned-model"
        original.routes.append(RouteRecordV1(task: "custom", providerID: "other", model: "deepseek-v4-flash"))
        let migrated = AppConfigurationDefaults.updatingLegacyFlashRoutes(original)
        #expect(migrated.routes[0].model == "deepseek-flash")
        #expect(migrated.routes[1] == original.routes[1])
        #expect(migrated.routes.last == original.routes.last)
        #expect(migrated.providers == original.providers)
        #expect(AppConfigurationDefaults.updatingLegacyFlashRoutes(migrated) == migrated)
    }

    @Test func defaultRoutesUseFlashThinkingAndLunaVerifier() {
        let config = AppConfigurationDefaults.make(
            workspaceRoot: URL(fileURLWithPath: "/app/workspace"),
            codexExecutable: URL(fileURLWithPath: "/app/codex")
        )

        #expect(config.providers.first(where: { $0.id == "deepseek" })?.thinking == "enabled")
        #expect(config.routes.first(where: { $0.task == "deep_reading" })?.model == "deepseek-flash")
        #expect(config.routes.first(where: { $0.task == "verifier" })?.model == "gpt-5.6-luna")
        #expect(config.providers.first(where: { $0.id == "codex" })?.reasoningEffort == "xhigh")
        #expect(config.delivery.wechat.appIDSecret == "wechat.app_id")
    }

    @Test func lunaMigrationOnlyChangesTheOldBuiltInCombination() {
        var original = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: "/app/workspace"), codexExecutable: nil)
        let provider = original.providers.firstIndex { $0.id == "codex" }!
        let route = original.routes.firstIndex { $0.task == "verifier" }!
        original.providers[provider].reasoningEffort = "high"
        original.routes[route].model = "gpt-5.6-terra"
        let migrated = AppConfigurationDefaults.updatingLegacyCodexDefaults(original)
        #expect(migrated.routes[route].model == "gpt-5.6-luna")
        #expect(migrated.providers[provider].reasoningEffort == "xhigh")
        #expect(AppConfigurationDefaults.updatingLegacyCodexDefaults(migrated) == migrated)
        let fallback = AppConfigurationDefaults.useDeepSeekVerifier(original)
        #expect(AppConfigurationDefaults.updatingLegacyCodexDefaults(fallback) == fallback)
        original.routes[route].model = "custom-model"
        #expect(AppConfigurationDefaults.updatingLegacyCodexDefaults(original) == original)
        original.routes[route].model = "gpt-5.6-terra"
        original.providers[provider].reasoningEffort = "medium"
        #expect(AppConfigurationDefaults.updatingLegacyCodexDefaults(original) == original)
    }

    @Test func fallbackChangesOnlyVerifier() {
        let original = AppConfigurationDefaults.make(
            workspaceRoot: URL(fileURLWithPath: "/app/workspace"), codexExecutable: nil
        )
        let fallback = AppConfigurationDefaults.useDeepSeekVerifier(original)

        #expect(fallback.routes.first(where: { $0.task == "verifier" })?.providerID == "deepseek")
        #expect(fallback.routes.filter { $0.task != "verifier" } == original.routes.filter { $0.task != "verifier" })
    }
}
