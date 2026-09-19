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
    @State private var deepSeekKey = ""
    @State private var searchKey = ""
    @State private var confirmFallback = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(localization.text("onboarding.providers")).font(.headline)
            SecureField("DeepSeek API key", text: $deepSeekKey)
            SecureField("Tavily API key", text: $searchKey)
            ForEach(["deepseek.api_key", "web_search.api_key"], id: \.self) { name in
                LabeledContent(name, value: localization.text(store.secretPresence[name].map { $0 ? "status.key_saved" : "status.key_missing" } ?? "status.key_unknown"))
            }
            Button(localization.text("action.save_secrets")) {
                if store.performAction({
                    if !deepSeekKey.isEmpty { try store.saveSecret(name: "deepseek.api_key", value: deepSeekKey) }
                    if !searchKey.isEmpty { try store.saveSecret(name: "web_search.api_key", value: searchKey) }
                }) { deepSeekKey = ""; searchKey = "" }
            }
            .disabled((deepSeekKey.isEmpty && searchKey.isEmpty) || store.behaviorChangesBlocked)
            LabeledContent("Codex", value: store.configuration.providers.first(where: { $0.id == "codex" })?.commandPath ?? localization.text("status.not_configured"))
                .textSelection(.enabled)
            HStack {
                Button(localization.text("action.select_codex")) {
                    let panel = NSOpenPanel()
                    panel.canChooseDirectories = false
                    panel.canChooseFiles = true
                    panel.allowsMultipleSelection = false
                    if panel.runModal() == .OK, let url = panel.url {
                        store.performAction { try store.setCodexExecutable(url.path) }
                    }
                }
                Button(localization.text("action.use_codex_verifier")) {
                    store.performAction { try store.useCodexVerifier() }
                }
                Button(localization.text("action.use_deepseek_verifier")) { confirmFallback = true }
            }
            .disabled(store.behaviorChangesBlocked)
            Button(localization.text("action.test_connections")) { Task { await store.testConnections() } }
                .disabled(store.behaviorChangesBlocked)
            if let preflight = store.preflight {
                Text(localization.text("status.preflight_scope")).font(.callout).foregroundStyle(.secondary)
                ForEach(preflight.checks, id: \.id) { check in
                    LabeledContent(check.id, value: "\(check.provider ?? "") · \(localization.text("check.\(check.status.rawValue)"))")
                }
            }
        }
        .onAppear { store.refreshSecretPresence() }
        .confirmationDialog(localization.text("confirm.verifier_fallback"), isPresented: $confirmFallback) {
            Button(localization.text("action.use_deepseek_verifier")) {
                store.performAction { try store.useDeepSeekVerifier() }
            }
        } message: { Text(localization.text("confirm.verifier_fallback_detail")) }
    }
}

struct CacheLimitView: View {
    let store: AppStore
    let localization: LocalizationStore
    @State private var enabled: Bool
    @State private var bytes: String

    init(store: AppStore, localization: LocalizationStore) {
        self.store = store; self.localization = localization
        _enabled = State(initialValue: store.configuration.storage.modelCacheLimitBytes != nil)
        _bytes = State(initialValue: store.configuration.storage.modelCacheLimitBytes.map(String.init) ?? "")
    }

    var body: some View {
        Toggle(localization.text("setting.cache_limit"), isOn: $enabled)
        if enabled { TextField(localization.text("label.bytes"), text: $bytes) }
        Button(localization.text("action.save")) {
            store.performAction {
                let limit = try CacheLimitInput.parse(enabled: enabled, bytes: bytes)
                try store.setCacheLimit(limit)
            }
        }
        .disabled(store.behaviorChangesBlocked)
    }
}

enum CacheLimitInput {
    static func parse(enabled: Bool, bytes: String) throws -> UInt64? {
        guard enabled else { return nil }
        guard let value = UInt64(bytes.trimmingCharacters(in: .whitespacesAndNewlines)), value > 0 else {
            throw DurableStateValidationError.invalidValue
        }
        return value
    }
}
