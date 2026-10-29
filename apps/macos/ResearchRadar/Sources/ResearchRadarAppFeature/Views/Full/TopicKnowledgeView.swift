import ResearchRadarCore
import SwiftUI

struct TopicKnowledgeView: View {
    let store: AppStore
    let model: TopicKnowledgeModel
    let localization: LocalizationStore
    @State private var confirming = false
    @State private var confirmedScope: OrganizeTopicPayloadV1?
    @State private var showingInfo = false

    private var topicID: String { store.selectedTopic?.id ?? "" }
    private var progress: TopicKnowledgePresentation { .init(topicID: topicID, jobs: store.jobs) }
    private var route: String {
        guard let route = store.configuration.routes.first(where: { $0.task == "deep_reading" }) else { return "—" }
        return "\(route.providerID) / \(route.model)"
    }

    var body: some View {
        HStack(spacing: 10) {
            Button { showingInfo.toggle() } label: { Image(systemName: "info.circle") }
                .buttonStyle(.borderless).help(localization.text("knowledge.title"))
                .accessibilityLabel(localization.text("knowledge.title"))
                .popover(isPresented: $showingInfo, arrowEdge: .bottom) { snapshotInfo }
            if progress.isActive {
                Button { Task { await store.cancelActiveJob() } } label: {
                    Label(localization.text("knowledge.stop"), systemImage: "stop.fill")
                }.disabled(store.cancellationRequested || progress.job?.state == .pending)
            } else {
                Button { confirmedScope = store.selectedTopicOrganization; confirming = true } label: {
                    Label(localization.text(model.current(for: topicID) == nil ? "knowledge.organize" : "knowledge.reorganize"),
                          systemImage: "square.stack.3d.up")
                }.disabled(store.behaviorChangesBlocked || store.selectedTopicOrganization == nil)
            }
        }
        .controlSize(.small).fixedSize()
        .confirmationDialog(localization.text("knowledge.confirm"), isPresented: $confirming, titleVisibility: .visible) {
            Button(localization.text("knowledge.organize")) {
                if let scope = confirmedScope { Task { await store.organizeSelectedTopic(expectedScope: scope) } }
            }
            Button(localization.text("action.cancel"), role: .cancel) {}
        } message: {
            Text(localization.text("knowledge.confirm_detail") + "\n" + route)
        }
    }

    private var snapshotInfo: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(localization.text("knowledge.title")).font(.system(size: 14, weight: .semibold))
            if let summary = model.current(for: topicID) {
                HStack(spacing: 12) {
                    count(summary.paperCount, "knowledge.papers")
                    count(summary.groupCount, "knowledge.groups")
                }
                HStack(spacing: 12) {
                    count(summary.featureCount, "knowledge.features")
                    count(summary.relationCount, "knowledge.relations")
                }
                Text(String(summary.createdAt.prefix(10))).monospacedDigit().foregroundStyle(.secondary)
            } else { Text(localization.text("knowledge.empty")) }
            if let graph = model.graph(for: topicID) {
                let selected = model.graphSelection(for: topicID).facetID
                if let facet = graph.facets.first(where: { $0.id == selected }) {
                    Divider()
                    Text(facet.label).fontWeight(.medium)
                    Text(facet.description).fixedSize(horizontal: false, vertical: true)
                }
            }
            Divider()
            Text(localization.text("graph.interpretation_help")).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }.font(.system(size: 13)).padding(18).frame(width: 310, alignment: .leading)
    }

    private func count(_ value: Int, _ key: String) -> some View {
        Text("\(value) \(localization.text(key))").monospacedDigit()
    }
}

/// Exceptional states stay visible; quiet snapshot metadata lives in the information popover.
struct TopicKnowledgeNotice: View {
    let store: AppStore
    let model: TopicKnowledgeModel
    let localization: LocalizationStore
    private var topicID: String { store.selectedTopic?.id ?? "" }
    private var progress: TopicKnowledgePresentation { .init(topicID: topicID, jobs: store.jobs) }

    var body: some View {
        let status = progress.statusKey.flatMap { $0 == "knowledge.ready" ? nil : $0 }
        let errorCode = progress.isActive ? nil : progress.job?.error?.code
        if status != nil || errorCode != nil || model.error(for: topicID) != nil {
            VStack(alignment: .leading, spacing: 6) {
                if let status {
                    Text(localization.text(store.cancellationRequested && progress.isActive ? "today.cancelling" : status))
                }
                if let errorCode {
                    Text(UserFacingErrorCatalog(localization: localization).message(for: errorCode)).foregroundStyle(.secondary)
                }
                if let key = model.error(for: topicID) { Text(localization.text(key)).foregroundStyle(.secondary) }
            }.font(.system(size: 12)).frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20).padding(.bottom, 10)
        }
    }
}
