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
            "knowledge_failed", "knowledge_no_material", "knowledge_confirmation_changed",
            "model_transport_failed", "model_response_interrupted", "model_response_retry_exhausted",
            "schedule_refresh_failed", "schedule_recovery_failed", "state_reconciliation_failed",
            "email_confirmation_changed", "email_report_missing", "email_password_missing", "delivery_retry_blocked",
            "email.no_public_report", "email.configure_first", "email.busy",
            "wechat_confirmation_changed", "wechat_report_missing", "wechat_credentials_missing",
            "wechat.no_public_report", "wechat.configure_first", "wechat.busy",
            "wechat_cover_invalid", "wechat_cover_unconfirmed", "wechat_cover_save_failed",
        ])

    @MainActor public func message(for code: String) -> String {
        guard Self.knownCodes.contains(code) else { return localization.text("error.generic") }
        let key = "error.\(code)"
        let value = localization.text(key)
        return value == key ? localization.text("error.generic") : value
    }
}
