import AppKit
import ResearchRadarCore
import SwiftUI

public struct ResearchRadarRootView: View {
    @Bindable private var store: AppStore
    @Bindable private var localization: LocalizationStore

    public init(store: AppStore, localization: LocalizationStore) {
        self.store = store; self.localization = localization
    }

    public var body: some View {
        Group {
            if store.configuration.topics.isEmpty {
                TopicOnboardingView(store: store, localization: localization)
            } else {
                ResearchWorkspaceView(store: store, localization: localization)
            }
        }
        .safeAreaInset(edge: .bottom) {
            AppActionErrorView(store: store, localization: localization).padding(8)
        }
        .frame(minWidth: 720, minHeight: 520)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

private struct TopicOnboardingView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    @State private var description = ""
    @State private var reportLanguage: ReportLanguageV1 = .chinese
    @State private var languageInitialized = false
    @State private var reportLanguageEdited = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header
                AppLanguagePicker(store: store, localization: localization)
                Divider()
                ProviderSettingsView(store: store, localization: localization)
                Divider()
                topicSetup
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(32)
        }
        .onAppear {
            if !languageInitialized {
                reportLanguage = TopicEditorInput.reportLanguage(for: localization.resolvedLanguage)
                languageInitialized = true
            }
        }
        .onChange(of: localization.resolvedLanguage) { _, language in
            if !reportLanguageEdited { reportLanguage = TopicEditorInput.reportLanguage(for: language) }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(localization.text("onboarding.title"), systemImage: "dot.radiowaves.left.and.right")
                .font(.title2.weight(.semibold))
            Text(localization.text("onboarding.subtitle"))
                .foregroundStyle(.secondary)
        }
    }

    private var topicSetup: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(localization.text("onboarding.topic")).font(.headline)
            Text(localization.text("onboarding.topic_detail"))
                .font(.callout).foregroundStyle(.secondary)
            TextEditor(text: $description)
                .font(.body)
                .frame(minHeight: 84)
                .padding(8)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
                .overlay { RoundedRectangle(cornerRadius: 6).stroke(.separator) }
            Picker(localization.text("label.report_language"), selection: Binding(
                get: { reportLanguage },
                set: { reportLanguage = $0; reportLanguageEdited = true }
            )) {
                Text("中文").tag(ReportLanguageV1.chinese)
                Text("English").tag(ReportLanguageV1.english)
            }
            .pickerStyle(.segmented).frame(width: 240)
            if let draft = store.topicDraft {
                topicReview(draft)
            } else {
                Button(localization.text("action.generate_topic")) {
                    Task { await store.bootstrapTopic(description: description, language: reportLanguage) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isEngineRunning)
            }
        }
    }

    private func topicReview(_ draft: TopicDraftV1) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            TopicEditorView(store: store, localization: localization, topic: TopicRecordV1(
                id: draft.id, displayName: draft.displayName, researchFocus: draft.researchFocus,
                queries: draft.queries, paperQueries: draft.paperQueries, webQueries: draft.webQueries,
                exclusionTerms: draft.exclusionTerms, requiredPhrases: draft.requiredPhrases,
                conceptGroups: draft.conceptGroups, negativePhrases: draft.negativePhrases,
                prioritySources: draft.prioritySources, sourceIntent: draft.sourceIntent,
                reportLanguage: draft.reportLanguage
            ), creating: true).id(store.topicDraftRevision).frame(minHeight: 580)
            if !draft.warnings.isEmpty {
                Text(draft.warnings.joined(separator: "\n")).font(.callout).foregroundStyle(.orange)
            }
            HStack {
                Button(localization.text("action.regenerate")) {
                    Task { await store.bootstrapTopic(description: description, language: reportLanguage) }
                }
            }
        }
        .padding(.top, 8)
    }

}

private enum WorkspaceSection: String, CaseIterable, Identifiable {
    case overview, topics, reports, settings, diagnostics
    var id: String { rawValue }
}

