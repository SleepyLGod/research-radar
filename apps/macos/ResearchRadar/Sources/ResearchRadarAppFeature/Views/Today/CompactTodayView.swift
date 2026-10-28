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
        today.latestAttemptReport?.reportDate == ReportDate.string(for: Date())
            && today.latestAttemptReport?.isEffectiveDeepReport == true
    }
    private var isResearchActive: Bool { today.researchProgress.isActive }
    private var configurationCode: String? { store.isEngineRunning ? nil : store.researchConfigurationErrorCode }
    var showsAttemptDetails: Bool {
        !today.prefersReportFirst || configurationCode != nil || store.isEngineRunning
            || !store.selectedTopicPaperProgress.isEmpty
    }
    var showsResearchFailure: Bool { today.researchFailureTime != nil }
    var attentionCode: String? {
        today.failureCode ?? configurationCode
            ?? (today.status == .failed ? "engine_failed" : nil)
    }
    var statusKey: String {
        if showsResearchFailure { return today.statusKey }
        if configurationCode != nil && today.latestAttemptReport == nil && !isResearchActive { return "today.failed" }
        return store.isEngineRunning && store.engineStatusPresentation == nil ? "today.checking" : today.researchProgress.statusKey
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: compact ? 16 : 24) {
                VStack(alignment: .leading, spacing: 8) {
                    TopicSelectionView(store: store, localization: localization)
                    scheduleLine
                    if let otherID = today.otherActiveTopicID,
                       let topic = store.configuration.topics.first(where: { $0.id == otherID }) {
                        Label(localization.text("today.other_task") + ": " + topic.displayName, systemImage: "waveform.path")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                    if let focus = today.topic?.researchFocus, !focus.isEmpty {
                        if !compact {
                            Text(localization.text("label.research_focus"))
                                .font(.system(size: 12)).foregroundStyle(.secondary).padding(.top, 8)
                        }
                        Text(focus)
                            .font(.system(size: compact ? 18 : 22, weight: .medium))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Divider()
                if today.prefersReportFirst, let report {
                    reportSummary(report)
                    if showsAttemptDetails { Divider() }
                }
                if showsAttemptDetails { attemptDetails }
                if !today.prefersReportFirst, let report {
                    Divider()
                    reportSummary(report)
                }
            }
            .frame(maxWidth: compact ? .infinity : 760, alignment: .leading)
            .padding(compact ? 16 : 20)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .background(Color(nsColor: .textBackgroundColor))
        .confirmationDialog(localization.text("confirm.run_again"), isPresented: $showRunAgain) {
            Button(localization.text("action.run_again")) {
                Task { await confirmRunAgain() }
            }
        } message: { Text(localization.text("confirm.run_again_detail")) }
    }

    private var attemptDetails: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(localization.text(today.researchProgress.hasAttempt ? "today.latest_attempt" : "home.research"))
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if let time = today.researchProgress.attemptDate, !compact {
                    Text(time, format: .dateTime.month().day().hour().minute())
                        .font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                }
            }
            if showsResearchFailure {
                researchFailure
            } else {
                statusLine
                if let key = today.researchProgress.detailKey {
                    Text(localization.text(key)).font(.system(size: 13)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !isResearchActive {
                    ForEach(Array(today.outcomeReasonKeys.enumerated()), id: \.offset) { _, key in
                        Text(localization.text(key)).font(.system(size: 13)).foregroundStyle(.secondary)
                    }
                    if let key = today.automaticDeliveryExplanationKey {
                        Text(localization.text(key)).font(.system(size: 13)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let attentionCode {
                        Text(UserFacingErrorCatalog(localization: localization).message(for: attentionCode))
                            .font(.system(size: 13)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            ResearchProgressView(progress: today.researchProgress, compact: compact, localization: localization)
            actions
            PaperProgressView(rows: store.selectedTopicPaperProgress, compact: compact, localization: localization)
        }
    }

    private var researchFailure: some View {
        VStack(alignment: .leading, spacing: 8) {
            statusLine
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
            .font(.system(size: 15, weight: .medium)).foregroundStyle(isResearchActive ? .teal : .primary)
            .accessibilityAddTraits(.updatesFrequently)
    }

    private var actions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) { actionButtons }
            VStack(alignment: .leading, spacing: 12) { actionButtons }
        }
    }

    @ViewBuilder private var actionButtons: some View {
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
        } else {
            if !hasEffectiveAttemptToday {
                Button { runNow() } label: {
                    Label(localization.text("action.run_now"), systemImage: "play.fill")
                }.disabled(store.isShuttingDown || store.requiresReconciliation || store.selectedTopic?.isPaused == true)
                    .buttonStyle(.glass)
            }
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

    private func reportSummary(_ report: ReportRecordV1) -> some View {
        VStack(alignment: .leading, spacing: compact ? 10 : 12) {
            HStack {
                Text(localization.text(today.reportSectionKey))
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Text(report.reportDate).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
            }
            Text(ReportHeading.title(report: report, topic: today.topic)).font(.system(size: compact ? 13 : 14, weight: .medium))
                .lineLimit(2).help(report.title)
            if !report.summary.isEmpty {
                Text(report.summary).font(.system(size: compact ? 13 : 14)).foregroundStyle(.secondary)
                    .lineLimit(compact ? 2 : 3)
            }
            HStack(spacing: compact ? 20 : 32) {
                statistic(report.sourceCount, "label.sources")
                statistic(report.deepReadCount, "label.deep_reads")
                statistic(report.publishableClaimCount, "label.publishable_claims")
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) {
                    readReportButton(report)
                    if !showsAttemptDetails { actionButtons }
                }
                VStack(alignment: .leading, spacing: 8) {
                    readReportButton(report)
                    if !showsAttemptDetails { actionButtons }
                }
            }
            if !report.deliveries.isEmpty {
                Divider()
                if let key = today.deliveryHistoryKey {
                    Text(localization.text(key)).font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
                }
                DeliveryStatusView(deliveries: report.deliveries, localization: localization)
            }
        }
    }

    private func readReportButton(_ report: ReportRecordV1) -> some View {
        Button { openReport(report) } label: {
            Label(localization.text("action.open_report"), systemImage: "book")
        }
        .buttonStyle(.glassProminent).controlSize(.large)
        .accessibilityIdentifier("today.read_report")
    }

    private func statistic(_ count: Int, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(count, format: .number).font(.system(size: compact ? 18 : 20, weight: .medium, design: .monospaced))
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
        await store.runAgain(topicID: topic.id, reportDate: ReportDate.string(for: Date()), confirmed: true)
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
