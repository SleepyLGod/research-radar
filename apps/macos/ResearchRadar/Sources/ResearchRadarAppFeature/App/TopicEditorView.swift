import Foundation
import ResearchRadarCore
import SwiftUI

struct ConceptGroupInput: Identifiable {
    let id = UUID()
    var name: String
    var phrases: String
    private let originalPhrases: [String]

    init(name: String = "", phrases: [String] = []) {
        self.name = name
        self.phrases = phrases.joined(separator: "\n")
        originalPhrases = phrases
    }

    var phraseValues: [String] {
        phrases == originalPhrases.joined(separator: "\n") ? originalPhrases : TopicEditorInput.lines(phrases)
    }
}

struct TopicEditorInput {
    var topic: TopicRecordV1
    var queries: String
    var paperQueries: String
    var exclusions: String
    var negativePhrases: String
    var conceptGroups: [ConceptGroupInput]

    init(topic: TopicRecordV1) {
        self.topic = topic
        queries = topic.queries.joined(separator: "\n")
        paperQueries = topic.paperQueries.joined(separator: "\n")
        exclusions = topic.exclusionTerms.joined(separator: "\n")
        negativePhrases = topic.negativePhrases.joined(separator: "\n")
        conceptGroups = topic.conceptGroups.keys.sorted().map {
            ConceptGroupInput(name: $0, phrases: topic.conceptGroups[$0] ?? [])
        }
    }

    func candidate() throws -> TopicRecordV1 {
        guard !hasInvalidAdvancedFields else { throw AppStoreError.invalidTopic }
        var result = topic
        result.displayName = result.displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        result.researchFocus = result.researchFocus.trimmingCharacters(in: .whitespacesAndNewlines)
        result.queries = Self.lines(queries)
        result.paperQueries = Self.lines(paperQueries)
        result.exclusionTerms = Self.lines(exclusions)
        result.negativePhrases = negativePhrases == topic.negativePhrases.joined(separator: "\n")
            ? topic.negativePhrases : Self.lines(negativePhrases)
        result.conceptGroups = [:]
        for group in conceptGroups {
            result.conceptGroups[group.name] = group.phraseValues
        }
        guard !result.displayName.isEmpty, !result.researchFocus.isEmpty else {
            throw AppStoreError.invalidTopic
        }
        return result
    }

    var hasInvalidAdvancedFields: Bool {
        guard !Self.lines(queries).isEmpty, !Self.lines(paperQueries).isEmpty else { return true }
        var names = Set<String>()
        for group in conceptGroups {
            if group.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !names.insert(group.name).inserted || group.phraseValues.isEmpty
                || group.phraseValues.contains(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
                return true
            }
        }
        return false
    }

    var advancedCounts: [Int] {
        [Self.lines(queries).count, Self.lines(paperQueries).count, conceptGroups.count,
         Self.lines(exclusions).count, Self.lines(negativePhrases).count]
    }

    static func lines(_ value: String) -> [String] {
        value.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }

    static func reportLanguage(for language: ResolvedAppLanguage) -> ReportLanguageV1 {
        language == .simplifiedChinese ? .chinese : .english
    }
}

struct TopicEditorView: View {
    let store: AppStore
    let localization: LocalizationStore
    let creating: Bool
    let onSaved: () -> Void
    @State private var input: TopicEditorInput
    @State private var advancedExpanded = false

    init(store: AppStore, localization: LocalizationStore, topic: TopicRecordV1, creating: Bool = false, onSaved: @escaping () -> Void = {}) {
        self.store = store; self.localization = localization; self.creating = creating; self.onSaved = onSaved
        _input = State(initialValue: TopicEditorInput(topic: topic))
    }

