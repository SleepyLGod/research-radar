import Foundation

@MainActor
public struct UserFacingErrorCatalog {
    private let localization: LocalizationStore

    public init(localization: LocalizationStore) {
        self.localization = localization
    }

    public func message(for code: String) -> String {
        let knownCodes = Set([
            "invalid_request", "engine_missing", "engine_busy", "engine_crashed",
            "preflight_not_ready", "cancelled", "parent_lost",
        ])
        guard knownCodes.contains(code) else { return localization.text("error.generic") }
        let key = "error.\(code)"
        let value = localization.text(key)
        return value == key ? localization.text("error.generic") : value
    }
}
