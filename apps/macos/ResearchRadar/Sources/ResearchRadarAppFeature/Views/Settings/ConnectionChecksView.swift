import ResearchRadarCore
import SwiftUI

struct ConnectionChecksView: View {
    let store: AppStore
    let localization: LocalizationStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(localization.text("setting.connection_check_cost"))
                .font(.callout).foregroundStyle(.secondary)
            Button(localization.text("action.test_connections")) { Task { await store.testConnections() } }
                .disabled(store.behaviorChangesBlocked)
            if store.isEngineRunning { ProgressView().controlSize(.small) }
            if let preflight = store.preflight {
                Text(localization.text("status.preflight_scope")).font(.callout).foregroundStyle(.secondary)
                ForEach(Array(preflight.checks.enumerated()), id: \.offset) { _, check in
                    VStack(alignment: .leading, spacing: 4) {
                        LabeledContent(localization.text(SettingsPresentation.checkLabelKey(id: check.id))) {
                            Text([SettingsPresentation.providerName(check.provider),
                                  check.model.map(SettingsPresentation.safeCheckMessage),
                                  localization.text("check.\(check.status.rawValue)")]
                                .compactMap { $0 }.joined(separator: " · "))
                        }
                        if let key = SettingsPresentation.failureDetailKey(for: check) {
                            Label(localization.text(key), systemImage: "exclamationmark.triangle")
                                .foregroundStyle(.red)
                            Text(SettingsPresentation.safeCheckMessage(check.message))
                                .font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                }
            }
        }
    }
}

extension SettingsPresentation {
    /// Defense in depth for the engine's already-redacted diagnostic excerpt.
    static func safeCheckMessage(_ message: String) -> String {
        let patterns = [
            #"(?i)\b[\w.-]*(?:api[_-]?key|secret|token|password)[\"']?\s*[:=]\s*[\"']?[^\s,;\"']+"#,
            #"(?i)\bbearer\s+[^\s,;]+"#,
            #"\b(?:sk|tvly)-[A-Za-z0-9_-]+"#,
            #"(?i)https?://[^\s]+"#,
            #"(?:/(?:Users|private|tmp|var|home)/|~/)[^\s]+"#,
        ]
        var text = message
        for pattern in patterns {
            text = text.replacingOccurrences(of: pattern, with: "[REDACTED]", options: .regularExpression)
        }
        return String(text.prefix(600))
    }
}