    var body: some View {
        Form {
            Section(localization.text("topic.basic")) {
                TextField(localization.text("label.topic_name"), text: $input.topic.displayName)
                TextField(localization.text("label.research_focus"), text: $input.topic.researchFocus, axis: .vertical)
                Picker(localization.text("label.report_language"), selection: $input.topic.reportLanguage) {
                    Text("中文").tag(ReportLanguageV1.chinese)
                    Text("English").tag(ReportLanguageV1.english)
                }
                Toggle(localization.text("setting.pause_topic"), isOn: $input.topic.isPaused)
            }
            Section {
                DisclosureGroup(localization.text("topic.advanced"), isExpanded: $advancedExpanded) {
                    LabeledContent(localization.text("label.topic_id"), value: input.topic.id)
                    multiline("label.search_queries", text: $input.queries)
                    multiline("label.paper_queries", text: $input.paperQueries)
                    multiline("label.exclusions", text: $input.exclusions)
                    multiline("label.negative_phrases", text: $input.negativePhrases)
                    VStack(alignment: .leading) {
                        Text(localization.text("label.concept_groups")).font(.headline)
                        ForEach($input.conceptGroups) { $group in
                            VStack(alignment: .leading) {
                                HStack {
                                    TextField(localization.text("label.group_name"), text: $group.name)
                                    Button {
                                        input.conceptGroups.removeAll { $0.id == group.id }
                                    } label: { Image(systemName: "minus.circle") }
                                        .help(localization.text("action.remove_group"))
                                        .accessibilityLabel(localization.text("action.remove_group"))
                                }
                                multiline("label.group_phrases", text: $group.phrases)
                            }
                        }
                        Button {
                            input.conceptGroups.append(ConceptGroupInput())
                        } label: { Label(localization.text("action.add_group"), systemImage: "plus") }
                    }
                }
            }
            Section(localization.text("topic.review")) {
                ForEach(Array(zip(["label.search_queries", "label.paper_queries", "label.concept_groups", "label.exclusions", "label.negative_phrases"], input.advancedCounts)), id: \.0) { key, count in
                    LabeledContent(localization.text(key), value: String(count))
                }
                Button(localization.text("action.save")) {
                    if input.hasInvalidAdvancedFields { advancedExpanded = true }
                    if store.performAction({ try store.saveTopic(input.candidate(), creating: creating) }) { onSaved() }
                }
                .disabled(store.behaviorChangesBlocked)
                AppActionErrorView(store: store, localization: localization)
            }
        }
        .formStyle(.grouped)
    }

    private func multiline(_ key: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading) {
            Text(localization.text(key))
            TextEditor(text: text).frame(minHeight: 64, maxHeight: 100)
                .font(.body).border(.separator)
                .accessibilityLabel(localization.text(key))
        }
    }
}

struct TopicsView: View {
    let store: AppStore
    let localization: LocalizationStore
    @State private var newTopic: TopicRecordV1?

    var body: some View {
        VStack(alignment: .leading) {
            HStack {
                Picker(localization.text("nav.topics"), selection: Binding(
                    get: { store.selectedTopic?.id ?? "" },
                    set: { id in store.performAction { try store.selectTopic(id) } }
                )) {
                    ForEach(store.configuration.topics) { topic in
                        Text(topic.displayName).tag(topic.id)
                    }
                }
                Button {
                    newTopic = TopicRecordV1(id: UUID().uuidString.lowercased(), displayName: "", researchFocus: "", queries: [], paperQueries: [], reportLanguage: TopicEditorInput.reportLanguage(for: localization.resolvedLanguage))
                } label: { Label(localization.text("action.new_topic"), systemImage: "plus") }
                    .disabled(store.behaviorChangesBlocked)
            }.padding()
            if let topic = store.selectedTopic {
                TopicEditorView(store: store, localization: localization, topic: topic).id(topic.id)
            }
        }
        .sheet(item: $newTopic) { topic in
            VStack {
                TopicEditorView(store: store, localization: localization, topic: topic, creating: true) { newTopic = nil }
                Button(localization.text("action.cancel")) { newTopic = nil }.padding()
            }.frame(minWidth: 540, minHeight: 600)
        }
    }
}
