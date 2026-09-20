import ResearchRadarCore
import SwiftUI

struct CompactTodayView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    @Bindable var presentation: WindowPresentationState
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Label("ResearchRadar", systemImage: "dot.radiowaves.left.and.right")
                    .font(.system(size: 13, weight: .medium))
                Spacer()
                Button { store.performAction { try store.setWindowMode(.full) } } label: {
                    Image(systemName: "arrow.up.left.and.arrow.down.right")
                }
                .buttonStyle(.glass)
                .help(localization.text("action.full_workspace"))
                .accessibilityLabel(localization.text("action.full_workspace"))
            }.padding(.horizontal, 16).padding(.vertical, 10)
            Divider()
            TodayContentView(store: store, localization: localization, compact: true, configure: {
                if store.performAction({ try store.setWindowMode(.full) }) {
                    presentation.requestedSection = .settings
                }
            }) { report in
                if store.performAction({ try store.setWindowMode(.full) }) {
                    store.selectReport(report.id)
                    presentation.requestedReportID = report.id
                }
            }
        }
    }
}

struct TopicSelectionView: View {
    @Bindable var store: AppStore
    let localization: LocalizationStore
    var body: some View {
        Picker(localization.text("nav.topics"), selection: Binding(
            get: { store.selectedTopic?.id ?? "" },
            set: { id in store.performAction { try store.selectTopic(id) } }
        )) {
            ForEach(store.configuration.topics) { topic in Text(topic.displayName).tag(topic.id) }
        }
        .labelsHidden().accessibilityLabel(localization.text("nav.topics"))
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct TodayContentView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    let compact: Bool
    var configure: () -> Void = {}
    let openReport: (ReportRecordV1) -> Void
    @State private var showRunAgain = false
    @State private var showDiagnostics = false

    private var today: TodayPresentation { store.todayPresentation }
    private var report: ReportRecordV1? { today.latestReport }
    private var hasEffectiveAttemptToday: Bool {
        today.latestAttemptReport?.reportDate == Self.reportDate()
            && today.latestAttemptReport?.isEffectiveDeepReport == true
    }
    private var isResearchActive: Bool { today.job.map { $0.kind == .research && [.running, .cancelling, .pending].contains($0.state) } ?? false }
    private var configurationCode: String? { store.isEngineRunning ? nil : store.researchConfigurationErrorCode }
    var showsResearchFailure: Bool { today.researchFailureTime != nil }
    private var emptyTitleKey: String {
        if today.latestAttemptReport != nil { return "today.latest_attempt" }
        if configurationCode != nil { return "today.setup_title" }
        return attentionCode == nil ? "today.start_title" : "today.failed_title"
    }
    var attentionCode: String? {
        today.failureCode ?? configurationCode
            ?? (today.status == .failed ? "engine_failed" : nil)
    }
    var statusKey: String {
        if showsResearchFailure { return today.statusKey }
        if configurationCode != nil && today.latestAttemptReport == nil && !isResearchActive { return "today.failed" }
        return store.isEngineRunning && store.engineStatusPresentation == nil ? "today.checking" : today.statusKey
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    TopicSelectionView(store: store, localization: localization)
                    scheduleLine
                    if let otherID = today.otherActiveTopicID,
                       let topic = store.configuration.topics.first(where: { $0.id == otherID }) {
                        Label(localization.text("today.other_task") + ": " + topic.displayName, systemImage: "waveform.path")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
                if showsResearchFailure {
                    researchFailure
                    if report != nil { Divider() }
                }
                if !showsResearchFailure || report != nil {
                    VStack(alignment: .leading, spacing: 10) {
                        if showsResearchFailure {
                            Text(localization.text("today.last_successful_report"))
                                .font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
                        } else {
                            statusLine
                            if !isResearchActive {
                                ForEach(Array(today.outcomeReasonKeys.enumerated()), id: \.offset) { _, key in
                                    Text(localization.text(key)).font(.system(size: 13)).foregroundStyle(.secondary)
                                }
                                if let key = today.automaticDeliveryExplanationKey {
                                    Text(localization.text(key)).font(.system(size: 13)).foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if today.showsRetainedReport {
                                    Text(localization.text("today.last_successful_report"))
                                        .font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
                                }
                            }
                        }
                        Text(isResearchActive ? (store.selectedTopic?.researchFocus ?? "") : (report?.title ?? localization.text(emptyTitleKey)))
                            .font(.system(size: compact ? 17 : 20, weight: .semibold))
                            .fixedSize(horizontal: false, vertical: true)
                        if let report, !isResearchActive {
                            Text(report.summary).font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(2)
                            Text(report.reportDate).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                        } else if !isResearchActive && attentionCode == nil && today.latestAttemptReport == nil {
                            Text(localization.text("today.start_detail")).foregroundStyle(.secondary)
                        }
                        if let attentionCode, !isResearchActive, !showsResearchFailure {
                            Text(UserFacingErrorCatalog(localization: localization).message(for: attentionCode))
                                .font(.system(size: 13)).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                if let report, !isResearchActive {
                    HStack(spacing: 24) {
                        statistic(report.sourceCount, "label.sources")
                        statistic(report.deepReadCount, "label.deep_reads")
                        statistic(report.publishableClaimCount, "label.publishable_claims")
                    }
                }
                actions
                if today.job?.kind == .research && !compact && !showsResearchFailure {
                    Divider()
                    OperationalTimelineView(stage: today.stage, status: today.status, localization: localization)
                } else if compact, isResearchActive, let stage = today.stage {
                    Label(localization.text("stage.\(stage.rawValue)"), systemImage: "circle.inset.filled")
                        .font(.system(size: 13)).foregroundStyle(.secondary)
                }
                if let report, !report.deliveries.isEmpty {
                    Divider()
                    if let key = today.deliveryHistoryKey {
                        Text(localization.text(key)).font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
                    }
                    DeliveryStatusView(deliveries: report.deliveries, localization: localization)
                }
            }
            .frame(maxWidth: compact ? .infinity : 720, alignment: .leading)
            .padding(compact ? 16 : 20)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .confirmationDialog(localization.text("confirm.run_again"), isPresented: $showRunAgain) {
            Button(localization.text("action.run_again")) {
                Task { await confirmRunAgain() }
            }
        } message: { Text(localization.text("confirm.run_again_detail")) }
    }

    private var researchFailure: some View {
        VStack(alignment: .leading, spacing: 8) {
            statusLine
            Text(localization.text("today.latest_attempt"))
                .font(.system(size: compact ? 17 : 20, weight: .semibold))
            if let time = today.researchFailureTime {
                Text(time, format: .dateTime.year().month().day().hour().minute())
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
            if let stageKey = today.researchFailureStageKey {
                Label(localization.text(stageKey), systemImage: "exclamationmark.circle")
                    .font(.system(size: 13))
            }
            if let code = today.failureCode {
                Text(UserFacingErrorCatalog(localization: localization).message(for: code))
                    .font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Button { showRunAgain = true } label: {
                    Label(localization.text("action.retry_research"), systemImage: "arrow.clockwise")
                }
                .buttonStyle(.glassProminent)
                .disabled(store.behaviorChangesBlocked || configurationCode != nil || store.selectedTopic?.isPaused == true)
                Button { showDiagnostics.toggle() } label: {
                    Label(localization.text("nav.diagnostics"), systemImage: "stethoscope")
                }.buttonStyle(.glass)
            }
            if showDiagnostics, let job = store.jobs.first(where: { $0.id == today.latestResearchJob?.id }) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(localization.text("nav.diagnostics")).font(.subheadline.weight(.medium))
                    Text(job.id.uuidString)
                    if let code = job.error?.code { Text(code) }
                    if let message = job.error?.message { Text(message) }
                }
                .font(.system(size: 12, design: .monospaced))
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
            if configurationCode != nil {
                Button(action: configure) {
                    Label(localization.text("action.configure"), systemImage: "gearshape")
                }.buttonStyle(.glass)
            }
        }
    }

    @ViewBuilder private var scheduleLine: some View {
        if let next = store.schedulePresentation.nextRun {
            HStack(spacing: 5) {
                Image(systemName: "clock")
                Text(localization.text("label.next_run"))
                Text(next, format: .dateTime.month().day().hour().minute()).monospaced()
            }.font(.system(size: 12)).foregroundStyle(.secondary)
        } else {
            Text(localization.text(store.schedulePresentation.localizationKey))
                .font(.system(size: 12)).foregroundStyle(.secondary)
        }
    }

    private var statusLine: some View {
        Label(localization.text(statusKey), systemImage: isResearchActive ? "waveform.path" : attentionCode != nil ? "exclamationmark.circle" : report != nil ? "doc.text" : "sparkle.magnifyingglass")
            .font(.subheadline.weight(.medium)).foregroundStyle(isResearchActive ? .teal : .secondary)
            .accessibilityAddTraits(.updatesFrequently)
    }

    private var actions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) { actionButtons }
            VStack(alignment: .leading, spacing: 12) { actionButtons }
        }
    }

    @ViewBuilder private var actionButtons: some View {
        if let report {
            Button {
                openReport(report)
            } label: { Label(localization.text("action.open_report"), systemImage: "doc.richtext") }
                .buttonStyle(.glassProminent)
        }
        if store.isEngineRunning {
            Button { Task { await store.cancelActiveJob() } } label: {
                Label(localization.text(today.otherActiveTopicID == nil ? "action.cancel" : "action.cancel_active"), systemImage: "stop")
            }.disabled(store.cancellationRequested).buttonStyle(.glass)
            if today.canQueueResearch {
                Button { runNow() } label: {
                    Label(localization.text("action.queue_run"), systemImage: "text.badge.plus")
                }.disabled(store.isShuttingDown || store.requiresReconciliation || store.selectedTopic?.isPaused == true)
                    .buttonStyle(.glass)
            }
        } else if showsResearchFailure {
            // Retry is above the retained report and always uses the confirmed runAgain flow.
        } else if configurationCode != nil {
            Button(action: configure) {
                Label(localization.text("action.configure"), systemImage: "gearshape")
            }.buttonStyle(.glassProminent)
        } else if !compact || !hasEffectiveAttemptToday {
            Button { runNow() } label: {
                Label(localization.text("action.run_now"), systemImage: "play.fill")
            }.disabled(store.isShuttingDown || store.requiresReconciliation || store.selectedTopic?.isPaused == true)
                .buttonStyle(.glass)
            if hasEffectiveAttemptToday, !compact {
                Menu {
                    Button(localization.text("action.run_again")) { showRunAgain = true }
                } label: { Image(systemName: "ellipsis") }
                    .help(localization.text("action.more"))
                    .accessibilityLabel(localization.text("action.more"))
                    .disabled(store.behaviorChangesBlocked || store.selectedTopic?.isPaused == true)
            }
        }
    }

    private func statistic(_ count: Int, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(count, format: .number).font(.system(size: 17, weight: .medium, design: .monospaced))
            Text(localization.text(label)).font(.system(size: 12)).foregroundStyle(.secondary)
        }.accessibilityElement(children: .combine)
    }

    private func runNow() {
        Task {
            let existingID = hasEffectiveAttemptToday ? report?.id : nil
            await store.runSelectedTopicNow()
            if let existingID, let selected = store.selectedReport, selected.id == existingID {
                openReport(selected)
            }
        }
    }

    func confirmRunAgain() async {
        guard let topic = store.selectedTopic else { return }
        await store.runAgain(topicID: topic.id, reportDate: Self.reportDate(), confirmed: true)
    }

    private static func reportDate() -> String {
        let formatter = DateFormatter(); formatter.calendar = .current
        formatter.dateFormat = "yyyy-MM-dd"; return formatter.string(from: Date())
    }
}

struct OperationalTimelineView: View {
    let stage: ResearchStage?
    let status: TodayStatus
    let localization: LocalizationStore
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(localization.text("label.research_progress")).font(.subheadline.weight(.medium))
            ForEach(ResearchStage.allCases, id: \.rawValue) { item in
                let active = stage == item
                let stopped = [.failed, .cancelled, .interrupted].contains(status)
                HStack(spacing: 10) {
                    Image(systemName: active ? (stopped ? "exclamationmark.circle" : "circle.inset.filled") : status == .succeeded ? "checkmark.circle" : "circle")
                        .frame(width: 18)
                    Text(localization.text("stage.\(item.rawValue)"))
                    Spacer()
                    if active { Text(localization.text(stopped ? "timeline.stopped" : "timeline.current")).font(.system(size: 12)) }
                }
                .font(.callout).foregroundStyle(active ? (stopped ? Color.orange : Color.teal) : Color.secondary)
                .frame(minHeight: 22)
                .accessibilityElement(children: .combine)
            }
        }
    }
}

struct DeliveryStatusView: View {
    let deliveries: [DeliveryRecordV1]
    let localization: LocalizationStore
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(deliveries, id: \.channel) { delivery in
                HStack(alignment: .top, spacing: 10) {
                    Label(localization.text(delivery.channel == .wechat ? "setting.wechat" : "setting.email"), systemImage: delivery.channel == .wechat ? "bubble.left.and.text.bubble.right" : "envelope")
                    Spacer(minLength: 8)
                    Text(localization.text("delivery.\(delivery.state.rawValue)"))
                        .multilineTextAlignment(.trailing)
                }.font(.callout).foregroundStyle(.secondary).accessibilityElement(children: .combine)
                if delivery.state == .unknown {
                    Text(localization.text("delivery.unknown_detail")).font(.system(size: 12)).foregroundStyle(.secondary)
                }
            }
        }
    }
}
