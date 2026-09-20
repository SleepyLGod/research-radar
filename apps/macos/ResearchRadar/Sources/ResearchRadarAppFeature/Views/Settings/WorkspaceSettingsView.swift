import AppKit
import ResearchRadarCore
import SwiftUI

struct WorkspaceSettingsView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    @State private var showClearCacheConfirmation = false
    var body: some View {
        Form {
            Section(localization.text("setting.general")) {
                AppAppearancePicker(store: store, localization: localization)
                AppLanguagePicker(store: store, localization: localization)
            }
            ProviderSettingsView(store: store, localization: localization)
            Section(localization.text("setting.automation")) {
            Toggle(localization.text("setting.pause_schedules"), isOn: Binding(
                get: { store.runtime.schedulesPaused },
                set: { value in store.performAction { try store.setSchedulesPaused(value) } }
            ))
            .disabled(store.behaviorChangesBlocked)
            Text(localization.text("schedule.runtime_contract")).font(.callout).foregroundStyle(.secondary)
            if store.scheduleFaulted || store.requiresReconciliation {
                Button(localization.text("action.recover_schedule"), systemImage: "arrow.clockwise") {
                    Task { await store.recoverScheduling() }
                }.disabled(store.isEngineRunning || store.isShuttingDown)
            }
            Toggle(localization.text("setting.start_at_login"), isOn: Binding(
                get: { store.configuration.startAtLogin },
                set: { value in Task { await store.setStartAtLogin(value) } }
            ))
            .disabled(store.behaviorChangesBlocked)
            }
            DeliveryConfigurationView(store: store, localization: localization)
                .disabled(store.behaviorChangesBlocked)
            ScheduleEditorView(store: store, localization: localization)
                .id(store.selectedTopic?.id)
                .disabled(store.behaviorChangesBlocked)
            Section(localization.text("setting.legacy_history")) {
                Text(localization.text("setting.legacy_history_detail"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Button(localization.text("action.import_history")) {
                    let panel = NSOpenPanel()
                    panel.canChooseDirectories = true
                    panel.canChooseFiles = false
                    panel.allowsMultipleSelection = false
                    if panel.runModal() == .OK, let directory = panel.url {
                        store.importLegacySourceHistory(from: directory)
                    }
                }
                .disabled(store.behaviorChangesBlocked)
            }
            Section(localization.text("setting.storage")) {
                CacheLimitView(store: store, localization: localization)
                if let usage = store.storageUsage {
                    LabeledContent(
                        localization.text("label.model_cache"),
                        value: ByteCountFormatter.string(fromByteCount: Int64(usage.modelCacheBytes), countStyle: .file)
                    )
                    LabeledContent(
                        localization.text("label.reports"),
                        value: ByteCountFormatter.string(fromByteCount: Int64(usage.reportsBytes), countStyle: .file)
                    )
                    LabeledContent(
                        localization.text("label.diagnostics"),
                        value: ByteCountFormatter.string(fromByteCount: Int64(usage.jobDiagnosticsBytes), countStyle: .file)
                    )
                    LabeledContent(localization.text("label.total_storage"), value: ByteCountFormatter.string(fromByteCount: Int64(usage.totalBytes), countStyle: .file))
                }
                HStack {
                    Button(localization.text("action.refresh_storage")) { store.refreshStorageUsage() }
                    Button(localization.text("action.clear_cache"), role: .destructive) {
                        showClearCacheConfirmation = true
                    }
                    .disabled(store.behaviorChangesBlocked)
                }
            }
            .onAppear { store.refreshStorageUsage() }
        }.formStyle(.grouped).padding(20)
        .confirmationDialog(localization.text("confirm.clear_cache"), isPresented: $showClearCacheConfirmation) {
            Button(localization.text("action.clear_cache"), role: .destructive) { store.clearModelCache() }
            Button(localization.text("action.cancel"), role: .cancel) {}
        } message: { Text(localization.text("confirm.clear_cache_detail")) }
    }


}

private struct DeliveryConfigurationView: View {
    let store: AppStore
    let localization: LocalizationStore
    @State private var wechatEnabled: Bool
    @State private var author: String
    @State private var thumbMediaID: String
    @State private var appID = ""
    @State private var appSecret = ""
    @State private var emailEnabled: Bool
    @State private var smtpHost: String
    @State private var smtpPort: Int
    @State private var emailUsername: String
    @State private var emailPassword = ""
    @State private var fromAddress: String
    @State private var toAddress: String

    init(store: AppStore, localization: LocalizationStore) {
        self.store = store; self.localization = localization
        let wechat = store.configuration.delivery.wechat
        let email = store.configuration.delivery.email
        _wechatEnabled = State(initialValue: wechat.enabled); _author = State(initialValue: wechat.author)
        _thumbMediaID = State(initialValue: wechat.thumbMediaID)
        _emailEnabled = State(initialValue: email.enabled); _smtpHost = State(initialValue: email.smtpHost)
        _smtpPort = State(initialValue: email.smtpPort); _emailUsername = State(initialValue: email.username)
        _fromAddress = State(initialValue: email.fromAddress); _toAddress = State(initialValue: email.toAddress)
    }

    var body: some View {
        Section(localization.text("setting.wechat")) {
            Toggle(localization.text("setting.enable_wechat"), isOn: $wechatEnabled)
            TextField(localization.text("label.author"), text: $author)
            TextField(localization.text("label.cover_media"), text: $thumbMediaID)
            SecureField(localization.text("label.wechat_app_id"), text: $appID)
            SecureField(localization.text("label.wechat_app_secret"), text: $appSecret)
            Button(localization.text("action.save_wechat")) {
                if store.performAction({ try store.configureWeChat(
                    enabled: wechatEnabled, author: author, thumbMediaID: thumbMediaID,
                    appID: appID, appSecret: appSecret
                ) }) { appID = ""; appSecret = "" }
            }
        }
        Section(localization.text("setting.email")) {
            Toggle(localization.text("setting.enable_email"), isOn: $emailEnabled)
            TextField(localization.text("label.smtp_host"), text: $smtpHost)
            TextField(localization.text("label.smtp_port"), value: $smtpPort, format: .number)
            TextField(localization.text("label.username"), text: $emailUsername)
            SecureField(localization.text("label.app_password"), text: $emailPassword)
            TextField(localization.text("label.from"), text: $fromAddress)
            TextField(localization.text("label.to"), text: $toAddress)
            Button(localization.text("action.save_email")) {
                if store.performAction({ try store.configureEmail(
                    enabled: emailEnabled, host: smtpHost, port: smtpPort, security: .tls,
                    username: emailUsername, password: emailPassword,
                    from: fromAddress, to: toAddress
                ) }) { emailPassword = "" }
            }
        }
    }
}

private struct ScheduleEditorView: View {
    let store: AppStore
    let localization: LocalizationStore
    @State private var enabled: Bool
    @State private var time: Date

    init(store: AppStore, localization: LocalizationStore) {
        self.store = store
        self.localization = localization
        let topicID = store.runtime.selectedTopicID ?? store.configuration.topics.first?.id
        let schedule = store.schedules.first { $0.topicID == topicID }
        _enabled = State(initialValue: schedule?.isEnabled ?? false)
        let components = DateComponents(hour: schedule?.hour ?? 9, minute: schedule?.minute ?? 0)
        _time = State(initialValue: Calendar.current.date(from: components) ?? Date())
    }

    var body: some View {
        Section(localization.text("setting.schedule")) {
            TopicSelectionView(store: store, localization: localization)
            Text(localization.text(store.schedulePresentation.localizationKey))
                .font(.callout).foregroundStyle(.secondary)
            if let next = store.schedulePresentation.nextRun {
                Text(next, format: .dateTime.month().day().hour().minute()).monospaced()
            }
            if let topicID = resolvedTopicID,
               store.legacyScheduleTopics.contains(topicID) {
                Label(
                    localization.text("warning.legacy_schedule"),
                    systemImage: "exclamationmark.triangle.fill"
                )
                .foregroundStyle(.orange)
            }
            Toggle(localization.text("setting.enable_schedule"), isOn: $enabled)
            DatePicker(localization.text("label.daily_time"), selection: $time, displayedComponents: .hourAndMinute)
            Button(localization.text("action.save_schedule")) {
                guard let topicID = resolvedTopicID else { return }
                let parts = Calendar.current.dateComponents([.hour, .minute], from: time)
                store.saveDailySchedule(
                    topicID: topicID, hour: parts.hour ?? 9, minute: parts.minute ?? 0,
                    enabled: enabled,
                    deliveryChannels: [
                        store.configuration.delivery.wechat.enabled ? .wechat : nil,
                        store.configuration.delivery.email.enabled ? .email : nil,
                    ].compactMap { $0 }
                )
            }
        }
    }

    private var resolvedTopicID: String? {
        store.runtime.selectedTopicID ?? store.configuration.topics.first?.id
    }
}
