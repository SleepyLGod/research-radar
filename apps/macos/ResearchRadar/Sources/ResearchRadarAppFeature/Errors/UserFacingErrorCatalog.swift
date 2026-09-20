import Foundation

public struct UserFacingErrorCatalog {
    private let localization: LocalizationStore

    @MainActor public init(localization: LocalizationStore) {
        self.localization = localization
    }

    public static let knownCodes = Set([
            "invalid_request", "engine_missing", "engine_busy", "engine_crashed",
            "preflight_not_ready", "cancelled", "parent_lost",
            "codex_not_configured", "codex_path_invalid", "credentials_missing", "credentials_unchecked",
            "keychain_lookup_failed", "invalid_configuration", "research_failed", "delivery_failed",
            "engine_failed", "configuration_write_failed",
            "model_transport_failed", "model_response_interrupted", "model_response_retry_exhausted",
            "schedule_refresh_failed", "schedule_recovery_failed", "state_reconciliation_failed",
        ])

    @MainActor public func message(for code: String) -> String {
        guard Self.knownCodes.contains(code) else { return localization.text("error.generic") }
        let key = "error.\(code)"
        let value = localization.text(key)
        return value == key ? localization.text("error.generic") : value
    }
}
