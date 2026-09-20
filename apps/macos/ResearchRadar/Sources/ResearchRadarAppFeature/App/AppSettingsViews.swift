import AppKit
import ResearchRadarCore
import SwiftUI

struct AppLanguagePicker: View {
    let store: AppStore
    let localization: LocalizationStore

    var body: some View {
        Picker(localization.text("language.picker_label"), selection: Binding(
            get: { store.configuration.uiLanguage },
            set: { value in
                if store.performAction({ try store.setUILanguage(value) }) {
                    localization.preference = value
                }
            }
        )) {
            Text(localization.text("language.system")).tag(AppLanguagePreference.system)
            Text("简体中文").tag(AppLanguagePreference.simplifiedChinese)
            Text("English").tag(AppLanguagePreference.english)
        }
    }
}

struct AppActionErrorView: View {
    let store: AppStore
    let localization: LocalizationStore

    var body: some View {
        if let code = store.lastErrorCode {
            let key = "error.\(code)"
            let message = localization.text(key)
            Label(message == key ? localization.text("error.generic") : message,
                  systemImage: "exclamationmark.triangle")
                .foregroundStyle(.orange)
                .textSelection(.enabled)
                .accessibilityIdentifier("action-error")
        }
    }
}

struct ProviderSettingsView: View {
    let store: AppStore
    let localization: LocalizationStore
    var onboarding = false
    @State private var credentials = ProviderCredentialDraft()
    @State private var detectedCodex: URL?
    @State private var confirmFallback = false

    var body: some View {
        Section(localization.text("onboarding.providers")) {
            Text(localization.text("setting.deepseek_purpose")).font(.callout).foregroundStyle(.secondary)
            Text(localization.text("setting.deepseek_fees")).font(.callout).foregroundStyle(.secondary)
            Link(localization.text("action.manage_api_key"), destination: URL(string: "https://platform.deepseek.com/api_keys")!)
            SecureField(localization.text(store.secretPresence["deepseek.api_key"] == true
                ? "setting.replace_key" : "setting.deepseek_key"), text: $credentials.deepSeekKey)
            secretStatus("DeepSeek", name: "deepseek.api_key")
            Button(localization.text("action.save_deepseek")) {
                store.performAction { try credentials.saveDeepSeek { try store.saveSecret(name: $0, value: $1) } }
            }.disabled(credentials.deepSeekKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.behaviorChangesBlocked)
            Text(localization.text("setting.tavily_purpose")).font(.callout).foregroundStyle(.secondary)
            Text(localization.text("setting.tavily_fees")).font(.callout).foregroundStyle(.secondary)
            Link(localization.text("action.manage_api_key"), destination: URL(string: "https://app.tavily.com/")!)
            SecureField(localization.text(store.secretPresence["web_search.api_key"] == true
                ? "setting.replace_key" : "setting.tavily_key"), text: $credentials.searchKey)
            secretStatus("Tavily", name: "web_search.api_key")
            Button(localization.text("action.save_tavily")) {
                store.performAction { try credentials.saveSearch { try store.saveSecret(name: $0, value: $1) } }
            }.disabled(credentials.searchKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.behaviorChangesBlocked)
            Text(localization.text("status.saved_not_verified")).font(.callout).foregroundStyle(.secondary)
            Button(localization.text("action.refresh_credentials"), systemImage: "arrow.clockwise") {
                store.refreshSecretPresence()
            }
            .disabled(store.behaviorChangesBlocked)
            LabeledContent("Codex", value: localization.text(SettingsPresentation.codexStatusKey(
                isExecutable: store.codexExecutableAvailable
            )))
            HStack {
                if let detectedCodex {
                    Button(localization.text("action.use_detected_codex")) {
                        if store.performAction({ try store.setCodexExecutable(detectedCodex.path) }) {
                            self.detectedCodex = nil
                        }
                    }
                }
                DisclosureGroup(localization.text("setting.codex_advanced")) {
                    Button(localization.text("action.select_codex")) {
                        let panel = NSOpenPanel()
                        panel.canChooseDirectories = false
                        panel.canChooseFiles = true
                        panel.allowsMultipleSelection = false
                        if panel.runModal() == .OK, let url = panel.url {
                            if store.performAction({ try store.setCodexExecutable(url.path) }) { detectedCodex = nil }
                        }
                    }
                }
            }
            .disabled(store.behaviorChangesBlocked)
            Picker(localization.text("setting.verifier"), selection: Binding(
                get: { store.configuration.routes.first(where: { $0.task == "verifier" })?.providerID ?? "" },
                set: { provider in
                    if provider == "deepseek" { confirmFallback = true }
                    else if provider == "codex" { store.performAction { try store.useCodexVerifier() } }
                }
            )) {
                Text(localization.text("setting.codex_recommended")).tag("codex")
                Text("DeepSeek").tag("deepseek")
                if let provider = store.configuration.routes.first(where: { $0.task == "verifier" })?.providerID,
                   provider != "codex", provider != "deepseek" {
                    Text(localization.text("status.verifier_custom")).tag(provider)
                } else if !store.configuration.routes.contains(where: { $0.task == "verifier" }) {
                    Text(localization.text("status.not_configured")).tag("")
                }
            }
            .disabled(store.behaviorChangesBlocked)
            if let route = store.configuration.routes.first(where: { $0.task == "verifier" }) {
                Text("\(route.providerID) · \(route.model) · \(store.configuration.providers.first(where: { $0.id == route.providerID })?.reasoningEffort ?? "—")")
                    .font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                if route.providerID == "codex" {
                    if onboarding {
                        DisclosureGroup(localization.text("setting.codex_advanced")) { effortPicker }
                    } else { effortPicker }
                }
            }
            Text(localization.text("setting.codex_connection_detail")).font(.callout).foregroundStyle(.secondary)
            if !onboarding { ConnectionChecksView(store: store, localization: localization) }
        }
        .onAppear {
            store.loadSecretPresenceIfNeeded()
            detectedCodex = store.detectedCodexExecutable()
        }
        .confirmationDialog(localization.text("confirm.verifier_fallback"), isPresented: $confirmFallback) {
            Button(localization.text("action.use_deepseek_verifier")) {
                store.performAction { try store.useDeepSeekVerifier() }
            }
        } message: { Text(localization.text("confirm.verifier_fallback_detail")) }
    }

