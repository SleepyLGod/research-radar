import Testing
@testable import ResearchRadarAppFeature

@Suite struct UserFacingErrorCatalogTests {
    @MainActor
    @Test func knownAndUnknownErrorsUseLocalizedSafeCopy() {
        let store = LocalizationStore(
            preference: .english,
            preferredLanguages: { ["en-US"] }
        )
        let catalog = UserFacingErrorCatalog(localization: store)

        #expect(catalog.message(for: "cancelled") == "The check was cancelled.")
        #expect(
            catalog.message(for: "engine_missing")
                == "The bundled local engine is missing. Reinstall ResearchRadar."
        )
        #expect(
            catalog.message(for: "engine_busy")
                == "Another local engine check is already running."
        )
        #expect(
            catalog.message(for: "preflight_not_ready")
                == "Some required checks need attention."
        )
        #expect(
            catalog.message(for: "python traceback /private/tmp/x") == store.text("error.generic")
        )
    }
}
