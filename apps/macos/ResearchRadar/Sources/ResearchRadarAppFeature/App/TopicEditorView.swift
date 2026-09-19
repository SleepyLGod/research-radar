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
            guard !group.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  result.conceptGroups[group.name] == nil,
                  !group.phraseValues.isEmpty else { throw AppStoreError.invalidTopic }
            result.conceptGroups[group.name] = group.phraseValues
        }
        guard !result.displayName.isEmpty, !result.researchFocus.isEmpty,
              !result.queries.isEmpty, !result.paperQueries.isEmpty,
              result.conceptGroups.allSatisfy({ !$0.key.isEmpty && !$0.value.isEmpty && $0.value.allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } }) else {
            throw AppStoreError.invalidTopic
        }
        return result
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

    init(store: AppStore, localization: LocalizationStore, topic: TopicRecordV1, creating: Bool = false, onSaved: @escaping () -> Void = {}) {
        self.store = store; self.localization = localization; self.creating = creating; self.onSaved = onSaved
        _input = State(initialValue: TopicEditorInput(topic: topic))
    }

    var body: some View {
        Form {
            LabeledContent(localization.text("label.topic_id"), value: input.topic.id)
            TextField(localization.text("label.topic_name"), text: $input.topic.displayName)
            TextField(localization.text("label.research_focus"), text: $input.topic.researchFocus, axis: .vertical)
            multiline("label.search_queries", text: $input.queries)
            multiline("label.paper_queries", text: $input.paperQueries)
            multiline("label.exclusions", text: $input.exclusions)
            multiline("label.negative_phrases", text: $input.negativePhrases)
            Section(localization.text("label.concept_groups")) {
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
            Picker(localization.text("label.report_language"), selection: $input.topic.reportLanguage) {
                Text("中文").tag(ReportLanguageV1.chinese)
                Text("English").tag(ReportLanguageV1.english)
            }
            Toggle(localization.text("setting.pause_topic"), isOn: $input.topic.isPaused)
            Button(localization.text("action.save")) {
                if store.performAction({ try store.saveTopic(input.candidate(), creating: creating) }) { onSaved() }
            }
            .disabled(store.behaviorChangesBlocked)
            AppActionErrorView(store: store, localization: localization)
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
            HSplitView {
                List(store.configuration.topics, selection: Binding(
                    get: { store.selectedTopic?.id },
                    set: { id in if let id { store.performAction { try store.selectTopic(id) } } }
                )) { topic in
                    Label(topic.displayName, systemImage: topic.isPaused ? "pause.circle" : "text.magnifyingglass")
                }.frame(minWidth: 130, idealWidth: 170, maxWidth: 230)
                if let topic = store.selectedTopic {
                    TopicEditorView(store: store, localization: localization, topic: topic).id(topic.id)
                }
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