private struct ResearchWorkspaceView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    @State private var section: WorkspaceSection = .overview
    @State private var showClearCacheConfirmation = false
    @State private var showRunAgainConfirmation = false

    var body: some View {
        NavigationSplitView {
            List(WorkspaceSection.allCases, selection: $section) { item in
                Label(localization.text("nav.\(item.rawValue)"), systemImage: icon(item))
            }
            .navigationSplitViewColumnWidth(min: 160, ideal: 180)
        } detail: {
            switch section {
            case .overview: overview
            case .topics: TopicsView(store: store, localization: localization)
            case .reports: reportList
            case .settings: settings
            case .diagnostics: diagnostics
            }
        }
        .onChange(of: store.selectedReportID) { _, id in
            if id != nil { section = .reports }
        }
        .confirmationDialog(localization.text("confirm.run_again"), isPresented: $showRunAgainConfirmation) {
            Button(localization.text("action.run_again")) {
                if let topic = selectedTopic {
                    Task { await store.runAgain(topicID: topic.id, reportDate: Self.today(), confirmed: true) }
                }
            }
        } message: { Text(localization.text("confirm.run_again_detail")) }
        .confirmationDialog(
            localization.text("confirm.clear_cache"),
            isPresented: $showClearCacheConfirmation
        ) {
            Button(localization.text("action.clear_cache"), role: .destructive) { store.clearModelCache() }
            Button(localization.text("action.cancel"), role: .cancel) {}
        } message: {
            Text(localization.text("confirm.clear_cache_detail"))
        }
    }

    private var overview: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(localization.text("nav.overview")).font(.title2.weight(.semibold))
            if let topic = selectedTopic {
                VStack(alignment: .leading, spacing: 5) {
                    Text(topic.displayName).font(.title3.weight(.medium))
                    Text(topic.researchFocus).foregroundStyle(.secondary)
                }
                HStack {
                    Button {
                        Task { await store.runNow(topicID: topic.id, reportDate: Self.today()) }
                    } label: {
                        Label(localization.text("action.run_now"), systemImage: "play.fill")
                    }
                    .buttonStyle(.borderedProminent).disabled(store.isShuttingDown || topic.isPaused)
                    if store.reports.contains(where: { $0.topicID == topic.id && $0.reportDate == Self.today() }) {
                        Button(localization.text("action.run_again")) { showRunAgainConfirmation = true }
                            .disabled(store.behaviorChangesBlocked || topic.isPaused)
                    }
                    if store.isEngineRunning {
                        ProgressView().controlSize(.small)
                        Button(localization.text("action.cancel")) {
                            Task { await store.cancelActiveJob() }
                        }
                        .disabled(store.cancellationRequested)
                    }
                }
            }
            Divider()
            Text(localization.text("label.recent_report")).font(.headline)
            if let report = store.reports.first {
                Text(report.title).font(.headline)
                Text(report.summary).foregroundStyle(.secondary).lineLimit(3)
            } else {
                Text(localization.text("empty.reports")).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(28)
    }

    private var reportList: some View {
        List(store.reports, selection: Binding(get: { store.selectedReportID }, set: { store.selectReport($0) })) { report in
            VStack(alignment: .leading, spacing: 4) {
                Text(report.title).font(.headline)
                Text(report.reportDate).font(.caption).foregroundStyle(.secondary)
                Text(report.summary).lineLimit(3).foregroundStyle(.secondary)
                LabeledContent(
                    localization.text("label.publishable_claims"),
                    value: "\(report.publishableClaimCount)"
                )
                .font(.caption)
            }
            .padding(.vertical, 6)
        }
        .overlay {
            if store.reports.isEmpty {
                ContentUnavailableView(localization.text("empty.reports"), systemImage: "doc.text")
            }
        }
    }

    private var settings: some View {
        ScrollView { Form {
            AppLanguagePicker(store: store, localization: localization)
            ProviderSettingsView(store: store, localization: localization)
            Toggle(localization.text("setting.pause_schedules"), isOn: Binding(
                get: { store.runtime.schedulesPaused },
                set: { value in store.performAction { try store.setSchedulesPaused(value) } }
            ))
            .disabled(store.behaviorChangesBlocked)
            Toggle(localization.text("setting.start_at_login"), isOn: Binding(
                get: { store.configuration.startAtLogin },
                set: { value in Task { await store.setStartAtLogin(value) } }
            ))
            .disabled(store.behaviorChangesBlocked)
            DeliveryConfigurationView(store: store, localization: localization)
                .disabled(store.behaviorChangesBlocked)
            ScheduleEditorView(store: store, localization: localization)
                .id(selectedTopic?.id)
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
                }
                HStack {
                    Button(localization.text("action.refresh_storage")) { store.refreshStorageUsage() }
                    Button(localization.text("action.clear_cache"), role: .destructive) {
                        showClearCacheConfirmation = true
                    }
                    .disabled(store.behaviorChangesBlocked)
                }
            }
        }.formStyle(.grouped).padding(20) }
    }

    private var diagnostics: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(localization.text("nav.diagnostics")).font(.title2.weight(.semibold))
            LabeledContent("Jobs", value: "\(store.jobs.count)")
            LabeledContent("Reports", value: "\(store.reports.count)")
            if let error = store.lastErrorCode {
                Text(error).font(.system(.body, design: .monospaced)).textSelection(.enabled)
            } else {
                Text(localization.text("diagnostics.none")).foregroundStyle(.secondary)
            }
            Spacer()
        }.padding(28)
    }

    private var selectedTopic: TopicRecordV1? {
        let selected = store.runtime.selectedTopicID
        return store.configuration.topics.first(where: { $0.id == selected }) ?? store.configuration.topics.first
    }

    private func icon(_ section: WorkspaceSection) -> String {
        switch section {
        case .overview: "gauge"
        case .topics: "list.bullet"
        case .reports: "doc.text"
        case .settings: "gearshape"
        case .diagnostics: "stethoscope"
        }
    }

    private static func today() -> String {
        let formatter = DateFormatter(); formatter.calendar = .current
        formatter.dateFormat = "yyyy-MM-dd"; return formatter.string(from: Date())
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
            TextField("thumb_media_id", text: $thumbMediaID)
            SecureField("WeChat App ID", text: $appID)
            SecureField("WeChat App Secret", text: $appSecret)
            Button(localization.text("action.save_wechat")) {
                if store.performAction({ try store.configureWeChat(
                    enabled: wechatEnabled, author: author, thumbMediaID: thumbMediaID,
                    appID: appID, appSecret: appSecret
                ) }) { appID = ""; appSecret = "" }
            }
        }
        Section(localization.text("setting.email")) {
            Toggle(localization.text("setting.enable_email"), isOn: $emailEnabled)
            TextField("SMTP host", text: $smtpHost)
            TextField("SMTP port", value: $smtpPort, format: .number)
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
