import Foundation
import Testing
@testable import ResearchRadarCore

@Suite struct AppConfigurationDefaultsTests {
    @Test func defaultRoutesUseFlashThinkingAndTerraVerifier() {
        let config = AppConfigurationDefaults.make(
            workspaceRoot: URL(fileURLWithPath: "/app/workspace"),
            codexExecutable: URL(fileURLWithPath: "/app/codex")
        )

        #expect(config.providers.first(where: { $0.id == "deepseek" })?.thinking == "enabled")
        #expect(config.routes.first(where: { $0.task == "deep_reading" })?.model == "deepseek-v4-flash")
        #expect(config.routes.first(where: { $0.task == "verifier" })?.model == "gpt-5.6-terra")
        #expect(config.delivery.wechat.appIDSecret == "wechat.app_id")
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