    private var effortPicker: some View {
        Picker(localization.text("setting.reasoning_effort"), selection: Binding(
                        get: { store.configuration.providers.first(where: { $0.id == "codex" })?.reasoningEffort ?? "xhigh" },
                        set: { value in store.performAction { try store.setCodexReasoningEffort(value) } }
                    )) {
                        Text(localization.text("effort.high")).tag("high")
                        Text(localization.text("effort.xhigh")).tag("xhigh")
                        if let effort = store.configuration.providers.first(where: { $0.id == "codex" })?.reasoningEffort,
                           !["high", "xhigh"].contains(effort) { Text(effort).tag(effort) }
                    }.disabled(store.behaviorChangesBlocked)
    }

    private func secretStatus(_ provider: String, name: String) -> some View {
        LabeledContent(provider, value: localization.text(
            store.secretPresence[name].map { $0 ? "status.key_saved" : "status.key_missing" } ?? "status.key_unknown"
        ))
    }
}

struct ProviderCredentialDraft {
    var deepSeekKey = ""
    var searchKey = ""

    mutating func saveDeepSeek(_ persist: (String, String) throws -> Void) throws {
        try persist("deepseek.api_key", deepSeekKey)
        deepSeekKey = ""
    }

    mutating func saveSearch(_ persist: (String, String) throws -> Void) throws {
        try persist("web_search.api_key", searchKey)
        searchKey = ""
    }

