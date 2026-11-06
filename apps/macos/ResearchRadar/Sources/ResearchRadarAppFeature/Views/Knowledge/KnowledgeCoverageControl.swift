import ResearchRadarCore
import SwiftUI

/// Differences stay out of the canvas; selecting one opens its existing ledger history.
struct KnowledgeCoverageControl: View {
    let coverage: KnowledgeCoverageV1
    let localization: LocalizationStore
    var openPaper: ((String) -> Void)?
    @State private var showingChanges = false

    private var summary: String {
        [(coverage.newCount, "knowledge.coverage.new_count"),
         (coverage.updatedCount, "knowledge.coverage.updated_count"),
         (coverage.removedCount, "knowledge.coverage.removed_count")]
            .filter { $0.0 > 0 }.map { String(format: localization.text($0.1), $0.0) }
            .joined(separator: " · ")
    }

    var body: some View {
        Button { showingChanges.toggle() } label: {
            Label(summary, systemImage: "circle.badge.clock").font(.system(size: 12)).monospacedDigit()
        }.buttonStyle(.borderless)
            .help(localization.text("knowledge.coverage.pending"))
            .popover(isPresented: $showingChanges) {
                VStack(alignment: .leading, spacing: 12) {
                    Text(localization.text("knowledge.coverage.pending")).font(.system(size: 14, weight: .semibold))
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(coverage.changes) { paper in
                                Button {
                                    showingChanges = false
                                    openPaper?(paper.paperID)
                                } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        HStack(alignment: .top, spacing: 10) {
                                            Text(paper.title).font(.system(size: 13, weight: .medium))
                                                .lineLimit(3).help(paper.title)
                                            Spacer(minLength: 0)
                                            Image(systemName: "chevron.right").font(.system(size: 11))
                                        }
                                        HStack {
                                            Text(localization.text(paper.status.localizationKey))
                                            if let version = paper.version { Text(version).monospaced() }
                                        }.font(.system(size: 12)).foregroundStyle(.secondary)
                                    }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 10)
                                }.buttonStyle(.plain).disabled(openPaper == nil)
                                Divider()
                            }
                        }
                    }.frame(maxHeight: 300)
                }.padding(16).frame(width: 380, alignment: .leading)
            }
    }
}
