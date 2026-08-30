import Foundation
import Testing
@testable import ResearchRadarAppFeature
import ResearchRadarCore

@MainActor
private final class PreferredLanguagesBox {
    var value: [String]

    init(_ value: [String]) {
        self.value = value
    }
}

@Suite struct AppLanguageTests {
    @Test func systemLanguageResolution() {
        let cases: [([String], ResolvedAppLanguage)] = [
            (["zh-Hans", "en"], .simplifiedChinese),
            (["zh-Hant-HK"], .simplifiedChinese),
            (["en-US"], .english),
            (["fr-FR"], .english),
            ([], .english),
        ]
        for (preferredLanguages, expected) in cases {
            #expect(
                AppLanguageResolver.resolve(preferredLanguages: preferredLanguages) == expected
            )
        }
    }

    @Test func manualLanguageOverridesSystem() {
        #expect(
            AppLanguageResolver.resolve(
            preference: .english,
            preferredLanguages: ["zh-Hans"]
            ) == .english
        )
        #expect(
            AppLanguageResolver.resolve(
            preference: .simplifiedChinese,
            preferredLanguages: ["en-US"]
            ) == .simplifiedChinese
        )
    }

    @MainActor
    @Test func localizationStoreRefreshesWithoutRestart() {
        let store = LocalizationStore(
            preference: .english,
            preferredLanguages: { ["en-US"] }
        )
        #expect(store.text("status.ready") == "Ready")

        store.preference = .simplifiedChinese

        #expect(store.text("status.ready") == "准备就绪")
    }

    @MainActor
    @Test func systemPreferenceRespondsToLocaleChanges() async {
        let languages = PreferredLanguagesBox(["en-US"])
        let store = LocalizationStore(
            preference: .system,
            preferredLanguages: { languages.value }
        )
        #expect(store.resolvedLanguage == .english)

        languages.value = ["zh-Hans"]
        NotificationCenter.default.post(name: NSLocale.currentLocaleDidChangeNotification, object: nil)
        for _ in 0..<20 where store.resolvedLanguage != .simplifiedChinese {
            await Task.yield()
        }

        #expect(store.resolvedLanguage == .simplifiedChinese)
        #expect(store.text("status.ready") == "准备就绪")
    }
}
