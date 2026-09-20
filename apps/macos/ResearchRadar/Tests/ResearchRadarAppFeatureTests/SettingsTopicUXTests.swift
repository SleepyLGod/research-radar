import Foundation
import ResearchRadarCore
import Testing
@testable import ResearchRadarAppFeature

@Suite struct SettingsTopicUXTests {
    @Test func publicSettingsNeverEchoPrivatePathsOrUnknownCheckIDs() {
        let privatePath = FileManager.default.temporaryDirectory.appending(path: "private-fixture/codex").path
        #expect(SettingsPresentation.codexStatusKey(isExecutable: false) == "status.not_configured")
        #expect(SettingsPresentation.codexStatusKey(isExecutable: true) == "status.codex_found")
        for id in ["deepseek.api_key", privatePath, "new_internal_check"] {
            #expect(SettingsPresentation.checkLabelKey(id: id) == "check.name.generic")
            #expect(SettingsPresentation.providerName(id) == nil)
        }
        for id in ["engine", "topic_bootstrap", "source_gist", "deep_reading", "anchor_repair", "report_localization", "verifier"] {
            #expect(SettingsPresentation.checkLabelKey(id: id) == "check.name.\(id)")
        }
        #expect(SettingsPresentation.providerName("deepseek") == "DeepSeek")
        #expect(SettingsPresentation.providerName("codex") == "Codex")
    }

    @Test func cacheUnitsConvertExactlyAndRejectUnsafeValues() throws {
        #expect(try CacheLimitInput.parse(enabled: true, amount: "1.5", unit: .gigabytes) == 1_500_000_000)
        #expect(try CacheLimitInput.parse(enabled: true, amount: " 250 ", unit: .megabytes) == 250_000_000)
        #expect(try CacheLimitInput.parse(enabled: false, amount: "invalid", unit: .megabytes) == nil)
        for value in ["", "0", "-1", "NaN", "1MB", "1.2.3", "0.0000001", "18446744073710"] {
            #expect(throws: DurableStateValidationError.invalidValue) {
                try CacheLimitInput.parse(enabled: true, amount: value, unit: .megabytes)
            }
        }
    }

    @Test func existingCacheCapsRoundTripWithoutRounding() throws {
        for bytes: UInt64 in [1, 1024, 1_500_000_000, UInt64.max] {
            let display = CacheLimitInput.display(bytes: bytes)
            #expect(try CacheLimitInput.parse(enabled: true, amount: display.amount, unit: display.unit) == bytes)
        }
        let disabled = CacheLimitInput.display(bytes: nil)
        #expect(try CacheLimitInput.parse(enabled: false, amount: disabled.amount, unit: disabled.unit) == nil)
    }

    @Test func advancedValidationRevealsHiddenErrorsWithoutChangingDraft() throws {
        var input = TopicEditorInput(topic: topic())
        #expect(!input.hasInvalidAdvancedFields)
        input.topic.displayName = ""
        #expect(!input.hasInvalidAdvancedFields)
        input.queries = " \n"
        #expect(input.hasInvalidAdvancedFields)
        #expect(throws: AppStoreError.invalidTopic) { try input.candidate() }
        #expect(input.queries == " \n")
        input.queries = "memory"
        input.conceptGroups = [ConceptGroupInput(name: "a", phrases: ["x"]), ConceptGroupInput(name: "a", phrases: ["y"])]
        #expect(input.hasInvalidAdvancedFields)
        input.conceptGroups[1].name = "b"
        #expect(!input.hasInvalidAdvancedFields)
        input.conceptGroups[1].phrases = " "
        #expect(input.hasInvalidAdvancedFields)
    }

    @Test func reviewCountsAndCandidatePreserveAdvancedCapabilities() throws {
        var original = topic()
        original.webQueries = ["web"]
        original.requiredPhrases = ["required"]
        original.negativePhrases = [" original "]
        var input = TopicEditorInput(topic: original)
        input.queries = "one\n\ntwo"
        input.exclusions = "exclude\nspam"
        #expect(input.advancedCounts == [2, 1, 0, 2, 1])
        let saved = try input.candidate()
        #expect(saved.webQueries == original.webQueries)
        #expect(saved.requiredPhrases == original.requiredPhrases)
        #expect(saved.negativePhrases == original.negativePhrases)
        #expect(saved.reportLanguage == .chinese)
    }

    private func topic() -> TopicRecordV1 {
        TopicRecordV1(id: "memory", displayName: "Memory", researchFocus: "Recall", queries: ["memory"], paperQueries: ["recall"], reportLanguage: .chinese)
    }
}
