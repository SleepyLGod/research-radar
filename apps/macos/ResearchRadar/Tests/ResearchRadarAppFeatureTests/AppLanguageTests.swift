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
    @MainActor
    @Test func researchOutcomeCopyResolvesWithBoundedClaimsInBothLanguages() {
        let store = LocalizationStore(preference: .english, preferredLanguages: { ["en-US"] })
        let messages: [(String, String, String)] = [
            ("research_reason.no_eligible_papers",
             "No eligible new deep-reading candidates were found in this attempt.",
             "本轮未找到可精读的新候选。"),
            ("today.noNewContent", "Latest attempt: no new deep-reading report",
             "最近一次尝试：未形成新的精读报告"),
            ("today.no_automatic_delivery",
             "This attempt produced no publishable deep read. No automatic WeChat or email delivery tasks were created.",
             "本轮没有可公开精读，未自动创建微信或邮件投递任务。"),
            ("today.automatic_delivery_ineligible",
             "This record has no publishable deep-reading report and is not eligible for new automatic WeChat or email delivery tasks.",
             "这条记录没有可公开的精读报告，不符合自动创建新微信或邮件投递任务的条件。"),
            ("today.historical_delivery", "Previous report delivery status, not this attempt",
             "历史报告投递状态（不是本轮结果）"),
        ]
        for (key, english, _) in messages { #expect(store.text(key) == english) }
        store.preference = .simplifiedChinese
        for (key, _, chinese) in messages { #expect(store.text(key) == chinese) }
    }

    @MainActor
    @Test func everyTypedOutcomeReasonHasEnglishAndChineseResources() {
        let english = LocalizationStore(preference: .english)
        let chinese = LocalizationStore(preference: .simplifiedChinese)
        for reason in ResearchOutcomeV1.Reason.allCases {
            let key = reason.localizationKey
            #expect(!english.text(key).isEmpty && english.text(key) != key)
            #expect(!chinese.text(key).isEmpty && chinese.text(key) != key)
            #expect(english.text(key) != chinese.text(key))
        }
    }

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
