import AppKit
import ResearchRadarCore
import SwiftUI

struct TopicOnboardingView: View {
    @Bindable var store: AppStore
    @Bindable var localization: LocalizationStore
    @State private var description = ""
    @State private var reportLanguage: ReportLanguageV1 = .chinese
    @State private var languageInitialized = false
    @State private var reportLanguageEdited = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                Text("\(stepNumber) / 4 · \(localization.text(stepTitle))")
                    .font(.headline).accessibilityIdentifier("onboarding-step")
                Divider()
                switch store.onboardingPage {
                case .storage:
                    AppAppearancePicker(store: store, localization: localization)
                    AppLanguagePicker(store: store, localization: localization)
                case .providers:
                    ProviderSettingsView(store: store, localization: localization, onboarding: true)
                case .topicDescription:
                    if let topic = store.selectedTopic {
                        TopicEditorView(store: store, localization: localization, topic: topic)
                            .frame(minHeight: 460)
                    } else { topicSetup }
                default:
                    readyToStart
                }
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(20)
        }
        .safeAreaInset(edge: .bottom) { navigation.padding(16).background(.bar) }
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

    private var stepNumber: Int {
        switch store.onboardingPage {
        case .storage: 1
        case .providers: 2
        case .topicDescription: 3
        default: 4
        }
    }

    private var stepTitle: String {
        switch store.onboardingPage {
        case .storage: "onboarding.preferences"
        case .providers: "onboarding.providers"
        case .topicDescription: "onboarding.topic"
        default: "onboarding.ready"
        }
    }

    private var navigation: some View {
        HStack {
            if stepNumber > 1 {
                Button(localization.text("action.back"), systemImage: "chevron.left") {
                    let steps: [OnboardingStep] = [.storage, .providers, .topicDescription]
                    store.performAction { try store.setOnboardingStep(steps[stepNumber - 2]) }
                }
            }
            Spacer()
            if stepNumber < 4 {
                Button(localization.text("action.continue")) {
                    let steps: [OnboardingStep] = [.providers, .topicDescription, .preflight]
                    store.performAction { try store.setOnboardingStep(steps[stepNumber - 1]) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(stepNumber == 3 && store.configuration.topics.isEmpty)
            } else {
                Button(localization.text("action.finish_setup")) {
                    store.performAction { try store.completeOnboarding() }
                }
                Button(localization.text("action.start_first_research"), systemImage: "play.fill") {
                    Task { await store.startOnboardingResearch() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(store.researchConfigurationErrorCode != nil || store.selectedTopic?.isPaused != false)
            }
        }.disabled(store.behaviorChangesBlocked)
    }

    private var readyToStart: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let topic = store.selectedTopic {
                LabeledContent(localization.text("onboarding.topic"), value: topic.displayName)
                LabeledContent(localization.text("label.research_focus"), value: topic.researchFocus)
                LabeledContent(localization.text("label.report_language"), value: topic.reportLanguage == .chinese ? "中文" : "English")
                LabeledContent(localization.text("onboarding.deep_read_count"), value: String(topic.deepReadLimit))
            }
            ForEach(store.configuration.routes, id: \.task) { route in
                LabeledContent(localization.text(SettingsPresentation.checkLabelKey(id: route.task)),
                    value: "\(route.providerID) · \(route.model)")
            }
            LabeledContent(localization.text("check.name.web_search"),
                value: store.configuration.discovery.webSearchProvider ?? localization.text("status.not_configured"))
            Text(localization.text("onboarding.optional_delivery")).foregroundStyle(.secondary)
            if let code = store.researchConfigurationErrorCode {
                Label(UserFacingErrorCatalog(localization: localization).message(for: code), systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
            }
            Divider()
            ConnectionChecksView(store: store, localization: localization)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(localization.text("onboarding.title"), systemImage: "dot.radiowaves.left.and.right")
                .font(.system(size: 20, weight: .semibold))
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