    mutating func save(_ persist: (String, String) throws -> Void) throws {
        if !deepSeekKey.isEmpty { try persist("deepseek.api_key", deepSeekKey) }
        if !searchKey.isEmpty { try persist("web_search.api_key", searchKey) }
        deepSeekKey = ""
        searchKey = ""
    }
}

enum SettingsPresentation {
    static func codexStatusKey(isExecutable: Bool) -> String {
        isExecutable ? "status.codex_found" : "status.not_configured"
    }

    static func checkLabelKey(id: String) -> String {
        switch id {
        case "engine", "topic_bootstrap", "source_gist", "deep_reading", "anchor_repair", "report_localization", "verifier", "web_search":
            return "check.name.\(id)"
        default:
            return "check.name.generic"
        }
    }

    static func failureDetailKey(for check: PreflightCheckV1) -> String? {
        guard [.actionRequired, .unavailable].contains(check.status) else { return nil }
        return check.id == "web_search" ? "check.failure.web_search" : "check.failure.provider"
    }

    static func providerName(_ id: String?) -> String? {
        switch id {
        case "deepseek": "DeepSeek"
        case "codex": "Codex"
        case "tavily": "Tavily"
        default: nil
        }
    }
}

struct CacheLimitView: View {
    let store: AppStore
    let localization: LocalizationStore
    @State private var enabled: Bool
    @State private var amount: String
    @State private var unit: CacheLimitInput.Unit

    init(store: AppStore, localization: LocalizationStore) {
        self.store = store; self.localization = localization
        _enabled = State(initialValue: store.configuration.storage.modelCacheLimitBytes != nil)
        let display = CacheLimitInput.display(bytes: store.configuration.storage.modelCacheLimitBytes)
        _amount = State(initialValue: display.amount)
        _unit = State(initialValue: display.unit)
    }

    var body: some View {
        Toggle(localization.text("setting.cache_limit"), isOn: $enabled)
            .disabled(store.behaviorChangesBlocked)
        if enabled {
            HStack {
                TextField(localization.text("setting.cache_amount"), text: $amount)
                Picker(localization.text("setting.cache_unit"), selection: $unit) {
                    Text("MB").tag(CacheLimitInput.Unit.megabytes)
                    Text("GB").tag(CacheLimitInput.Unit.gigabytes)
                }.fixedSize()
            }
            .disabled(store.behaviorChangesBlocked)
        }
        Button(localization.text("action.save")) {
            store.performAction {
                let limit = try CacheLimitInput.parse(enabled: enabled, amount: amount, unit: unit)
                try store.setCacheLimit(limit)
            }
        }
        .disabled(store.behaviorChangesBlocked)
    }
}

enum CacheLimitInput {
    enum Unit: String {
        case megabytes, gigabytes

        var multiplier: UInt64 { self == .megabytes ? 1_000_000 : 1_000_000_000 }
    }

    static func display(bytes: UInt64?) -> (amount: String, unit: Unit) {
        guard let bytes else { return ("1", .gigabytes) }
        let unit: Unit = bytes >= 1_000_000_000 ? .gigabytes : .megabytes
        let value = Decimal(bytes) / Decimal(unit.multiplier)
        return (NSDecimalNumber(decimal: value).stringValue, unit)
    }

    static func parse(enabled: Bool, amount: String, unit: Unit) throws -> UInt64? {
        guard enabled else { return nil }
        let text = amount.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.range(of: #"^[0-9]+(?:\.[0-9]+)?$"#, options: .regularExpression) != nil,
              let number = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")) else {
            throw DurableStateValidationError.invalidValue
        }
        // Decimal avoids rounding persisted byte caps through floating point.
        let bytes = number * Decimal(unit.multiplier)
        return try parse(enabled: true, bytes: NSDecimalNumber(decimal: bytes).stringValue)
    }

    static func parse(enabled: Bool, bytes: String) throws -> UInt64? {
        guard enabled else { return nil }
        guard let value = UInt64(bytes.trimmingCharacters(in: .whitespacesAndNewlines)), value > 0 else {
            throw DurableStateValidationError.invalidValue
        }
        return value
    }
}
